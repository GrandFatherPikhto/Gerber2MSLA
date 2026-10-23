"""`gerber2msla/patterns.py`: the geometry of `bars` and `grid`.

Cells moved from Gerber2LDI `tests/test_tools_msla.py` (364fd28) by the plan
`plan_2026_10_23_png2px6s`, П4; function names and assertions are the ORIGINAL ones.
They live here because the rules they hold are the rules of this module: which pitch goes
to which axis, how many whole lines fit a side, what a pixel request draws, and when a
millimetre request has to announce its deviation.

Cells:

    ширина по осям          толщина линии = round(w/pitch) ПО КАЖДОЙ оси, в том числе
                            на неквадратном пикселе (одна ширина — разное n)
    группа                  промежуток = ширине, число белых полос = --lines
    grid край               линия у края: влезает целиком / не влезает на один пиксель
    grid both               объединение `x` и `y`
    ширина в пикселях       --widths-px: ровно n пикселей КАЖДОЙ оси (одно число — две
                            физические ширины), отклонения нет
    отклонение > 10 %       мм-заказ вне 10 % от фактической — предупреждение; внутри и
                            у пиксельной формы — тишина
    одинаковые группы       две ширины в одно n — предупреждение; разные n — тишина
"""
from __future__ import annotations

import numpy as np
import pytest

from conftest import pixels, run_mask, runs_of_figure


def test_a_width_is_whole_pixels_of_its_own_axis(tmp_path, screen_args, rect_pixel_args):
    """A non-square pixel: 0.2 mm is 6 px across and 7 px down, not one number twice.

    The horizontal block's lines are along X, so their THICKNESS is measured in Y pixels
    (7); the vertical block's lines are along Y, so their WIDTH is in X pixels (6).
    `--at 0,0` puts the figure corner on the PNG corner, so the runs are readable.
    """
    target = run_mask(tmp_path, "bars", *screen_args, *rect_pixel_args,
                      "--widths-mm", "0.2,0.1", "--lines", "2", "--at", "0,0",
                      "--no-marker")
    array = pixels(target)

    column = runs_of_figure(array[:, 0])
    # 0.2 mm of a 30 um pixel: 6.67 -> 7 px thick, gap = width, two lines per group;
    # then the group gap (one largest width, 7 px) and the 0.1 mm group: 3.33 -> 3 px.
    assert column == [(255, 7), (0, 7), (255, 7), (0, 7),
                      (255, 3), (0, 3), (255, 3)], "Y thickness must follow the Y pixel"

    row = runs_of_figure(array[0, :])
    assert row[0][0] == 255, "the horizontal block's top line spans its own width"
    assert row[1][0] == 0, "the two blocks are separated"
    # 0.2 mm of a 34.4 um pixel: 5.81 -> 6 px wide, and 0.1 mm -> 3 px.
    assert row[2:] == [(255, 6), (0, 6), (255, 6), (0, 6), (255, 3), (0, 3), (255, 3)]


@pytest.mark.parametrize("lines", [1, 2, 4])
def test_a_group_has_as_many_lines_as_asked_and_the_gap_equals_the_width(
        tmp_path, screen_args, square_pixel_args, lines):
    """One group of `--lines` lines: every white run is the width, every gap too."""
    target = run_mask(tmp_path, "bars", *screen_args, *square_pixel_args,
                      "--widths-mm", "0.2", "--lines", str(lines), "--at", "0,0",
                      "--no-marker")
    column = runs_of_figure(pixels(target)[:, 0])
    assert [length for value, length in column if value == 255] == [6] * lines
    assert [length for value, length in column if value == 0] == [6] * (lines - 1)


GRID_EDGE_CELLS = [
    ("0.5", 2),   # 5 px tall: 2 + 1 + 2 — the second line ends exactly on the edge
    ("0.4", 1),   # 4 px tall: one pixel short of a whole second line
]


@pytest.mark.parametrize("height_mm, expected", GRID_EDGE_CELLS,
                         ids=["second line fits exactly", "one pixel short"])
def test_the_last_line_is_drawn_only_whole(tmp_path, screen_args, capsys, height_mm,
                                           expected):
    """The near edge is flush, the far edge keeps a gap, never a sliver of line.

    100 um pixels: line 0.2 mm = 2 px, gap 0.1 mm = 1 px, period 3 px. A 5 px side
    holds lines at 0 and 3; a 4 px side holds only the first one.
    """
    target = run_mask(tmp_path, "grid", *screen_args, "--pixel-um", "100x100",
                      "--width-mm", "1", "--height-mm", height_mm,
                      "--line-mm", "0.2", "--gap-mm", "0.1", "--direction", "x",
                      "--at", "0,0", "--no-marker")
    out = capsys.readouterr().out
    assert f"lines: along X {expected}" in out
    rect_y = int(round(float(height_mm) / 0.1))  # 100 um pixels
    column = pixels(target)[:rect_y, 0]
    assert int((column == 255).sum()) == 2 * expected, "whole lines of 2 px, never a sliver"


