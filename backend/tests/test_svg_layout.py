"""
Tests for svg_layout.fix_label_collisions() — the deterministic backstop that
nudges colliding <text> labels apart from each other and off lines/paths/
polygons, since Opus cannot self-check bounding boxes from a text-only SVG
spec.
"""
import logging
import re
import xml.etree.ElementTree as ET

import pytest

from agents.svg_layout import (
    fix_label_collisions,
    _text_bbox,
    _point_in_polygon,
    _closed_segments,
    _segment_intersects_rect,
    _inflate,
)


def _texts(svg: str) -> list[ET.Element]:
    root = ET.fromstring(svg)
    return [el for el in root.iter() if el.tag.rsplit("}", 1)[-1] == "text"]


def _xy(el: ET.Element) -> tuple[float, float]:
    return (float(el.get("x")), float(el.get("y")))


def test_two_overlapping_labels_get_separated():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 300">'
        '<text x="50" y="50" font-size="13">Hello World Label</text>'
        '<text x="55" y="52" font-size="13">Overlap Label</text>'
        "</svg>"
    )
    out = fix_label_collisions(svg)
    a, b = _texts(out)
    assert (a.get("x"), a.get("y")) != ("50", "50") or (b.get("x"), b.get("y")) != ("55", "52"), \
        "at least one label must have moved"

    def bbox(el):
        x, y = _xy(el)
        fs = float(el.get("font-size"))
        text = "".join(el.itertext())
        w, h = 0.55 * fs * len(text), 1.2 * fs
        return (x, y - 0.8 * fs, x + w, y + 0.4 * fs)

    ax0, ay0, ax1, ay1 = bbox(a)
    bx0, by0, bx1, by1 = bbox(b)
    no_overlap = ax1 + 4 <= bx0 or bx1 + 4 <= ax0 or ay1 + 4 <= by0 or by1 + 4 <= ay0
    assert no_overlap, f"labels still overlap: {bbox(a)} vs {bbox(b)}"


def test_label_on_a_line_gets_moved_off_it():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 300">'
        '<line x1="20" y1="150" x2="280" y2="150" stroke="black" stroke-width="2"/>'
        '<text x="100" y="150" font-size="13" text-anchor="middle">on the line</text>'
        "</svg>"
    )
    out = fix_label_collisions(svg)
    (text,) = _texts(out)
    assert _xy(text) != (100.0, 150.0)
    # New y must clear the line (y=150) by at least the 4px padding, given
    # font-size 13 => half-height ~ 0.8*13=10.4 above baseline / 0.4*13=5.2 below.
    _, y = _xy(text)
    fs = 13.0
    ymin, ymax = y - 0.8 * fs, y + 0.4 * fs
    assert ymax + 4 <= 150 or ymin - 4 >= 150


def test_clean_svg_with_no_collisions_is_returned_byte_identical():
    svg = '<svg viewBox="0 0 100 100"><rect width="10" height="10"/></svg>'
    assert fix_label_collisions(svg) == svg


def test_clean_svg_with_widely_spaced_labels_is_untouched():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 400">'
        '<text x="50" y="50" font-size="13">Far label one</text>'
        '<text x="400" y="350" font-size="13">Far label two</text>'
        "</svg>"
    )
    assert fix_label_collisions(svg) == svg


def test_malformed_svg_returns_unchanged_with_no_exception():
    bad = '<svg viewBox="0 0 100 100"><text x="1" y="2">unterminated'
    assert fix_label_collisions(bad) == bad


def test_empty_string_returns_unchanged():
    assert fix_label_collisions("") == ""


def test_label_that_cannot_be_placed_stays_put_and_does_not_error():
    # A dense grid of full-width horizontal lines blocks every candidate
    # offset (every up/down/left/right move at 14 or 28px still lands within
    # padding of some line), while the label's ORIGINAL position already
    # satisfies the margin — isolating "no collision-free candidate exists"
    # from the margin-violation fallback covered separately below.
    lines = "".join(
        f'<line x1="0" y1="{y}" x2="300" y2="{y}" stroke="black"/>'
        for y in range(110, 191, 10)
    )
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 300">'
        + lines +
        '<text x="150" y="150" font-size="10" text-anchor="middle" '
        'dominant-baseline="middle">X</text>'
        "</svg>"
    )
    out = fix_label_collisions(svg)  # must not raise
    assert out == svg  # left exactly where it was


