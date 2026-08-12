"""
Deterministic FBD renderer for the "Small" dynamics archetype:
a single block/particle, optionally on an incline, with the standard
dynamics force set (weight, normal, friction, applied, tension).

NOT an LLM call. Takes a structured spec (from the visualizer agent) and
draws the same picture every time. No exec of generated code. Standard-force
geometry is computed here so it is always correct; only genuinely free forces
(an applied push at an arbitrary angle) use an angle supplied in the spec.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import io
import base64
import math

NAVY = "#041E42"
ORANGE = "#FF8200"
BLACK = "#0a0a0a"
GRAY = "#9aa0a6"

_SUPPORTED = ("block_on_incline", "block_on_flat", "particle_free")


def _force_angle_deg(force: dict, incline_angle_deg: float) -> float:
    """Global angle (deg, CCW from +x) for a force, by kind.
    Standard forces are computed from the incline angle (always exact);
    applied/tension/other use an explicit angle from the spec."""
    theta = incline_angle_deg or 0.0
    kind = force.get("kind", "applied")
    if kind == "weight":
        return 270.0
    if kind == "normal":
        return 90.0 + theta
    if kind == "friction":
        along = force.get("along", "up_incline")
        return theta + (180.0 if along == "down_incline" else 0.0)
    return float(force.get("angle_deg", 0.0))


def render_fbd(spec: dict) -> str:
    """Return a base64 PNG string, or '' if the spec is not renderable.

    Dynamics mechanisms (``type`` of gear/linkage/mechanism) are handed to the
    dynamics renderer; everything else falls back to the single-body statics FBD
    path below (block on incline/flat, free particle).
    """
    if not spec:
        return ""
    if str(spec.get("type") or "").lower() in _DYNAMICS_TYPES:
        return render_dynamics_diagram(spec)
    if not spec.get("renderable"):
        return ""
    archetype = spec.get("archetype")
    if archetype not in _SUPPORTED:
        return ""

    theta = float(spec.get("incline_angle_deg") or 0.0)
    forces = spec.get("forces", []) or []
    block_label = spec.get("block_label", "")
    t = math.radians(theta)

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.set_xlim(-3, 3)
    ax.set_ylim(-3, 3)
    ax.set_aspect("equal")
    ax.axis("off")

    # --- surface reference + hatching ---------------------------------
    if archetype == "block_on_incline":
        L = 2.7
        ax.plot([-L * math.cos(t), L * math.cos(t)],
                [-L * math.sin(t), L * math.sin(t)],
                color=GRAY, lw=2.5, zorder=1)
        nx, ny = math.sin(t), -math.cos(t)
        for s in [i / 5.0 for i in range(-12, 13)]:
            bx, by = s * math.cos(t), s * math.sin(t)
            ax.plot([bx, bx + 0.22 * nx], [by, by + 0.22 * ny],
                    color=GRAY, lw=1, zorder=1)
    elif archetype == "block_on_flat":
        ax.plot([-2.7, 2.7], [0, 0], color=GRAY, lw=2.5, zorder=1)
        for s in [i / 5.0 for i in range(-12, 13)]:
            ax.plot([s, s - 0.18], [0, -0.22], color=GRAY, lw=1, zorder=1)

    # --- body ---------------------------------------------------------
    if archetype == "particle_free":
        ax.plot(0, 0, "o", color=NAVY, markersize=16, zorder=3)
        cx, cy = 0.0, 0.0
    else:
        half = 0.42
        ox, oy = -math.sin(t) * half, math.cos(t) * half
        corners = []
        for lx, ly in [(-half, -half), (half, -half), (half, half), (-half, half)]:
            rx = lx * math.cos(t) - ly * math.sin(t)
            ry = lx * math.sin(t) + ly * math.cos(t)
            corners.append((rx + ox, ry + oy))
        ax.add_patch(plt.Polygon(corners, closed=True, facecolor=NAVY,
                                 edgecolor=BLACK, lw=1.5, zorder=3))
        cx, cy = ox, oy
        if block_label:
            ax.text(cx, cy, block_label, color="white", ha="center",
                    va="center", fontsize=13, fontweight="bold", zorder=4)

    # --- force arrows -------------------------------------------------
    arrow_len = 1.35
    for f in forces:
        ang = math.radians(_force_angle_deg(f, theta))
        dx, dy = math.cos(ang), math.sin(ang)
        ax.annotate("", xy=(cx + arrow_len * dx, cy + arrow_len * dy),
                    xytext=(cx, cy),
                    arrowprops=dict(arrowstyle="-|>", color=ORANGE, lw=2.4),
                    zorder=5)
        ax.text(cx + (arrow_len + 0.35) * dx, cy + (arrow_len + 0.35) * dy,
                f.get("label", ""), color=BLACK, ha="center", va="center",
                fontsize=11, fontweight="bold", zorder=6)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=120, facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


# ---------------------------------------------------------------------------
# Dynamics mechanisms: gear trains and linkages (rotating rigid-body motion).
# A separate deterministic code path from the single-body FBD renderer above.
# ---------------------------------------------------------------------------
_DYNAMICS_TYPES = ("gear", "linkage", "mechanism")


def _fig_to_b64(fig) -> str:
    """Serialize a matplotlib figure to a base64 PNG string and close it."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=120, facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def _arc_points(cx, cy, r, start_deg, end_deg, n=24):
    """Points along a circular arc (for angular-velocity arcs)."""
    a0, a1 = math.radians(start_deg), math.radians(end_deg)
    return [(cx + r * math.cos(a0 + (a1 - a0) * i / n),
             cy + r * math.sin(a0 + (a1 - a0) * i / n)) for i in range(n + 1)]


