"""
svg_layout.py — deterministic post-processing pass over visualizer() SVG
output: nudges colliding <text> labels apart from each other and off lines,
paths, and polygons, without ever touching geometry.

Geometry collision is segment-based, not bbox-based, for <line>, <polygon>,
and straight-only <path> data (M/L/H/V/Z): a label is tested against the
actual edges (and, for a filled shape, against its interior), not against the
element's overall bounding box. A ramp/incline polygon's bbox can cover most
of the canvas even though the shape itself is a thin triangle — bbox-only
collision made every candidate position "collide" with that oversized box, so
a label already touching the hypotenuse could never be moved (the reported
bug: "f_k", "W", and "θ" labels sitting on the incline's sloped edge, left in
place because nothing looked clear). Curves and arcs (C/S/Q/T/A) are sampled
into short segments too (_path_polylines). They used to fall back to a box
padded by the arc radius around both endpoints — for an angle arc that box
covered the whole corner where the "θ = 30°" label has to go, so the label
could never be placed.

Coordinates respect translate() on the element and its ancestor groups, and
font-size is inherited from ancestors (attribute or style). Anything under
a rotate/scale/matrix/skew transform can't be measured this simply, so it is
neither moved nor treated as an obstacle.

Why this exists: VISUALIZER_PROMPT's LAYOUT PROCESS asks Opus to plan label
placement so nothing overlaps, but it is a text-only spec — the model has no
way to actually measure what it drew, so it cannot self-check bounding boxes.
The prompt rules cut down on collisions but cannot eliminate them (see the
beam and pendulum diagrams from earlier verification runs, where a force
label and a support-point label rendered as overlapping glyphs). This module
is the deterministic backstop: parse the SVG, estimate every text and
geometry bounding box, and nudge only the colliding text elements to a
nearby clear spot.

Dependency choice — xml.etree, not lxml:
Both xml.etree (stdlib) and lxml are importable in this venv, but lxml is
NOT listed in backend/requirements.txt; it is pulled in transitively by
another dependency (chromadb), not something this codebase declares or can
rely on staying installed. xml.etree is stdlib, always available, and
sufficient for SVG's simple, non-DTD XML — so it is the one actually "already
a dependency" in the sense that matters (declared, not just present).

Text measurement — a fixed heuristic, not PIL ImageFont:
Pillow is also importable here, but only as a transitive dependency of
matplotlib (which uses it for image I/O), not a declared backend requirement
either. Depending on it for font metrics would be depending on an
implementation detail of an unrelated library. So text bounding boxes use the
estimate specified for this pass instead: 0.55 * font_size * len(text) wide,
1.2 * font_size tall. This is coarse — real glyph widths vary by character —
but it only needs to be good enough to tell "these two labels probably
overlap," not pixel-exact, and it adds no risk of silently losing font
metrics if Pillow's transitive path ever changes.
"""
from __future__ import annotations

import logging
import math
import re
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

# Elements considered "geometry" that a label must never cross. Deliberately
# excludes <rect>/<circle>: a body outline or background rect would otherwise
# collide with almost every label near it, and VISUALIZER_PROMPT rule 6
# already handles keeping labels outside the body outline.
_GEOMETRY_TAGS = {"line", "path", "polygon"}

_PADDING = 4.0          # required clearance between any two bounding boxes
_MARGIN = 30.0          # required clearance from the viewBox edge
_MAX_TOTAL_MOVE = 40.0  # a label may never move farther than this from its start

# Candidate offsets tried (in order) after the "move further from the
# diagram center along the label's existing offset direction" candidate,
# which is computed per-label in _candidates() since it depends on position.
_CARDINAL_14 = [(0.0, -14.0), (0.0, 14.0), (-14.0, 0.0), (14.0, 0.0)]
_CARDINAL_28 = [(0.0, -28.0), (0.0, 28.0), (-28.0, 0.0), (28.0, 0.0)]

_ARG_COUNTS = {"M": 2, "L": 2, "T": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "A": 7, "Z": 0}

