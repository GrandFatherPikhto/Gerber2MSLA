"""Rows by geometry, and the single normalisation (plan Г0, `gerber_rows`).

COPIED from Gerber2LDI at commit 3c77f9f35c3cd9c55c3046f91fd8f7034d09898d together with
the code: `tests/test_raster.py`, `tests/test_scan_row.py` and the `union`/`subtract`
cells of `tests/test_scan_ops.py`. The cell bodies are the original's —
`diagnostics/accept_g0_ast_2026_10_24.py` compares them by AST.

Cells closed here:

    y строки = центр прохода       y0 + (i + 0.5)·step, один хозяин формулы
    прямоугольник 10×2 мм           нужное число строк, отрезок (0, 10) в каждой
    светлая полярность вырезает     дырка в регионе даёт ДВА отрезка в строке
    порядок фигур                   LPC применяется к тому, что нарисовано раньше
    вершина на строке               пройденная вершина считается ОДИН раз
    нормализация строки             таблица из 11 строк: слияние, вложенность,
                                    дубликат, нулевая длина, порядок
    обратный отрезок                ValueError, НЕ выброс
    union / subtract                оракул по точкам на сетке 1 µm, 10 пар
    отказы                          нулевой шаг строк; NaN/inf в отрезках и в высоте

NOT moved, with the reason:

  * `test_tiff_is_written_top_down` and `test_rows_to_image_refuses_a_field_thinner_than_a_pixel` —
    TIFF and the image are the laser preview's; here rows become screen pixels, and
    the Y flip they prove is checked by the "Г" cell of `test_board.py` (Г1);
  * `test_double_mirror_is_identity`, `test_mirror_keeps_the_number_of_segments`,
    `test_mirror_flips_pair_order`, `test_double_invert_is_identity`, `test_invert_table`,
    `test_invert_rejects_reversed_bounds`, `test_shrink_table`,
    `test_shrink_rejects_negative_distance`, `test_shift_moves_both_ends`,
    `test_scale_is_about_the_origin`, `test_scale_rejects_useless_factors` — the
    operations themselves (spot compensation, axis calibration, scan-line mirror and
    polarity) stayed in Gerber2LDI; the whole-picture mirror and polarity live in
    `masks.compose`;
  * six of the eight rows of `test_every_operation_rejects_a_reversed_segment` — the
    same reason; the two rows of `union`/`subtract` keep the cell, its assert and its
    `match`, so the AST comparison reports this cell as DIFFERS by design.
"""
import math

import pytest

from gerber2msla.gerber_rows import (ScanRow, iter_rows, normalize, polygon_intervals,
                                     row_count, row_segments, row_y, subtract, union)
from gerber2msla.gerber_source import Shape


def _rect_shape(x0, y0, x1, y1, dark=True) -> Shape:
    polygon = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    return Shape(polygons=(polygon,), dark=dark, bbox=(x0, y0, x1, y1))


# ─────────────────────────── the row grid ───────────────────────────────────

def test_row_height_is_the_centre_of_the_pass():
    """y = y0 + (i + 0.5)·step — the one rule the pixel sampling relies on."""
    assert row_y(0.0, 0, 0.02) == pytest.approx(0.01)
    assert row_y(0.0, 9, 0.02) == pytest.approx(0.19)
    assert row_y(-5.0, 2, 0.02) == pytest.approx(-5.0 + 2.5 * 0.02)


def test_row_count_rounds_and_refuses_zero_step():
    assert row_count(2.0, 0.02) == 100
    assert row_count(0.0, 0.02) == 0
    with pytest.raises(ValueError, match="row step"):
        row_count(2.0, 0.0)


# ─────────────────────── the row invariant: normalize ───────────────────────

NORMALIZE_CELLS = [
    ("empty", (), ()),
    ("one", ((1.0, 2.0),), ((1.0, 2.0),)),
    ("touching", ((0.0, 1.0), (1.0, 2.0)), ((0.0, 2.0),)),
    ("overlapping", ((0.0, 1.5), (1.0, 2.0)), ((0.0, 2.0),)),
    ("nested", ((0.0, 3.0), (1.0, 2.0)), ((0.0, 3.0),)),
    ("nested reverse order", ((1.0, 2.0), (0.0, 3.0)), ((0.0, 3.0),)),
    ("duplicate", ((1.0, 2.0), (1.0, 2.0)), ((1.0, 2.0),)),
    ("unsorted", ((5.0, 6.0), (1.0, 2.0)), ((1.0, 2.0), (5.0, 6.0))),
    ("zero length", ((1.0, 1.0),), ()),
    ("zero length inside", ((0.0, 1.0), (1.0, 1.0), (2.0, 3.0)),
     ((0.0, 1.0), (2.0, 3.0))),
    ("chain", ((0.0, 1.0), (2.0, 3.0), (1.0, 2.0)), ((0.0, 3.0),)),
]


@pytest.mark.parametrize("name, given, expected",
                         NORMALIZE_CELLS, ids=[c[0] for c in NORMALIZE_CELLS])