def render_dynamics_diagram(fbd_data: dict) -> str:
    """Render a dynamics mechanism (gear train or linkage) to a base64 PNG.

    Dispatches on ``fbd_data['type']``:
      - "gear"                   -> gear-system renderer
      - "linkage" / "mechanism"  -> linkage renderer
    Returns '' for anything else or on any failure, so callers can fall back to
    the single-body FBD / schematic renderers for statics problems.
    """
    if not fbd_data:
        return ""
    dtype = str(fbd_data.get("type") or "").lower()
    try:
        if dtype == "gear":
            return _render_gear_system(fbd_data)
        if dtype in ("linkage", "mechanism"):
            return _render_linkage_system(fbd_data)
    except Exception:
        return ""
    return ""


def _render_gear_system(data: dict) -> str:
    """Gears as circle outlines, arms/sticks as lines, pivots as dots,
    velocity / angular-velocity vectors as arrows, labels for all quantities."""
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.set_aspect("equal")
    ax.axis("off")
    xs, ys = [], []

    def _track(*pts):
        for x, y in pts:
            xs.append(x); ys.append(y)

    # arms / sticks connecting gear centers
    for a in (data.get("arms") or data.get("sticks") or []):
        try:
            x1, y1, x2, y2 = float(a["x1"]), float(a["y1"]), float(a["x2"]), float(a["y2"])
            ax.plot([x1, x2], [y1, y2], color=NAVY, lw=2.5, solid_capstyle="round", zorder=2)
            _track((x1, y1), (x2, y2))
            if a.get("label"):
                ax.text((x1 + x2) / 2 + 0.08, (y1 + y2) / 2 + 0.08, a["label"],
                        color=NAVY, fontsize=9, zorder=6)
        except Exception:
            continue

    # gears as circle outlines with omega label placed outside the circle
    for g in (data.get("gears") or []):
        try:
            cx, cy, r = float(g["cx"]), float(g["cy"]), float(g.get("r", 0.5))
            ax.add_patch(plt.Circle((cx, cy), r, fill=False, edgecolor=BLACK, lw=2, zorder=3))
            _track((cx - r, cy - r), (cx + r, cy + r))
            if g.get("label"):
                ax.text(cx, cy, g["label"], color=BLACK, fontsize=10,
                        ha="center", va="center", zorder=4)
            omega = g.get("omega")
            if omega:
                ax.text(cx + r + 0.15, cy + r + 0.15, str(omega), color=ORANGE,
                        fontsize=9, ha="left", va="bottom", zorder=6)
        except Exception:
            continue

    # pivot points as filled dots, label offset diagonally
    for pv in (data.get("pivots") or []):
        try:
            x, y = float(pv["x"]), float(pv["y"])
            ax.plot(x, y, "o", color=BLACK, markersize=7, zorder=5)
            _track((x, y))
            if pv.get("label"):
                ax.text(x + 0.08, y + 0.08, pv["label"], color=BLACK, fontsize=9, zorder=6)
        except Exception:
            continue

    # velocity / angular-velocity vectors as arrows
    for v in (data.get("velocities") or data.get("vectors") or []):
        try:
            x1, y1 = float(v["x"]), float(v["y"])
            dx, dy = float(v.get("dx", 0)), float(v.get("dy", 0))
            ax.annotate("", xy=(x1 + dx, y1 + dy), xytext=(x1, y1),
                        arrowprops=dict(arrowstyle="-|>", color=ORANGE, lw=2), zorder=5)
            _track((x1, y1), (x1 + dx, y1 + dy))
            if v.get("label"):
                ax.text(x1 + dx + 0.08, y1 + dy + 0.08, v["label"],
                        color=ORANGE, fontsize=9, zorder=6)
        except Exception:
            continue

    # contact points between meshing gears
    for c in (data.get("contacts") or data.get("contact_points") or []):
        try:
            x, y = float(c["x"]), float(c["y"])
            ax.plot(x, y, "x", color=ORANGE, markersize=8, mew=2, zorder=5)
            _track((x, y))
            if c.get("label"):
                ax.text(x + 0.08, y - 0.08, c["label"], color=ORANGE,
                        fontsize=9, ha="left", va="top", zorder=6)
        except Exception:
            continue

    if xs and ys:
        pad = 0.6
        ax.set_xlim(min(xs) - pad, max(xs) + pad)
        ax.set_ylim(min(ys) - pad, max(ys) + pad)
    if data.get("title"):
        ax.set_title(data["title"], fontsize=10, color=NAVY, pad=8)

    return _fig_to_b64(fig)