# A <path> using only these commands is exactly reducible to line segments —
# no curve/arc approximation needed, so it gets the precise segment/interior
# treatment instead of the bbox fallback.
_STRAIGHT_PATH_CMDS = {"M", "L", "H", "V", "Z"}

BBox = tuple  # (xmin, ymin, xmax, ymax)
Point = tuple  # (x, y)
Segment = tuple  # (Point, Point)


def _local(tag: str) -> str:
    """Tag name without its namespace, e.g. '{...}text' -> 'text'."""
    return tag.rsplit("}", 1)[-1]


def _num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fmt(value: float) -> str:
    """1 decimal place at most, matching VISUALIZER_PROMPT's own compactness
    rule ('no unnecessary... decimals beyond 1 place')."""
    if value == int(value):
        return str(int(value))
    return f"{value:.1f}"


def _parse_viewbox(root: ET.Element) -> tuple[float, float, float, float]:
    vb = root.get("viewBox")
    if vb:
        parts = vb.replace(",", " ").split()
        if len(parts) == 4:
            try:
                return (float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]))
            except ValueError:
                pass
    # No usable viewBox: fall back to width/height, then VISUALIZER_PROMPT's
    # own default canvas size.
    w = _num(root.get("width"), 600.0)
    h = _num(root.get("height"), 400.0)
    return (0.0, 0.0, w, h)


_CURVE_SAMPLES = 12


def _arc_points(p0: Point, rx: float, ry: float, phi_deg: float, large: bool,
                sweep: bool, p1: Point) -> list[Point]:
    """Points along an SVG elliptical arc, endpoint p0 excluded (SVG spec
    F.6.5 endpoint-to-center conversion)."""
    if p0 == p1:
        return []
    rx, ry = abs(rx), abs(ry)
    if rx == 0 or ry == 0:
        return [p1]
    phi = math.radians(phi_deg)
    cos_p, sin_p = math.cos(phi), math.sin(phi)
    dx2, dy2 = (p0[0] - p1[0]) / 2.0, (p0[1] - p1[1]) / 2.0
    x1p = cos_p * dx2 + sin_p * dy2
    y1p = -sin_p * dx2 + cos_p * dy2
    lam = (x1p / rx) ** 2 + (y1p / ry) ** 2
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        coef = -coef
    cxp, cyp = coef * rx * y1p / ry, -coef * ry * x1p / rx
    cx = cos_p * cxp - sin_p * cyp + (p0[0] + p1[0]) / 2.0
    cy = sin_p * cxp + cos_p * cyp + (p0[1] + p1[1]) / 2.0

    def angle(ux, uy, vx, vy):
        return math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)

    ux, uy = (x1p - cxp) / rx, (y1p - cyp) / ry
    vx, vy = (-x1p - cxp) / rx, (-y1p - cyp) / ry
    theta1 = angle(1.0, 0.0, ux, uy)
    dtheta = angle(ux, uy, vx, vy)
    if not sweep and dtheta > 0:
        dtheta -= 2 * math.pi
    elif sweep and dtheta < 0:
        dtheta += 2 * math.pi
    pts = []
    for i in range(1, _CURVE_SAMPLES + 1):
        t = theta1 + dtheta * i / _CURVE_SAMPLES
        pts.append((cx + rx * math.cos(t) * cos_p - ry * math.sin(t) * sin_p,
                    cy + rx * math.cos(t) * sin_p + ry * math.sin(t) * cos_p))
    pts[-1] = p1
    return pts


def _bezier_points(ctrl: list[Point]) -> list[Point]:
    """Points along a quadratic/cubic Bezier, first control point excluded."""
    pts = []
    for i in range(1, _CURVE_SAMPLES + 1):
        t = i / _CURVE_SAMPLES
        layer = list(ctrl)
        while len(layer) > 1:
            layer = [((1 - t) * a[0] + t * b[0], (1 - t) * a[1] + t * b[1])
                     for a, b in zip(layer, layer[1:])]
        pts.append(layer[0])
    return pts


