"""
FBD Renderer - Converts visualizer agent JSON output into a matplotlib diagram.
Returns a base64-encoded PNG string that can be sent to the frontend.
"""

import matplotlib
matplotlib.use('Agg')  # non-interactive backend, required for server use
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyArrowPatch
import numpy as np
import base64
import io
import re


def parse_magnitude(magnitude_str) -> float:
    """Extract numeric value from a magnitude string like '50 N' or '100N'."""
    if not magnitude_str:
        return 0.0
    match = re.search(r'[\d.]+', str(magnitude_str))
    return float(match.group()) if match else 0.0


def parse_location_x(location_str: str, beam_length: float) -> float:
    """
    Extract x position from location description.
    Examples: 'left end', 'right end', 'midspan', '2.5m from A'
    """
    if not location_str:
        return beam_length / 2

    loc = location_str.lower()

    if 'left' in loc or 'point a' in loc or 'pin a' in loc:
        return 0.0
    if 'right' in loc or 'point b' in loc or 'roller b' in loc:
        return beam_length
    if 'midspan' in loc or 'mid' in loc:
        return beam_length / 2

    # Try to extract a numeric distance like "2.5m from A"
    match = re.search(r'([\d.]+)\s*m', loc)
    if match:
        return float(match.group(1))

    return beam_length / 2


def render_fbd(visualizer_output: dict) -> str:
    """
    Render a free body diagram from visualizer agent output.

    Args:
        visualizer_output: The JSON dict from the visualizer agent.

    Returns:
        Base64-encoded PNG string.
    """
    elements = visualizer_output.get("elements", [])

    # ----------------------------------------------------------------
    # Determine beam length from elements
    # ----------------------------------------------------------------
    beam_length = 5.0  # default
    for el in elements:
        if el.get("type") == "body":
            mag = parse_magnitude(el.get("magnitude", ""))
            if mag > 0:
                beam_length = mag

    # ----------------------------------------------------------------
    # Figure setup
    # ----------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.set_xlim(-1.5, beam_length + 1.5)
    ax.set_ylim(-2.5, 3.0)
    ax.set_aspect('equal')
    ax.axis('off')

    # UTEP color scheme
    NAVY    = '#041E42'
    ORANGE  = '#FF8200'
    BLACK   = '#0a0a0a'
    GRAY    = '#888888'

    # ----------------------------------------------------------------
    # Draw beam
    # ----------------------------------------------------------------
    beam_y = 0.0
    ax.plot([0, beam_length], [beam_y, beam_y],
            color=NAVY, linewidth=6, solid_capstyle='round', zorder=3)

    # ----------------------------------------------------------------
    # Draw elements
    # ----------------------------------------------------------------
    for el in elements:
        el_type     = el.get("type", "")
        label       = el.get("label", "")
        magnitude   = el.get("magnitude", "")
        direction   = el.get("direction", "").lower()
        location    = el.get("location", "")

        x = parse_location_x(location, beam_length)

        # ---- SUPPORT ----
        if el_type == "support":
            if "pin" in label.lower() or "pin" in el_type.lower():
                _draw_pin(ax, x, beam_y, NAVY)
            elif "roller" in label.lower():
                _draw_roller(ax, x, beam_y, NAVY)
            elif "fixed" in label.lower():
                _draw_fixed(ax, x, beam_y, NAVY)

        # ---- FORCE ----
        elif el_type == "force":
            mag_val = parse_magnitude(magnitude)
            mag_label = f"{label} = {magnitude}" if magnitude else label

            if "down" in direction or "-y" in direction:
                _draw_force_arrow(ax, x, beam_y + 1.2, x, beam_y + 0.1,
                                  ORANGE, mag_label, label_above=True)
            elif "up" in direction or "+y" in direction:
                _draw_force_arrow(ax, x, beam_y - 1.4, x, beam_y - 0.6,
                                ORANGE, mag_label, label_above=False)
            elif "right" in direction or "+x" in direction:
                if mag_val == 0:
                    ax.text(x - 0.3, beam_y + 0.25, f"{label} = 0",
                            color=GRAY, fontsize=8, ha='center')
                else:
                    _draw_force_arrow(ax, x - 1.0, beam_y, x - 0.1, beam_y,
                                      ORANGE, mag_label, label_above=True)
            elif "left" in direction or "-x" in direction:
                _draw_force_arrow(ax, x + 1.0, beam_y, x + 0.1, beam_y,
                                  ORANGE, mag_label, label_above=True)

        # ---- DISTRIBUTED LOAD ----
        elif el_type == "distributed":
            _draw_distributed_load(ax, 0, beam_length, beam_y, magnitude, ORANGE)

        # ---- MOMENT ----
        elif el_type == "moment":
            _draw_moment(ax, x, beam_y, direction, label, magnitude, ORANGE)

        # ---- AXIS ----
        elif el_type == "axis":
            _draw_axes(ax, -1.0, -1.8, GRAY)

    # ----------------------------------------------------------------
    # Title
    # ----------------------------------------------------------------
    desc = visualizer_output.get("description", "Free Body Diagram")
    ax.set_title(desc[:80] + ("..." if len(desc) > 80 else ""),
                 fontsize=9, color=NAVY, pad=10, wrap=True)

    # ----------------------------------------------------------------
    # Encode to base64
    # ----------------------------------------------------------------
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight',
                dpi=120, facecolor='white')
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode('utf-8')


# ----------------------------------------------------------------
# Drawing helpers
# ----------------------------------------------------------------

