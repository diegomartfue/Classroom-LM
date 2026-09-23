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
place because nothing looked clear). Curved path commands (C/S/Q/T/A) are not
cheaply reducible to exact segments, so those still fall back to the
over-approximated bounding box from _curved_path_bbox().

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


def _path_points(d: str) -> list[tuple[float, float]]:
    """Coordinates a path's 'd' visits: exact for straight segments (M/L/H/V),
    an over-approximation for curves and arcs (control points / an arc's
    radius box are included). Over-approximating only ever widens the
    estimated bbox, which is safe for a collision check — it can cause an
    unnecessary nudge, never let a real overlap through undetected."""
    points: list[tuple[float, float]] = []
    if not d:
        return points
    cur = (0.0, 0.0)
    start = (0.0, 0.0)
    tokens = re.findall(r"[MLHVCSQTAZmlhvcsqtaz]|-?\d*\.?\d+(?:[eE][-+]?\d+)?", d)

    idx = 0
    while idx < len(tokens):
        tok = tokens[idx]
        if not (tok[0].isalpha()):
            idx += 1  # stray number with no preceding command; skip defensively
            continue
        cmd = tok
        idx += 1
        c = cmd.upper()
        rel = cmd.islower()
        argc = _ARG_COUNTS.get(c)
        if argc is None:
            continue  # unknown command letter; nothing more we can parse safely
        if argc == 0:  # Z / z
            cur = start
            points.append(cur)
            continue

        first_pair = True
        while idx + argc <= len(tokens) and all(
            not tokens[idx + k][0].isalpha() for k in range(argc)
        ):
            nums = [float(tokens[idx + k]) for k in range(argc)]
            idx += argc

            if c in ("M", "L", "T"):
                x, y = nums
                if rel:
                    x, y = cur[0] + x, cur[1] + y
                cur = (x, y)
                if c == "M" and first_pair:
                    start = cur
                points.append(cur)
            elif c == "H":
                x = cur[0] + nums[0] if rel else nums[0]
                cur = (x, cur[1])
                points.append(cur)
            elif c == "V":
                y = cur[1] + nums[0] if rel else nums[0]
                cur = (cur[0], y)
                points.append(cur)
            elif c == "C":
                for (x, y) in [(nums[0], nums[1]), (nums[2], nums[3]), (nums[4], nums[5])]:
                    px, py = (cur[0] + x, cur[1] + y) if rel else (x, y)
                    points.append((px, py))
                cur = points[-1]
            elif c in ("S", "Q"):
                for (x, y) in [(nums[0], nums[1]), (nums[2], nums[3])]:
                    px, py = (cur[0] + x, cur[1] + y) if rel else (x, y)
                    points.append((px, py))
                cur = points[-1]
            elif c == "A":
                rx, ry = nums[0], nums[1]
                x, y = nums[5], nums[6]
                if rel:
                    x, y = cur[0] + x, cur[1] + y
                # Coarse arc-extent estimate: the endpoint plus a box padded
                # by (rx, ry) around both the start and end points.
                points.append((x, y))
                points.append((x - rx, y - ry))
                points.append((x + rx, y + ry))
                points.append((cur[0] - rx, cur[1] - ry))
                points.append((cur[0] + rx, cur[1] + ry))
                cur = (x, y)

            first_pair = False
            if c == "M":
                # Per the SVG spec, extra coordinate pairs after the first M
                # are implicit lineto commands.
                c, cmd, rel = "L", ("l" if rel else "L"), rel
    return points


def _text_bbox(el: ET.Element) -> BBox:
    x = _num(el.get("x"))
    y = _num(el.get("y"))
    font_size = _num(el.get("font-size"), 16.0)
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


def _path_command_letters(d: str) -> set[str]:
    return set(c.upper() for c in re.findall(r"[A-Za-z]", d or ""))


def _curved_path_bbox(d: str) -> BBox | None:
    """Bounding-box fallback for a <path> that uses curve/arc commands —
    control points and arc-radius boxes only ever widen the estimate, so
    this remains a safe (if coarse) over-approximation, per _path_points."""
    pts = _path_points(d)
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


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


def _candidates(center: tuple[float, float], orig_xy: tuple[float, float]) -> list[tuple[float, float]]:
    """Offsets to try, in order: 14px further from the diagram center along
    the label's own existing offset direction, then the four cardinal
    directions at 14px, then the same four at 28px."""
    cx, cy = center
    x, y = orig_xy
    ddx, ddy = x - cx, y - cy
    dist = (ddx ** 2 + ddy ** 2) ** 0.5
    away = (ddx / dist, ddy / dist) if dist > 1e-6 else (0.0, -1.0)
    return [(away[0] * 14.0, away[1] * 14.0)] + _CARDINAL_14 + _CARDINAL_28


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
    geom_bboxes: list[BBox] = []    # curved paths only — can't cheaply segment these
    geom_segments: list[Segment] = []
    filled_regions: list[list[Point]] = []

    for el in root.iter():
        if id(el) in defs_ids:
            continue
        tag = _local(el.tag)
        if tag == "text":
            texts.append([el, _text_bbox(el)])
            continue
        if tag not in _GEOMETRY_TAGS or _is_invisible(el):
            continue

        if tag == "line":
            p1 = (_num(el.get("x1")), _num(el.get("y1")))
            p2 = (_num(el.get("x2")), _num(el.get("y2")))
            geom_segments.append((p1, p2))
        elif tag == "polygon":
            pts = _polygon_points(el.get("points", ""))
            if len(pts) >= 2:
                geom_segments.extend(_closed_segments(pts))
                if len(pts) >= 3 and _is_filled(el):
                    filled_regions.append(pts)
        elif tag == "path":
            d = el.get("d", "")
            letters = _path_command_letters(d)
            if letters and letters <= _STRAIGHT_PATH_CMDS:
                pts = _path_points(d)  # exact for straight-only commands
                if len(pts) >= 2:
                    geom_segments.extend(_open_segments(pts))
                    if "Z" in letters and len(pts) >= 3 and _is_filled(el):
                        filled_regions.append(pts)
            else:
                bbox = _curved_path_bbox(d)
                if bbox is not None:
                    geom_bboxes.append(bbox)

    def collides(self_index: int, bbox: BBox) -> bool:
        for g in geom_bboxes:
            if _overlaps(bbox, g):
                return True
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
        for dx, dy in _candidates(center, (x0, y0)):
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
            logger.debug(
                "fix_label_collisions: no clear spot for label %r; left in place",
                "".join(el.itertext()),
            )

    if moved == 0:
        # No change made: return the original string verbatim (byte
        # identical) rather than round-tripping through ElementTree, which
        # can reorder/reformat harmlessly but needlessly.
        return original

    logger.info("fix_label_collisions: moved %d label(s)", moved)
    return ET.tostring(root, encoding="unicode")