def test_nothing_lands_outside_the_30px_margin():
    # Both labels start comfortably inside the margin and overlap each other,
    # so a move is required; _within_margin must reject any candidate that
    # would push the mover outside the 30px boundary, regardless of whether
    # the greedy pass ends up moving one label or both.
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 300">'
        '<text x="140" y="150" font-size="13">Center label one</text>'
        '<text x="143" y="152" font-size="13">Center label two</text>'
        "</svg>"
    )
    out = fix_label_collisions(svg)
    for el in _texts(out):
        x, y = _xy(el)
        fs = float(el.get("font-size"))
        text = "".join(el.itertext())
        w, h = 0.55 * fs * len(text), 1.2 * fs
        xmin, xmax = x, x + w
        ymin, ymax = y - 0.8 * fs, y + 0.4 * fs
        assert xmin >= 30 - 1e-6 and ymin >= 30 - 1e-6
        assert xmax <= 300 - 30 + 1e-6 and ymax <= 300 - 30 + 1e-6


def test_a_move_that_would_breach_margin_is_rejected():
    # This label collides with the line but the only "further from center"
    # and cardinal candidates near an edge either still collide or would
    # breach the margin; whatever the final position, it must respect it.
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 300">'
        '<line x1="0" y1="45" x2="300" y2="45" stroke="black"/>'
        '<text x="40" y="45" font-size="13">near top edge</text>'
        "</svg>"
    )
    out = fix_label_collisions(svg)
    (el,) = _texts(out)
    x, y = _xy(el)
    fs = 13.0
    ymin = y - 0.8 * fs
    assert ymin >= 30 - 1e-6


def test_defs_markers_and_background_survive_untouched():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 300">'
        '<defs><marker id="arrow" markerWidth="10" markerHeight="10">'
        '<path d="M0 0 L10 5 L0 10 z"/></marker></defs>'
        '<rect width="300" height="300" fill="white"/>'
        '<text x="50" y="50" font-size="13">A</text>'
        '<text x="52" y="51" font-size="13">B overlapping label</text>'
        "</svg>"
    )
    out = fix_label_collisions(svg)
    root = ET.fromstring(out)
    tags = [el.tag.rsplit("}", 1)[-1] for el in root.iter()]
    assert "defs" in tags and "marker" in tags and "path" in tags and "rect" in tags

    defs = next(el for el in root.iter() if el.tag.rsplit("}", 1)[-1] == "defs")
    marker = next(el for el in defs.iter() if el.tag.rsplit("}", 1)[-1] == "marker")
    assert marker.get("id") == "arrow"
    assert marker.get("markerWidth") == "10"
    path = next(el for el in marker.iter() if el.tag.rsplit("}", 1)[-1] == "path")
    assert path.get("d") == "M0 0 L10 5 L0 10 z"

    rect = next(el for el in root.iter() if el.tag.rsplit("}", 1)[-1] == "rect")
    assert rect.get("fill") == "white"
    assert rect.get("width") == "300" and rect.get("height") == "300"


def test_never_moves_geometry_only_text():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 300">'
        '<line x1="20" y1="150" x2="280" y2="150" stroke="black"/>'
        '<text x="100" y="150" font-size="13" text-anchor="middle">on the line</text>'
        "</svg>"
    )
    out = fix_label_collisions(svg)
    root = ET.fromstring(out)
    line = next(el for el in root.iter() if el.tag.rsplit("}", 1)[-1] == "line")
    assert (line.get("x1"), line.get("y1"), line.get("x2"), line.get("y2")) == (
        "20", "150", "280", "150",
    )