def _path_polylines(d: str) -> list[tuple[list[Point], bool]]:
    """Each subpath of ``d`` as (points, closed): exact for straight
    commands, sampled for curves and arcs."""
    polylines: list[tuple[list[Point], bool]] = []
    if not d:
        return polylines
    tokens = re.findall(r"[MLHVCSQTAZmlhvcsqtaz]|[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", d)
    cur = start = (0.0, 0.0)
    pts: list[Point] = []
    last_ctrl: Point | None = None   # for S/T reflection
    last_cmd = ""

    def flush(closed: bool):
        nonlocal pts
        if len(pts) >= 2:
            polylines.append((pts, closed))
        pts = []

    idx = 0
    while idx < len(tokens):
        tok = tokens[idx]
        if not tok[0].isalpha():
            idx += 1  # stray number with no preceding command; skip defensively
            continue
        cmd = tok
        idx += 1
        c, rel = cmd.upper(), cmd.islower()
        argc = _ARG_COUNTS.get(c)
        if argc is None:
            continue
        if argc == 0:  # Z / z
            if pts:
                pts.append(start)
            flush(closed=True)
            cur, last_ctrl, last_cmd = start, None, "Z"
            continue
        first_pair = True
        while idx + argc <= len(tokens) and all(
            not tokens[idx + k][0].isalpha() for k in range(argc)
        ):
            n = [float(tokens[idx + k]) for k in range(argc)]
            idx += argc

            def absolute(x, y):
                return (cur[0] + x, cur[1] + y) if rel else (x, y)

            if c == "M":
                if first_pair:
                    flush(closed=False)
                    cur = start = absolute(n[0], n[1])
                    pts = [cur]
                else:  # implicit lineto
                    cur = absolute(n[0], n[1])
                    pts.append(cur)
                last_ctrl = None
            elif c == "L":
                cur = absolute(n[0], n[1])
                pts.append(cur)
                last_ctrl = None
            elif c == "H":
                cur = (cur[0] + n[0] if rel else n[0], cur[1])
                pts.append(cur)
                last_ctrl = None
            elif c == "V":
                cur = (cur[0], cur[1] + n[0] if rel else n[0])
                pts.append(cur)
                last_ctrl = None
            elif c in ("C", "S"):
                if c == "C":
                    c1, c2, end = absolute(n[0], n[1]), absolute(n[2], n[3]), absolute(n[4], n[5])
                else:
                    c1 = ((2 * cur[0] - last_ctrl[0], 2 * cur[1] - last_ctrl[1])
                          if last_ctrl and last_cmd in ("C", "S") else cur)
                    c2, end = absolute(n[0], n[1]), absolute(n[2], n[3])
                pts.extend(_bezier_points([cur, c1, c2, end]))
                cur, last_ctrl = end, c2
            elif c in ("Q", "T"):
                if c == "Q":
                    q, end = absolute(n[0], n[1]), absolute(n[2], n[3])
                else:
                    q = ((2 * cur[0] - last_ctrl[0], 2 * cur[1] - last_ctrl[1])
                         if last_ctrl and last_cmd in ("Q", "T") else cur)
                    end = absolute(n[0], n[1])
                pts.extend(_bezier_points([cur, q, end]))
                cur, last_ctrl = end, q
            elif c == "A":
                end = absolute(n[5], n[6])
                pts.extend(_arc_points(cur, n[0], n[1], n[2], bool(n[3]), bool(n[4]), end))
                cur, last_ctrl = end, None
            if not pts:
                pts = [cur]
            last_cmd = c
            first_pair = False
    flush(closed=False)
    return polylines


_TRANSLATE_RE = re.compile(r"translate\(\s*([-+]?[\d.eE+-]+)(?:[\s,]+([-+]?[\d.eE+-]+))?\s*\)")


def _parse_transform(value: str | None) -> tuple[float, float] | None:
    """(tx, ty) for a transform made only of translate()s; None for any
    other transform (rotate/scale/matrix/skew), which this pass can't
    measure through."""
    if not value or not value.strip():
        return (0.0, 0.0)
    tx = ty = 0.0
    rest = value
    for m in _TRANSLATE_RE.finditer(value):
        tx += float(m.group(1))
        ty += float(m.group(2) or 0.0)
        rest = rest.replace(m.group(0), "", 1)
    return (tx, ty) if not rest.strip(" ,") else None