def test_normalize_table(name, given, expected):
    """normalize() sorts, merges what touches or overlaps, drops zero length."""
    assert normalize(given) == expected


def test_normalize_reversed_segment_raises():
    """A reversed segment is a broken transformation, not data to drop."""
    with pytest.raises(ValueError, match="reversed segment"):
        normalize(((2.0, 1.0),))


NON_FINITE_CELLS = [
    ((math.nan, 1.0),),
    ((0.0, math.nan),),
    ((math.inf, 1.0),),
    ((0.0, -math.inf),),
]


@pytest.mark.parametrize("segments", NON_FINITE_CELLS,
                         ids=["nan x0", "nan x1", "+inf x0", "-inf x1"])
def test_normalize_rejects_non_finite_coordinates(segments):
    """NaN compares False with everything, so it would MERGE into a neighbour and
    reach the image as a hole in the wrong place; infinity would make the segment
    unbounded."""
    with pytest.raises(ValueError, match="non-finite"):
        normalize(segments)


def test_scan_row_rejects_non_finite_segments():
    """The type refuses it too — a caller cannot smuggle NaN in through ScanRow."""
    with pytest.raises(ValueError, match="non-finite"):
        ScanRow(0.0, ((1.0, math.nan),))


def test_normalize_is_idempotent():
    """Applying it to its own output changes nothing — every op relies on this."""
    once = normalize(((5.0, 6.0), (0.0, 1.0), (0.5, 1.5), (3.0, 3.0)))
    assert normalize(once) == once


def test_scan_row_normalises_on_construction():
    """The invariant is enforced once, at the type, not by every consumer."""
    row = ScanRow(12.5, ((2.0, 3.0), (0.0, 1.0), (1.0, 2.0)))
    assert row.segments == ((0.0, 3.0),)
    assert row.y_mm == 12.5


def test_scan_row_is_immutable():
    """frozen: no consumer can rewrite a row that another layer is streaming."""
    row = ScanRow(0.0, ((0.0, 1.0),))
    with pytest.raises(Exception):
        row.segments = ()  # type: ignore[misc]


@pytest.mark.parametrize("y", [math.nan, math.inf, -math.inf])
def test_scan_row_rejects_non_finite_height(y):
    """A row height comes from the pixel grid; NaN/inf means the grid is broken."""
    with pytest.raises(ValueError, match="finite"):
        ScanRow(y, ())


def test_scan_row_empty_helper():
    """Rows outside the figure are the empty form, not a special case."""
    row = ScanRow.empty(3.5)
    assert row.is_empty
    assert row.segments == ()
    assert not ScanRow(3.5, ((0.0, 1.0),)).is_empty


# ───────────────── union and subtract: the polarity vocabulary ───────────────

STEP_MM = 0.001
XS = [round(i * STEP_MM, 6) for i in range(0, 6001)]  # 0 … 6 mm

PAIRS = [
    ("both empty", (), ()),
    ("a only", ((1.0, 2.0),), ()),
    ("b only", (), ((1.0, 2.0),)),
    ("disjoint", ((0.5, 1.0),), ((2.0, 3.0),)),
    ("touching", ((0.5, 1.0),), ((1.0, 2.0),)),
    ("overlapping", ((0.5, 2.0),), ((1.0, 3.0),)),
    ("nested", ((0.5, 3.0),), ((1.0, 2.0),)),
    ("nested reversed", ((1.0, 2.0),), ((0.5, 3.0),)),
    ("identical", ((1.0, 2.0),), ((1.0, 2.0),)),
    ("multi", ((0.5, 1.0), (2.0, 2.5)), ((0.75, 2.2),)),
]


def _ink(segments):
    """Sample the row: True where there is ink at that x."""
    return [any(x0 <= x < x1 for x0, x1 in segments) for x in XS]


OPERATIONS = [
    ("union", union, lambda a, b: a or b),
    ("subtract", subtract, lambda a, b: a and not b),
]


@pytest.mark.parametrize("op_name, op, combine", OPERATIONS,
                         ids=[o[0] for o in OPERATIONS])
@pytest.mark.parametrize("pair_name, a, b", PAIRS, ids=[p[0] for p in PAIRS])
def test_binary_operation_matches_pointwise_oracle(op_name, op, combine,
                                                   pair_name, a, b):
    """The result carries ink exactly where the boolean combination says."""
    got = _ink(op(a, b))
    expected = [combine(ia, ib) for ia, ib in zip(_ink(a), _ink(b))]
    assert got == expected


def test_union_is_commutative_and_idempotent():
    """Two properties the oracle alone would not pin: order and repetition."""
    assert union(((0.0, 1.0),), ((0.5, 2.0),)) == union(((0.5, 2.0),), ((0.0, 1.0),))
    assert union(((0.0, 1.0),), ((0.0, 1.0),)) == ((0.0, 1.0),)