def test_a_move_never_exceeds_40px_total():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 400">'
        '<text x="300" y="200" font-size="13" text-anchor="middle" '
        'dominant-baseline="middle">center label</text>'
        '<text x="298" y="201" font-size="13" text-anchor="middle" '
        'dominant-baseline="middle">overlapping twin</text>'
        "</svg>"
    )
    out = fix_label_collisions(svg)
    moved = _texts(out)
    originals = [(300.0, 200.0), (298.0, 201.0)]
    for el, (ox, oy) in zip(moved, originals):
        x, y = _xy(el)
        dist = ((x - ox) ** 2 + (y - oy) ** 2) ** 0.5
        assert dist <= 40.0 + 1e-6


# ---------------------------------------------------------------------------
# Margin violations must be treated as collisions too — a label the model
# placed partly outside the viewBox was previously left untouched (no
# collision) and rendered clipped by the canvas. Live case: "x' (down-slope)"
# cut off at the right edge of a 600x400 diagram.
# ---------------------------------------------------------------------------

def test_label_outside_margin_with_no_collision_is_still_moved():
    # Right edge of the bbox (x=560, width ~107 at font-size 13) lands well
    # past the margin (600 - 30 = 570), with nothing else on the canvas to
    # collide with.
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 400">'
        '<line x1="10" y1="10" x2="20" y2="20" stroke="black"/>'
        '<text x="560" y="200" font-size="13">x\' (down-slope)</text>'
        "</svg>"
    )
    out = fix_label_collisions(svg)
    assert out != svg  # a pure margin violation must still trigger a move
    (el,) = _texts(out)
    x, y = _xy(el)
    fs = 13.0
    text = "x' (down-slope)"
    w = 0.55 * fs * len(text)
    xmin, xmax = x, x + w
    # A tenth of a pixel of slack absorbs _fmt's 1-decimal-place rounding.
    assert xmin >= 30 - 0.2 and xmax <= 600 - 30 + 0.2


def test_small_margin_overflow_is_resolved_by_the_normal_candidate_search():
    # A small enough overflow should be fixed by one of the ordinary
    # collision-avoidance candidates (the same search a real collision goes
    # through), not by the inward-clamp fallback.
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 400">'
        '<text x="562" y="200" font-size="11">tiny</text>'
        "</svg>"
    )
    out = fix_label_collisions(svg)
    (el,) = _texts(out)
    x, y = _xy(el)
    assert (x, y) != (562.0, 200.0)
    fs = 11.0
    xmax = x + 0.55 * fs * len("tiny")
    assert xmax <= 600 - 30 + 1e-6


def test_label_with_no_collision_free_spot_still_clears_the_margin():
    # Surround the clipped label with geometry so every collision-free
    # candidate is unavailable; the fallback clamp must still pull it fully
    # inside the margin even though a collision remains.
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 400">'
        '<line x1="0" y1="186" x2="600" y2="186" stroke="black"/>'
        '<line x1="0" y1="214" x2="600" y2="214" stroke="black"/>'
        '<line x1="400" y1="0" x2="400" y2="400" stroke="black"/>'
        '<text x="560" y="200" font-size="13" dominant-baseline="middle">'
        "x' (down-slope)</text>"
        "</svg>"
    )
    out = fix_label_collisions(svg)
    (el,) = _texts(out)
    x, y = _xy(el)
    fs = 13.0
    text = "x' (down-slope)"
    w = 0.55 * fs * len(text)
    xmin, xmax = x, x + w
    assert xmin >= 30 - 0.2 and xmax <= 600 - 30 + 0.2


def test_label_within_margin_and_collision_free_is_untouched():
    svg = '<svg viewBox="0 0 100 100"><text x="40" y="50" font-size="10">ok</text></svg>'
    assert fix_label_collisions(svg) == svg


# ---------------------------------------------------------------------------
# Diagonal edges (a ramp/incline polygon, or an equivalent straight-only
# path) must be tested as actual line segments, not the element's overall
# bounding box. A ramp triangle's bbox can cover most of the canvas even
# though the shape itself is a thin wedge; bbox-only collision made every
# candidate position "collide" with that oversized box, so a label already
# touching the hypotenuse could never be moved off it. Live bug: "f_k",
# "W", and "θ" labels sitting on the incline's sloped edge, left in place.
# ---------------------------------------------------------------------------