def _render_linkage_system(data: dict) -> str:
    """Rods as lines, pivots as filled circles, sliding joints as rectangles,
    angular-velocity arcs, labels for all quantities."""
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.set_aspect("equal")
    ax.axis("off")
    xs, ys = [], []

    def _track(*pts):
        for x, y in pts:
            xs.append(x); ys.append(y)

    # rods / links as lines
    for rod in (data.get("rods") or data.get("links") or []):
        try:
            x1, y1, x2, y2 = float(rod["x1"]), float(rod["y1"]), float(rod["x2"]), float(rod["y2"])
            ax.plot([x1, x2], [y1, y2], color=NAVY, lw=3, solid_capstyle="round", zorder=2)
            _track((x1, y1), (x2, y2))
            if rod.get("label"):
                ax.text((x1 + x2) / 2 + 0.08, (y1 + y2) / 2 + 0.08, rod["label"],
                        color=NAVY, fontsize=9, zorder=6)
        except Exception:
            continue

    # sliding joints as rectangles
    for s in (data.get("sliders") or data.get("sliding_joints") or []):
        try:
            cx, cy = float(s["cx"]), float(s["cy"])
            w, h = float(s.get("w", 0.5)), float(s.get("h", 0.3))
            angle = float(s.get("angle", 0.0))
            ax.add_patch(plt.Rectangle((cx - w / 2, cy - h / 2), w, h, angle=angle,
                                       facecolor="none", edgecolor=BLACK, lw=2, zorder=3))
            _track((cx - w, cy - h), (cx + w, cy + h))
            if s.get("label"):
                ax.text(cx + 0.08, cy + h / 2 + 0.08, s["label"],
                        color=BLACK, fontsize=9, zorder=6)
        except Exception:
            continue

    # pivot points as filled circles, label offset diagonally
    for pv in (data.get("pivots") or []):
        try:
            x, y = float(pv["x"]), float(pv["y"])
            ax.add_patch(plt.Circle((x, y), 0.06, facecolor=BLACK, edgecolor=BLACK, zorder=5))
            _track((x, y))
            if pv.get("label"):
                ax.text(x + 0.08, y + 0.08, pv["label"], color=BLACK, fontsize=9, zorder=6)
        except Exception:
            continue

    # angular-velocity arcs with an arrowhead at the arc end
    for w in (data.get("angular_velocities") or data.get("arcs") or []):
        try:
            cx, cy = float(w["cx"]), float(w["cy"])
            r = float(w.get("r", 0.5))
            start = float(w.get("start", w.get("start_deg", 0.0)))
            end = float(w.get("end", w.get("end_deg", 120.0)))
            pts = _arc_points(cx, cy, r, start, end)
            ax.plot([p[0] for p in pts], [p[1] for p in pts], color=ORANGE, lw=2, zorder=4)
            ax.annotate("", xy=pts[-1], xytext=pts[-2],
                        arrowprops=dict(arrowstyle="-|>", color=ORANGE, lw=2), zorder=5)
            _track((cx - r, cy - r), (cx + r, cy + r))
            if w.get("label"):
                lx, ly = pts[len(pts) // 2]
                ax.text(lx + 0.1, ly + 0.1, w["label"], color=ORANGE, fontsize=9, zorder=6)
        except Exception:
            continue

    if xs and ys:
        pad = 0.6
        ax.set_xlim(min(xs) - pad, max(xs) + pad)
        ax.set_ylim(min(ys) - pad, max(ys) + pad)
    if data.get("title"):
        ax.set_title(data["title"], fontsize=10, color=NAVY, pad=8)

    return _fig_to_b64(fig)


_SCHEMATIC_COLORS = {
    "black": "#0a0a0a", "red": "#d62828", "blue": "#1d4ed8",
    "green": "#2a9d3f", "navy": NAVY, "orange": ORANGE, "gray": GRAY,
}

def _sch_color(name):
    return _SCHEMATIC_COLORS.get((name or "").lower(), BLACK)

def render_schematic(layout: dict) -> str:
    """Deterministic fallback sketch for multi-body setups the single-body
    renderer can't draw. Draws ONLY from a fixed primitive vocabulary
    (line, circle, box, point, arrow, note) — no code execution."""
    if not layout or not layout.get("drawable"):
        return ""
    prims = layout.get("primitives") or []
    if not prims:
        return ""

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.set_aspect("equal")
    ax.axis("off")

    xs, ys = [], []
    def _track(*pts):
        for x, y in pts:
            xs.append(x); ys.append(y)

    for p in prims:
        try:
            ptype = p.get("type")
            color = _sch_color(p.get("color"))
            label = p.get("label", "")
            if ptype == "line":
                x1, y1, x2, y2 = float(p["x1"]), float(p["y1"]), float(p["x2"]), float(p["y2"])
                ax.plot([x1, x2], [y1, y2], color=color, lw=4, solid_capstyle="round", zorder=3)
                _track((x1, y1), (x2, y2))
                if label:
                    ax.text((x1 + x2) / 2, (y1 + y2) / 2 + 0.12, label, color=color,
                            fontsize=9, ha="center", va="bottom", zorder=6)
            elif ptype == "circle":
                cx, cy, r = float(p["cx"]), float(p["cy"]), float(p.get("r", 0.3))
                ax.add_patch(plt.Circle((cx, cy), r, fill=False, edgecolor=color, lw=3, zorder=3))
                _track((cx - r, cy - r), (cx + r, cy + r))
                if label:
                    ax.text(cx, cy + r + 0.12, label, color=color, fontsize=9,
                            ha="center", va="bottom", zorder=6)
            elif ptype == "box":
                cx, cy = float(p["cx"]), float(p["cy"])
                w, h = float(p.get("w", 0.4)), float(p.get("h", 0.4))
                ax.add_patch(plt.Rectangle((cx - w / 2, cy - h / 2), w, h,
                                           facecolor=color, edgecolor=BLACK, lw=1.5, zorder=3))
                _track((cx - w / 2, cy - h / 2), (cx + w / 2, cy + h / 2))
                if label:
                    ax.text(cx, cy, label, color="white", fontsize=9, ha="center",
                            va="center", fontweight="bold", zorder=4)
            elif ptype == "point":
                x, y = float(p["x"]), float(p["y"])
                ax.plot(x, y, "o", color=color, markersize=9, zorder=4)
                _track((x, y))
                if label:
                    ax.text(x, y - 0.18, label, color=color, fontsize=8.5,
                            ha="center", va="top", zorder=6)
            elif ptype == "arrow":
                x1, y1, x2, y2 = float(p["x1"]), float(p["y1"]), float(p["x2"]), float(p["y2"])
                ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                            arrowprops=dict(arrowstyle="-|>", color=color, lw=2.2), zorder=5)
                _track((x1, y1), (x2, y2))
                if label:
                    ax.text(x2, y2 + 0.12, label, color=color, fontsize=8.5,
                            ha="center", va="bottom", zorder=6)
            elif ptype == "note":
                x, y = float(p.get("x", 0.0)), float(p.get("y", 0.0))
                ax.text(x, y, p.get("text", ""), color=GRAY, fontsize=8,
                        ha="left", va="top", style="italic", zorder=6)
                _track((x, y))
        except Exception:
            continue

    if xs and ys:
        pad = 0.6
        ax.set_xlim(min(xs) - pad, max(xs) + pad)
        ax.set_ylim(min(ys) - pad, max(ys) + pad)
    else:
        ax.set_xlim(-1, 5); ax.set_ylim(-1, 5)

    ax.set_title(layout.get("title", "Approximate schematic"), fontsize=10, color=NAVY, pad=8)
    ax.text(0.5, 0.02, "approximate sketch — not to scale, may be inexact",
            transform=ax.transAxes, ha="center", va="bottom",
            fontsize=8, color=GRAY, style="italic")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=120, facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")