def _draw_pin(ax, x, y, color):
    """Draw a pin support (triangle + circle)."""
    triangle = plt.Polygon(
        [[x, y], [x - 0.3, y - 0.5], [x + 0.3, y - 0.5]],
        closed=True, fill=False, edgecolor=color, linewidth=1.5, zorder=4
    )
    ax.add_patch(triangle)
    circle = plt.Circle((x, y), 0.07, color=color, zorder=5)
    ax.add_patch(circle)
    ax.plot([x - 0.4, x + 0.4], [y - 0.55, y - 0.55],
            color=color, linewidth=2, zorder=4)
    ax.text(x, y - 0.75, 'A', ha='center', va='top',
            fontsize=9, color=color, fontweight='bold')


def _draw_roller(ax, x, y, color):
    """Draw a roller support (triangle + circle at bottom)."""
    triangle = plt.Polygon(
        [[x, y], [x - 0.3, y - 0.5], [x + 0.3, y - 0.5]],
        closed=True, fill=False, edgecolor=color, linewidth=1.5, zorder=4
    )
    ax.add_patch(triangle)
    circle = plt.Circle((x, y - 0.62), 0.1, fill=False,
                         edgecolor=color, linewidth=1.5, zorder=5)
    ax.add_patch(circle)
    ax.text(x, y - 0.85, 'B', ha='center', va='top',
            fontsize=9, color=color, fontweight='bold')


def _draw_fixed(ax, x, y, color):
    """Draw a fixed/wall support."""
    ax.plot([x, x], [y - 0.6, y + 0.6], color=color, linewidth=3, zorder=4)
    for i in np.arange(y - 0.5, y + 0.6, 0.2):
        ax.plot([x, x - 0.25], [i, i - 0.15], color=color,
                linewidth=1, zorder=4)


def _draw_force_arrow(ax, x1, y1, x2, y2, color, label, label_above=True):
    """Draw a force arrow with label."""
    ax.annotate("",
        xy=(x2, y2), xytext=(x1, y1),
        arrowprops=dict(arrowstyle="-|>", color=color,
                        lw=2, mutation_scale=16),
        zorder=6
    )
    mid_x = (x1 + x2) / 2
    mid_y = (y1 + y2) / 2
    offset = 0.2 if label_above else -0.2
    ax.text(mid_x + 0.1, mid_y + offset, label,
            color=color, fontsize=8, fontweight='bold',
            ha='left', va='center', zorder=7)


def _draw_distributed_load(ax, x_start, x_end, y, magnitude, color):
    """Draw a distributed load as evenly spaced arrows."""
    n_arrows = 6
    xs = np.linspace(x_start, x_end, n_arrows)
    for xv in xs:
        ax.annotate("",
            xy=(xv, y + 0.05), xytext=(xv, y + 0.8),
            arrowprops=dict(arrowstyle="-|>", color=color,
                            lw=1.5, mutation_scale=12),
            zorder=6
        )
    ax.plot([x_start, x_end], [y + 0.8, y + 0.8],
            color=color, linewidth=2, zorder=6)
    ax.text((x_start + x_end) / 2, y + 1.0, magnitude,
            color=color, fontsize=8, fontweight='bold', ha='center')


def _draw_moment(ax, x, y, direction, label, magnitude, color):
    """Draw a curved moment arrow."""
    theta = np.linspace(0.2, 2 * np.pi - 0.2, 100)
    r = 0.35
    xs = x + r * np.cos(theta)
    ys = y + r * np.sin(theta)
    ax.plot(xs, ys, color=color, linewidth=2, zorder=6)
    ax.text(x, y + r + 0.2, f"{label} = {magnitude}",
            color=color, fontsize=8, ha='center', fontweight='bold')


def _draw_axes(ax, x, y, color):
    """Draw x-y coordinate axes."""
    ax.annotate("", xy=(x + 0.5, y), xytext=(x, y),
        arrowprops=dict(arrowstyle="-|>", color=color, lw=1.5, mutation_scale=12))
    ax.annotate("", xy=(x, y + 0.5), xytext=(x, y),
        arrowprops=dict(arrowstyle="-|>", color=color, lw=1.5, mutation_scale=12))
    ax.text(x + 0.55, y, 'x', color=color, fontsize=8, va='center')
    ax.text(x, y + 0.6, 'y', color=color, fontsize=8, ha='center')


# ----------------------------------------------------------------
# Quick test
# ----------------------------------------------------------------
if __name__ == "__main__":
    sample = {
        "description": "5m beam pinned at A, roller at B, 100N load at midspan",
        "elements": [
            {"type": "body", "label": "beam", "magnitude": "5 m length", "direction": "horizontal", "location": "extends from A to B", "is_known": True},
            {"type": "axis", "label": "xy-axes", "magnitude": None, "direction": "+x right, +y up", "location": "origin", "is_known": True},
            {"type": "support", "label": "pin A", "magnitude": None, "direction": "constrains x and y", "location": "left end of beam", "is_known": True},
            {"type": "support", "label": "roller B", "magnitude": None, "direction": "constrains y only", "location": "right end of beam, 5m from A", "is_known": True},
            {"type": "force", "label": "P", "magnitude": "100 N", "direction": "down (-y)", "location": "midspan, 2.5m from A", "is_known": True},
            {"type": "force", "label": "Ax", "magnitude": "0 N", "direction": "right (+x)", "location": "pin A at left end", "is_known": False},
            {"type": "force", "label": "Ay", "magnitude": "50 N", "direction": "up (+y)", "location": "pin A at left end", "is_known": False},
            {"type": "force", "label": "By", "magnitude": "50 N", "direction": "up (+y)", "location": "roller B at right end, 5m from A", "is_known": False},
        ]
    }

    b64 = render_fbd(sample)
    # Save to file so you can open and inspect it
    with open("test_fbd.png", "wb") as f:
        f.write(base64.b64decode(b64))
    print("Saved to test_fbd.png — open it to check the diagram!")