# A right triangle whose bbox (80,240)-(500,370) covers most of a 600x400
# canvas — the exact shape of the reported bug.
_RAMP_POLYGON = '<polygon points="80,370 500,370 80,240" fill="#eee" stroke="black"/>'
_RAMP_POINTS = [(80.0, 370.0), (500.0, 370.0), (80.0, 240.0)]


def test_label_near_but_not_touching_a_diagonal_edge_is_left_alone():
    # The hypotenuse passes through (300, 308.1); this label sits well above
    # it (a real ~26px gap after padding), comfortably outside the triangle,
    # but still inside the polygon's overall *bounding box* — exactly the
    # case the old bbox-only check would have falsely flagged as a collision.
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 400">'
        + _RAMP_POLYGON +
        '<text x="270" y="270" font-size="13" dominant-baseline="middle">'
        "near not touching</text>"
        "</svg>"
    )
    assert fix_label_collisions(svg) == svg


def test_label_crossing_a_diagonal_edge_gets_moved_off_it():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 400">'
        + _RAMP_POLYGON +
        '<text x="300" y="308" font-size="13">theta=30</text>'
        "</svg>"
    )
    out = fix_label_collisions(svg)
    assert out != svg
    (el,) = _texts(out)
    x, y = _xy(el)
    assert (x, y) != (300.0, 308.0)

    # The moved label must actually clear the real triangle: neither inside
    # its interior nor within padding of any of its three edges.
    new_el = ET.fromstring(f'<text x="{x}" y="{y}" font-size="13">theta=30</text>')
    new_bbox = _text_bbox(new_el)
    center = ((new_bbox[0] + new_bbox[2]) / 2, (new_bbox[1] + new_bbox[3]) / 2)
    assert not _point_in_polygon(center, _RAMP_POINTS)
    padded = _inflate(new_bbox, 4.0)
    for p1, p2 in _closed_segments(_RAMP_POINTS):
        assert not _segment_intersects_rect(p1, p2, padded)


def test_label_deep_inside_a_filled_polygon_is_detected_as_collision(caplog):
    # Not near an edge at all — squarely inside the filled interior, too far
    # in for any 40px-capped candidate to escape. Confirms the "text over a
    # filled body is a collision too" containment check fires (logged, even
    # though the label is left in place) rather than being silently missed.
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 400">'
        + _RAMP_POLYGON +
        '<text x="150" y="350" font-size="13">buried inside the ramp</text>'
        "</svg>"
    )
    with caplog.at_level(logging.DEBUG, logger="agents.svg_layout"):
        out = fix_label_collisions(svg)
    assert out == svg  # too deep inside to escape within the move budget
    assert any("buried inside the ramp" in r.message for r in caplog.records)


def test_straight_only_path_incline_behaves_like_the_equivalent_polygon():
    # Same triangle, drawn as a closed straight-line <path> instead of a
    # <polygon> — must go through the exact segment/interior treatment, not
    # the bbox fallback (which is reserved for curved commands).
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 400">'
        '<path d="M80,370 L500,370 L80,240 Z" fill="#eee" stroke="black"/>'
        '<text x="300" y="308" font-size="13">theta=30</text>'
        "</svg>"
    )
    out = fix_label_collisions(svg)
    assert out != svg


def test_curved_path_still_uses_the_bbox_fallback(caplog):
    # An arc/curve command makes the path not cheaply segmentable, so it
    # keeps the old (coarser) bounding-box treatment — this confirms that
    # path is still detected as a collision candidate at all (its bbox
    # fallback swallows too much room here for any candidate to clear it,
    # same as before this fix — curved paths were never the bug), i.e. the
    # straight-only fast path didn't silently stop detecting curved ones.
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 400">'
        '<path d="M100,300 A100,100 0 0 1 300,300" stroke="black" fill="none"/>'
        '<text x="180" y="290" font-size="13">on the arc</text>'
        "</svg>"
    )
    with caplog.at_level(logging.DEBUG, logger="agents.svg_layout"):
        out = fix_label_collisions(svg)
    assert out == svg
    assert any("on the arc" in r.message for r in caplog.records)