_FONT_SIZE_STYLE_RE = re.compile(r"font-size\s*:\s*([\d.]+)")


def _own_font_size(el: ET.Element) -> float | None:
    m = _FONT_SIZE_STYLE_RE.search(el.get("style", "") or "")
    raw = m.group(1) if m else el.get("font-size")
    if raw is None:
        return None
    m = re.match(r"\s*([\d.]+)", str(raw))
    return float(m.group(1)) if m else None


def _text_bbox(el: ET.Element, font_size: float | None = None,
               offset: Point = (0.0, 0.0)) -> BBox:
    """Estimated bbox in canvas coordinates. ``font_size`` is the inherited
    size when the element doesn't set its own; ``offset`` is the summed
    translate() of its ancestors."""
    x = _num(el.get("x")) + offset[0]
    y = _num(el.get("y")) + offset[1]
    font_size = _own_font_size(el) or font_size or 16.0
    anchor = el.get("text-anchor", "start")
    baseline = el.get("dominant-baseline", "")
    text = "".join(el.itertext())

    width = 0.55 * font_size * max(len(text), 1)
    height = 1.2 * font_size

    if anchor == "middle":
        xmin, xmax = x - width / 2, x + width / 2
    elif anchor == "end":
        xmin, xmax = x - width, x
    else:
        xmin, xmax = x, x + width

    if baseline == "middle":
        ymin, ymax = y - height / 2, y + height / 2
    else:
        # Default alphabetic baseline: most of a glyph sits above y (ascent),
        # a little below (descent).
        ymin, ymax = y - 0.8 * font_size, y + 0.4 * font_size

    return (xmin, ymin, xmax, ymax)


def _polygon_points(points_attr: str) -> list[Point]:
    coords = re.findall(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?", points_attr or "")
    nums = [float(n) for n in coords]
    return list(zip(nums[0::2], nums[1::2]))


def _is_filled(el: ET.Element) -> bool:
    """SVG's default fill is black — a shape is filled unless fill is
    explicitly 'none'. Missing attribute therefore means filled."""
    return el.get("fill", "").strip().lower() != "none"


def _closed_segments(points: list[Point]) -> list[Segment]:
    """Consecutive edges of a closed shape, including the edge back to the
    start (used for <polygon>, which SVG always implicitly closes)."""
    n = len(points)
    return [(points[i], points[(i + 1) % n]) for i in range(n)] if n >= 2 else []


def _open_segments(points: list[Point]) -> list[Segment]:
    """Consecutive edges of an already-explicit point sequence (used for a
    straight-only <path>, whose points already include any Z closing point
    _path_points appended)."""
    return [(points[i], points[i + 1]) for i in range(len(points) - 1)]


def _inflate(bbox: BBox, pad: float) -> BBox:
    x0, y0, x1, y1 = bbox
    return (x0 - pad, y0 - pad, x1 + pad, y1 + pad)


def _bbox_center(bbox: BBox) -> Point:
    x0, y0, x1, y1 = bbox
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


def _point_in_rect(p: Point, rect: BBox) -> bool:
    x, y = p
    x0, y0, x1, y1 = rect
    return x0 <= x <= x1 and y0 <= y <= y1


def _ccw(a: Point, b: Point, c: Point) -> float:
    return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a: Point, b: Point, p: Point) -> bool:
    """True when p, known collinear with a-b, lies within their span."""
    eps = 1e-9
    return (min(a[0], b[0]) - eps <= p[0] <= max(a[0], b[0]) + eps and
            min(a[1], b[1]) - eps <= p[1] <= max(a[1], b[1]) + eps)