def test_both_directions_are_the_union_of_the_two(tmp_path, screen_args):
    """`both` draws the union — the crossings are lit, nothing is subtracted."""
    masks = {}
    for direction in ("x", "y", "both"):
        masks[direction] = pixels(run_mask(
            tmp_path, "grid", *screen_args, "--pixel-um", "100x100",
            "--width-mm", "1", "--height-mm", "1", "--line-mm", "0.2",
            "--gap-mm", "0.1", "--direction", direction, "--at", "0,0", "--no-marker",
            name=f"{direction}.png"))
    assert masks["x"].any() and masks["y"].any()
    assert not np.array_equal(masks["x"], masks["y"])
    assert np.array_equal(masks["both"], np.maximum(masks["x"], masks["y"]))


def test_widths_that_share_a_pixel_count_are_announced(tmp_path, screen_args,
                                                       square_pixel_args, capsys):
    """Two requested widths on one `n` give identical groups on the plate — say so."""
    run_mask(tmp_path, "bars", *screen_args, *square_pixel_args,
             "--widths-mm", "0.100,0.110", "--lines", "2")
    captured = capsys.readouterr()
    assert "give the same 3 px" in captured.err
    assert "identical" in captured.err
    assert "0.100" in captured.err and "0.110" in captured.err


def test_widths_with_different_pixel_counts_say_nothing(tmp_path, screen_args,
                                                        square_pixel_args, capsys):
    """The control: 0.2 mm and 0.1 mm are 6 and 3 px, so there is nothing to warn about."""
    run_mask(tmp_path, "bars", *screen_args, *square_pixel_args,
             "--widths-mm", "0.2,0.1", "--lines", "2")
    captured = capsys.readouterr()
    assert "identical" not in captured.err


def test_a_pixel_request_is_one_count_and_two_physical_widths(tmp_path, screen_args,
                                                              rect_pixel_args, capsys):
    """6 px of a 30 um pixel is 180 um down and of a 34.4 um one 206.4 um across.

    That is the whole point of asking in pixels: the count is exactly what the LCD lights,
    and one number still means two widths when the pixel is not square.
    """
    target = run_mask(tmp_path, "bars", *screen_args, *rect_pixel_args,
                      "--widths-px", "6", "--lines", "2", "--at", "0,0", "--no-marker")
    captured = capsys.readouterr()
    assert "6 px -> 180.0 um along Y, 206.4 um along X" in captured.out
    assert "is drawn as" not in captured.err, "a pixel request cannot deviate from itself"

    array = pixels(target)
    column = runs_of_figure(array[:, 0])
    assert [length for value, length in column if value == 255] == [6] * 2
    row = runs_of_figure(array[0, :])
    assert row[2:] == [(255, 6), (0, 6), (255, 6)], "the same 6 px wide along X"


DEVIATION_CELLS = [
    ("34x34", "0.100", None),        # 3 px = 102 um: +2 %, silence
    ("100x100", "0.220", None),      # 2 px = 200 um: -9.1 %, silence
    ("100x100", "0.180", "+11 %"),   # 2 px = 200 um: +11.1 %, warned
    ("34x34", "0.050", "-32 %"),     # 1 px = 34 um: -32 %, warned
]


@pytest.mark.parametrize("pixel_um, width_mm, expected", DEVIATION_CELLS,
                         ids=["+2 % silent", "-9.1 % silent", "+11.1 % warned",
                              "-32 % warned"])
def test_a_millimetre_request_announces_a_deviation_over_ten_percent(
        tmp_path, screen_args, capsys, pixel_um, width_mm, expected):
    """Ten percent is where the operator has to know; below it development is coarser.

    The exactly-ten-percent row is deliberately NOT here: on floats it is a coin flip
    (the limit is strict, `> 10 %`), and a cell that passes by luck is worse than none.
    """
    run_mask(tmp_path, "bars", *screen_args, "--pixel-um", pixel_um,
             "--widths-mm", width_mm, "--lines", "2")
    err = capsys.readouterr().err
    assert ("is drawn as" in err) is (expected is not None)
    if expected is not None:
        assert expected in err
        assert f"{width_mm} mm along Y is drawn as" in err
        assert f"{width_mm} mm along X is drawn as" in err