def stack_images_vertical(b64_images: list) -> str:
    """Composite multiple base64 PNGs into ONE tall PNG (stacked top-to-bottom).
    Lets us return several diagrams through the single diagram_image field.
    Skips any empty/malformed entry. Returns '' if nothing usable."""
    imgs = []
    for b in b64_images:
        if not b:
            continue
        try:
            data = base64.b64decode(b)
            imgs.append(plt.imread(io.BytesIO(data), format="png"))
        except Exception:
            continue
    if not imgs:
        return ""
    if len(imgs) == 1:
        # nothing to stack; re-encode the single one unchanged
        return b64_images[[i for i, b in enumerate(b64_images) if b][0]]

    width = max(im.shape[1] for im in imgs)
    total_h = sum(im.shape[0] for im in imgs)
    fig_w = width / 100.0
    fig_h = total_h / 100.0
    fig, axes = plt.subplots(len(imgs), 1, figsize=(fig_w, fig_h))
    if len(imgs) == 1:
        axes = [axes]
    for ax, im in zip(axes, imgs):
        ax.imshow(im)
        ax.axis("off")
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0, hspace=0.05)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=100, facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


if __name__ == "__main__":
    # standalone sanity check: python agents/fbd_renderer.py
    spec = {
        "renderable": True, "archetype": "block_on_incline",
        "incline_angle_deg": 25, "block_label": "A",
        "forces": [
            {"label": "W = 117.7 N", "kind": "weight"},
            {"label": "N = 106.7 N", "kind": "normal"},
            {"label": "f = 30 N", "kind": "friction", "along": "up_incline"},
        ],
    }
    open("test_incline.png", "wb").write(base64.b64decode(render_fbd(spec)))
    print("wrote test_incline.png")