@pytest.mark.parametrize("call", [
    lambda: union(((2.0, 1.0),), ()),
    lambda: subtract(((2.0, 1.0),), ()),
], ids=["union", "subtract"])
def test_every_operation_rejects_a_reversed_segment(call):
    """One row per operation we have: none may swallow the error."""
    with pytest.raises(ValueError, match="reversed segment"):
        call()


# ─────────────────────── one row of real Gerber geometry ────────────────────

def test_rectangle_row_is_one_segment():
    """A 10×2 mm rectangle: every row carries exactly (0, 10)."""
    shape = _rect_shape(0.0, 0.0, 10.0, 2.0)
    rows = list(iter_rows([shape], shape.bbox, 0.02))
    assert len(rows) == 100
    for row in rows:
        assert row.segments == ((0.0, 10.0),)


def test_clear_object_cuts_two_segments():
    """A dark region with a clear hole in it: the row through the hole has two parts."""
    dark = _rect_shape(0.0, 0.0, 10.0, 10.0)
    clear = _rect_shape(3.0, 4.0, 7.0, 6.0, dark=False)
    row = row_segments([dark, clear], 5.0)
    assert row == ((0.0, 3.0), (7.0, 10.0))
    # Outside the hole the row is whole again.
    assert row_segments([dark, clear], 1.0) == ((0.0, 10.0),)


def test_polarity_follows_file_order():
    """Draw, erase, draw again: the second dark object covers part of the hole."""
    dark = _rect_shape(0.0, 0.0, 10.0, 10.0)
    clear = _rect_shape(3.0, 4.0, 7.0, 6.0, dark=False)
    again = _rect_shape(5.0, 4.0, 7.0, 6.0, dark=True)
    assert row_segments([dark, clear, again], 5.0) == ((0.0, 3.0), (5.0, 10.0))


def test_clear_before_dark_changes_nothing_but_is_not_reordered():
    """A clear object first erases an empty row; the later dark one still draws."""
    clear = _rect_shape(3.0, 4.0, 7.0, 6.0, dark=False)
    dark = _rect_shape(0.0, 0.0, 10.0, 10.0)
    assert row_segments([clear, dark], 5.0) == ((0.0, 10.0),)


def test_iter_rows_yields_scan_rows_with_centres():
    shape = _rect_shape(0.0, 0.0, 1.0, 0.1)
    rows = list(iter_rows([shape], (0.0, 0.0, 1.0, 0.1), 0.02))
    assert all(isinstance(row, ScanRow) for row in rows)
    assert [round(row.y_mm, 6) for row in rows] == [0.01, 0.03, 0.05, 0.07, 0.09]


DIAMOND = ((0.0, 0.0), (1.0, 1.0), (2.0, 0.0), (1.0, -1.0))
TRIANGLE = ((0.0, 0.0), (2.0, 0.0), (1.0, 2.0))


def test_vertex_lying_on_the_row_is_counted_once():
    """A PASS-THROUGH vertex on the row: two crossings, so the full chord.

    The diamond's left and right vertices sit exactly on y = 0. Half-open counting
    (``y1 <= y < y2``) gives one crossing per vertex → (0, 2). A closed rule
    (`<=` on both ends) counts each vertex twice, the pairs collapse into
    zero-length segments and the row comes out EMPTY — this is the mutation cell.
    """
    assert polygon_intervals(DIAMOND, 0.0) == ((0.0, 2.0),)


def test_apex_lying_on_the_row_gives_no_interval():
    """A local EXTREMUM on the row: one crossing → odd → nothing to fill.

    The apex is a point, so the row has no width; the row just below has a small
    chord. NOTE, measured: this cell does NOT react to the ``<=`` mutation (the
    crossing count stays 1) — it pins a different property, "an odd number of
    crossings yields nothing", and is reported as such.
    """
    assert polygon_intervals(TRIANGLE, 2.0) == ()
    below = polygon_intervals(TRIANGLE, 1.99)
    assert len(below) == 1
    # Both flanks fall at 2 mm per 1 mm, so the chord half-width is (2 - y) / 2.
    assert below[0][1] - below[0][0] == pytest.approx(2.0 * (2.0 - 1.99) / 2.0, abs=1e-3)


def test_vertex_on_the_machine_row_grid_keeps_the_span():
    """The same pass-through vertex, reached through the row grid the printer uses.

    With y0 = 0 and step 0.1 the row centres land on 0.05, 0.15, …, so the diamond
    is placed with its left/right vertices exactly at 0.05: the first row passes
    through both. This ties `row_y` and the crossing rule together.
    """
    diamond = ((0.0, 0.05), (1.0, 1.05), (2.0, 0.05), (1.0, -0.95))
    shape = Shape(polygons=(diamond,), dark=True, bbox=(0.0, -0.95, 2.0, 1.05))
    rows = list(iter_rows([shape], (0.0, 0.0, 2.0, 1.05), 0.1))
    assert rows[0].y_mm == pytest.approx(0.05)
    assert rows[0].segments == ((0.0, 2.0),)