def _segments_intersect(p1: Point, p2: Point, p3: Point, p4: Point) -> bool:
    d1, d2 = _ccw(p3, p4, p1), _ccw(p3, p4, p2)
    d3, d4 = _ccw(p1, p2, p3), _ccw(p1, p2, p4)
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True
    if d1 == 0 and _on_segment(p3, p4, p1):
        return True
    if d2 == 0 and _on_segment(p3, p4, p2):
        return True
    if d3 == 0 and _on_segment(p1, p2, p3):
        return True
    if d4 == 0 and _on_segment(p1, p2, p4):
        return True
    return False


def _segment_intersects_rect(p1: Point, p2: Point, rect: BBox) -> bool:
    """True when segment p1-p2 touches or enters ``rect`` (already padded by
    the caller)."""
    rx0, ry0, rx1, ry1 = rect
    sx0, sx1 = sorted((p1[0], p2[0]))
    sy0, sy1 = sorted((p1[1], p2[1]))
    if sx1 < rx0 or sx0 > rx1 or sy1 < ry0 or sy0 > ry1:
        return False  # cheap reject: segment's own bbox misses the rect
    if _point_in_rect(p1, rect) or _point_in_rect(p2, rect):
        return True
    corners = [(rx0, ry0), (rx1, ry0), (rx1, ry1), (rx0, ry1)]
    for a, b in zip(corners, corners[1:] + corners[:1]):
        if _segments_intersect(p1, p2, a, b):
            return True
    return False


def _point_in_polygon(p: Point, poly: list[Point]) -> bool:
    """Standard ray-casting test. Only used to catch a label sitting fully
    *inside* a filled shape without crossing any edge — edge-crossing itself
    is already caught by the segment tests, so this only needs one point
    (the label's bbox center)."""
    x, y = p
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            x_at_y = (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
            if x < x_at_y:
                inside = not inside
        j = i
    return inside


def _is_invisible(el: ET.Element) -> bool:
    """Fully invisible geometry can't visually collide with anything. This
    also covers the one plausible shape of a 'text halo built as geometry'
    (rather than via paint-order/stroke on <text> itself, which is how our
    own VISUALIZER_PROMPT does it): a stroke='none' fill='none' placeholder
    contributes nothing to render and is skipped here regardless of intent."""
    return el.get("stroke", "") == "none" and el.get("fill", "none") in ("none", "")


def _overlaps(a: BBox, b: BBox, padding: float = _PADDING) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (ax1 + padding <= bx0 or bx1 + padding <= ax0 or
                ay1 + padding <= by0 or by1 + padding <= ay0)


def _within_margin(bbox: BBox, viewbox: tuple[float, float, float, float]) -> bool:
    vx0, vy0, vw, vh = viewbox
    x0, y0, x1, y1 = bbox
    return (x0 >= vx0 + _MARGIN and y0 >= vy0 + _MARGIN and
            x1 <= vx0 + vw - _MARGIN and y1 <= vy0 + vh - _MARGIN)


def _shift(bbox: BBox, dx: float, dy: float) -> BBox:
    x0, y0, x1, y1 = bbox
    return (x0 + dx, y0 + dy, x1 + dx, y1 + dy)


def _margin_shift(bbox: BBox, viewbox: tuple[float, float, float, float]) -> tuple[float, float]:
    """The (dx, dy) that moves ``bbox`` fully inside the margin, last resort
    for a label no candidate offset could place cleanly. Unlike the
    collision-avoidance candidates, this is unconditional — it isn't capped
    at _MAX_TOTAL_MOVE and doesn't check for a resulting collision, because a
    label clipped by the viewBox edge is a hard visual bug (part of it is
    literally invisible), strictly worse than a label that overlaps another
    element but is at least fully visible.

    If bbox is wider or taller than the available interior, only one edge on
    each axis can be satisfied; this still fixes whichever edge was actually
    violated rather than leaving it clipped."""
    vx0, vy0, vw, vh = viewbox
    x0, y0, x1, y1 = bbox
    left, right = vx0 + _MARGIN, vx0 + vw - _MARGIN
    top, bottom = vy0 + _MARGIN, vy0 + vh - _MARGIN

    dx = 0.0
    if x0 < left:
        dx = left - x0
    elif x1 > right:
        dx = right - x1

    dy = 0.0
    if y0 < top:
        dy = top - y0
    elif y1 > bottom:
        dy = bottom - y1

    return dx, dy


_RINGS = (8.0, 14.0, 20.0, 28.0, 34.0, _MAX_TOTAL_MOVE)
_DIRECTIONS = [(math.cos(math.radians(a)), math.sin(math.radians(a)))
               for a in range(0, 360, 30)]


def _candidates(center: tuple[float, float], orig_xy: tuple[float, float],
                normals: list[Point] = ()) -> list[tuple[float, float]]:
    """Offsets to try, nearest first, never beyond _MAX_TOTAL_MOVE. At each
    distance: away from the diagram center, then along the normals of the
    edges the label currently touches (the short way off a sloped edge),
    then 12 evenly spaced directions. Up/down/left/right only used to
    need up to 2x the distance to clear a 30 degree slope."""
    cx, cy = center
    x, y = orig_xy
    ddx, ddy = x - cx, y - cy
    dist = (ddx ** 2 + ddy ** 2) ** 0.5
    away = (ddx / dist, ddy / dist) if dist > 1e-6 else (0.0, -1.0)
    directions = [away]
    for nx, ny in normals:
        directions += [(nx, ny), (-nx, -ny)]
    directions += _DIRECTIONS
    return [(ux * r, uy * r) for r in _RINGS for ux, uy in directions]


def fix_label_collisions(svg: str) -> str:
    """Nudge colliding <text> labels in ``svg`` apart from each other and off
    any <line>/<path>/<polygon> geometry. Returns the input unchanged (never
    raises) if the SVG can't be parsed or anything unexpected happens — this
    pass must never break a diagram trying to improve it."""
    if not svg or not svg.strip():
        return svg
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        logger.warning("fix_label_collisions: could not parse SVG (%s); returning unchanged", exc)
        return svg

    try:
        return _fix(root, svg)
    except Exception:
        logger.warning("fix_label_collisions: unexpected error; returning unchanged SVG", exc_info=True)
        return svg


def _fix(root: ET.Element, original: str) -> str:
    if root.tag.startswith("{"):
        ns_uri = root.tag[1:].split("}", 1)[0]
        ET.register_namespace("", ns_uri)

    viewbox = _parse_viewbox(root)

    # Elements inside <defs> (marker glyphs, etc.) are definitions in their
    # own local coordinate space, not geometry drawn on the canvas — never
    # treat them as something a label could collide with.
    defs_ids: set[int] = set()
    for defs_el in root.iter():
        if _local(defs_el.tag) == "defs":
            defs_ids.update(id(sub) for sub in defs_el.iter())

    texts: list[list] = []          # [element, bbox] pairs, bbox mutated as labels move
    geom_segments: list[Segment] = []
    filled_regions: list[list[Point]] = []
    skipped_transformed = 0

    def shifted(points, off):
        return [(px + off[0], py + off[1]) for px, py in points]

    def walk(el: ET.Element, offset: Point, font_size: float | None):
        nonlocal skipped_transformed
        if id(el) in defs_ids:
            return
        own = _parse_transform(el.get("transform"))
        if own is None:
            skipped_transformed += 1
            return  # rotate/scale/matrix: can't measure what's inside
        offset = (offset[0] + own[0], offset[1] + own[1])
        font_size = _own_font_size(el) or font_size
        tag = _local(el.tag)
        if tag == "text":
            texts.append([el, _text_bbox(el, font_size, offset)])
            return
        if tag in _GEOMETRY_TAGS and not _is_invisible(el):
            if tag == "line":
                p1 = (_num(el.get("x1")) + offset[0], _num(el.get("y1")) + offset[1])
                p2 = (_num(el.get("x2")) + offset[0], _num(el.get("y2")) + offset[1])
                geom_segments.append((p1, p2))
            elif tag == "polygon":
                pts = shifted(_polygon_points(el.get("points", "")), offset)
                if len(pts) >= 2:
                    geom_segments.extend(_closed_segments(pts))
                    if len(pts) >= 3 and _is_filled(el):
                        filled_regions.append(pts)
            elif tag == "path":
                for pts, closed in _path_polylines(el.get("d", "")):
                    pts = shifted(pts, offset)
                    geom_segments.extend(_open_segments(pts))
                    if closed and len(pts) >= 3 and _is_filled(el):
                        filled_regions.append(pts)
        for child in el:
            walk(child, offset, font_size)

    walk(root, (0.0, 0.0), None)
    if skipped_transformed:
        logger.debug("fix_label_collisions: skipped %d element(s) under a non-translate transform",
                     skipped_transformed)

    def touched_normals(bbox: BBox) -> list[Point]:
        padded = _inflate(bbox, _PADDING)
        normals = []
        for p1, p2 in geom_segments:
            if _segment_intersects_rect(p1, p2, padded):
                ex, ey = p2[0] - p1[0], p2[1] - p1[1]
                length = (ex * ex + ey * ey) ** 0.5
                if length > 1e-9:
                    normals.append((-ey / length, ex / length))
        return normals[:4]

    def collides(self_index: int, bbox: BBox) -> bool:
        padded = _inflate(bbox, _PADDING)
        for p1, p2 in geom_segments:
            if _segment_intersects_rect(p1, p2, padded):
                return True
        center = _bbox_center(bbox)
        for poly in filled_regions:
            if _point_in_polygon(center, poly):
                return True
        for j, (_, other_bbox) in enumerate(texts):
            if j != self_index and _overlaps(bbox, other_bbox):
                return True
        return False

    center = (viewbox[0] + viewbox[2] / 2.0, viewbox[1] + viewbox[3] / 2.0)
    moved = 0
    for i, (el, bbox) in enumerate(texts):
        # A label the model placed partly outside the viewBox gets clipped by
        # the canvas even with zero collisions, so a margin violation is
        # treated as a collision too — it goes through the exact same
        # candidate search as an overlapping label.
        if not collides(i, bbox) and _within_margin(bbox, viewbox):
            continue
        x0, y0 = _num(el.get("x")), _num(el.get("y"))
        placed = False
        for dx, dy in _candidates(center, _bbox_center(bbox), touched_normals(bbox)):
            if (dx ** 2 + dy ** 2) ** 0.5 > _MAX_TOTAL_MOVE:
                continue
            new_bbox = _shift(bbox, dx, dy)
            if not _within_margin(new_bbox, viewbox):
                continue
            if collides(i, new_bbox):
                continue
            el.set("x", _fmt(x0 + dx))
            el.set("y", _fmt(y0 + dy))
            texts[i][1] = new_bbox
            moved += 1
            placed = True
            logger.debug(
                "fix_label_collisions: moved label %r by (%.1f, %.1f)",
                "".join(el.itertext()), dx, dy,
            )
            break
        if placed:
            continue

        if not _within_margin(bbox, viewbox):
            # No candidate cleared it, but leaving a margin violation in
            # place means part of the label renders outside the canvas —
            # strictly worse than a residual overlap. Shift it inward just
            # enough to satisfy the margin, collision or not.
            dx, dy = _margin_shift(bbox, viewbox)
            new_bbox = _shift(bbox, dx, dy)
            el.set("x", _fmt(x0 + dx))
            el.set("y", _fmt(y0 + dy))
            texts[i][1] = new_bbox
            moved += 1
            logger.debug(
                "fix_label_collisions: no collision-free candidate for label %r; "
                "shifted inward by (%.1f, %.1f) to clear the margin instead of "
                "leaving it clipped",
                "".join(el.itertext()), dx, dy,
            )
        else:
            # Visible in normal logs: a label still touching geometry is a
            # defect a student will see.
            logger.warning(
                "fix_label_collisions: no clear spot within %.0fpx for label %r; left in place",
                _MAX_TOTAL_MOVE, "".join(el.itertext()),
            )

    if moved == 0:
        # No change made: return the original string verbatim (byte
        # identical) rather than round-tripping through ElementTree, which
        # can reorder/reformat harmlessly but needlessly.
        return original

    logger.info("fix_label_collisions: moved %d label(s)", moved)
    return ET.tostring(root, encoding="unicode")
