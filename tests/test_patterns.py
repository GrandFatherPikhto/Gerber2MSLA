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

import re

import numpy as np
import pytest

from conftest import pixels, run_mask, runs_of_figure

from gerber2msla.cli import main
from gerber2msla.masks import Refusal, Screen
from gerber2msla.patterns import (DEFAULT_GRID_GAP_MM, DEFAULT_GRID_LINE_MM,
                                  DEFAULT_SQUARE_LINE_MM, PLATE_GRID_HEIGHT_MM,
                                  PLATE_GRID_WIDTH_MM, PLATE_HEIGHT_MM, PLATE_MARGIN_MM,
                                  PLATE_WIDTH_MM, Width, build_patches, build_plate)


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


# ─────────────────────────── square (plan П5а) ─────────────────────────────

def test_the_square_is_a_closed_contour_of_whole_pixels(tmp_path, screen_args,
                                                        rect_pixel_args):
    """2 mm of a 34.4 x 30 um pixel: 58 px across, 67 px down, strokes 6 x 7 px.

    The picture, not the report: the four strokes are read off the PNG placed at 0,0.
    """
    target = run_mask(tmp_path, "square", *screen_args, *rect_pixel_args,
                      "--side-mm", "2", "--line-mm", "0.2", "--at", "0,0",
                      "--no-marker")
    screen = pixels(target)
    rows = np.nonzero(screen.any(axis=1))[0]
    cols = np.nonzero(screen.any(axis=0))[0]
    drawn = (int(rows[-1] - rows[0] + 1), int(cols[-1] - cols[0] + 1))
    assert drawn == (67, 58), "the side is whole pixels of each axis"
    array = screen[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]
    assert array[:7, :].all(), "the near edge is a full-width stroke, 7 px tall"
    assert array[-7:, :].all(), "the far edge is closed"
    assert array[:, :6].all(), "the left edge is a 6 px stroke"
    assert array[:, -6:].all(), "the right edge is closed"
    assert not array[7:-7, 6:-6].any(), "inside the contour is black"


def test_a_square_side_below_two_line_widths_is_refused(tmp_path, screen_args,
                                                        rect_pixel_args, capsys):
    """A 0.4 mm side with a 0.2 mm line is a solid block, not a contour."""
    target = tmp_path / "square.png"
    assert main(["masks", "square", *screen_args, *rect_pixel_args, "--side-mm", "0.4",
                 "--line-mm", "0.2", "-o", str(target)]) == 2
    err = capsys.readouterr().err
    assert "solid, not a contour" in err
    assert "0.400 x 0.400 mm" in err and "0.200 mm" in err
    assert "12 x 13 px" in err and "6 x 7 px" in err
    assert not target.exists()


def test_a_square_that_does_not_fit_is_refused_in_millimetres_and_pixels(
        tmp_path, screen_args, rect_pixel_args, capsys):
    target = tmp_path / "square.png"
    assert main(["masks", "square", *screen_args, *rect_pixel_args, "--side-mm", "10",
                 "--line-mm", "0.2", "-o", str(target)]) == 2
    err = capsys.readouterr().err
    assert "does not fit" in err
    assert "mm" in err and "px" in err
    assert not target.exists()


def test_a_square_request_in_whole_pixels_is_the_same_count_on_both_axes(
        tmp_path, screen_args, rect_pixel_args, capsys):
    """40 px is 40 on each axis — two DIFFERENT physical sides on a 34.4 x 30 pixel."""
    target = run_mask(tmp_path, "square", *screen_args, *rect_pixel_args,
                      "--side-px", "40", "--line-px", "2", "--at", "0,0",
                      "--no-marker")
    captured = capsys.readouterr()
    assert "drawn: 40 x 40 px" in captured.out
    assert "1.376 x 1.200 mm" in captured.out, "one count, two physical sides"
    assert "strokes 2 x 2 px" in captured.out
    assert "is drawn as" not in captured.err, "a pixel request cannot deviate from itself"
    screen = pixels(target)
    rows = np.nonzero(screen.any(axis=1))[0]
    cols = np.nonzero(screen.any(axis=0))[0]
    drawn = (int(rows[-1] - rows[0] + 1), int(cols[-1] - cols[0] + 1))
    assert drawn == (40, 40), "the same pixel count on each axis"


def test_the_square_report_carries_the_pixel_formulas(tmp_path, screen_args,
                                                      rect_pixel_args, capsys):
    """The formula is printed WITH this order's numbers, ready to divide the measurement."""
    run_mask(tmp_path, "square", *screen_args, *rect_pixel_args,
             "--side-mm", "2", "--line-mm", "0.2")
    out = capsys.readouterr().out
    assert "pixel_um_x = measured_x_mm / 58 * 1000" in out
    assert "pixel_um_y = measured_y_mm / 67 * 1000" in out
    assert "measure both sides with calipers" in out
    assert "d1 = d2 expected" in out
    assert "theta" not in out, "the LCD grid has no skew: no skew formula"


def test_the_square_report_says_outer_edge_to_outer_edge(tmp_path, screen_args,
                                                         rect_pixel_args, capsys):
    """`n` is the OUTER size in pixels: the calipers must read outer edge to outer edge."""
    run_mask(tmp_path, "square", *screen_args, *rect_pixel_args, "--side-mm", "2")
    out = capsys.readouterr().out
    assert "OUTER edge to outer edge" in out
    assert "outer edges are what the formula divides" in out


# ──────────────────────────── plate (plan П5б) ─────────────────────────────

PLATE_SCREEN = ("--screen-px", "1200x900", "--pixel-um", "34.4x34.4")
PLATE_ARGS = (*PLATE_SCREEN, "--plate-mm", "20x16", "--margin-mm", "1",
              "--widths-mm", "0.2", "--lines", "1", "--grid-mm", "5x5",
              "--line-mm", "0.1", "--gap-mm", "0.1")


def _placement(report: str, name: str) -> tuple[int, int, int, int]:
    """(x_px, y_px, width_px, height_px) of one figure, read off its report line."""
    pattern = (rf"^figure {name}: [\d.]+ x [\d.]+ mm \((\d+) x (\d+) px\), "
               rf".* \((-?\d+), (-?\d+) px\)$")
    found = re.search(pattern, report, flags=re.MULTILINE)
    assert found, f"no placement line for figure {name}"
    width_px, height_px, x_px, y_px = (int(part) for part in found.groups())
    return x_px, y_px, width_px, height_px


def test_every_plate_figure_sits_where_the_report_says(tmp_path, capsys):
    """A crop of the plate at the reported corner IS the figure a single command draws."""
    plate = pixels(run_mask(tmp_path, "plate", *PLATE_ARGS, name="plate.png"))
    report = capsys.readouterr().out
    assert report.count("figure marker:") == 1, "one F on the plate, not one per figure"

    for name, single_args in (
        ("bars", ("bars", *PLATE_SCREEN, "--widths-mm", "0.2", "--lines", "1",
                  "--no-marker", "--at", "0,0")),
        ("grid", ("grid", *PLATE_SCREEN, "--width-mm", "5", "--height-mm", "5",
                  "--line-mm", "0.1", "--gap-mm", "0.1", "--direction", "both",
                  "--no-marker", "--at", "0,0")),
    ):
        x_px, y_px, width_px, height_px = _placement(report, name)
        alone = pixels(run_mask(tmp_path, *single_args, name=f"{name}.png"))
        assert np.array_equal(plate[y_px:y_px + height_px, x_px:x_px + width_px],
                              alone[:height_px, :width_px]), \
            f"the {name} on the plate is the figure the single command draws"

    frame_x, frame_y, frame_w, frame_h = _placement(report, "frame")
    frame = plate[frame_y:frame_y + frame_h, frame_x:frame_x + frame_w]
    assert frame[:6, :].all() and frame[-6:, :].all(), "the frame is closed top and bottom"
    assert frame[:, :6].all() and frame[:, -6:].all(), "the frame is closed left and right"


def test_the_plate_names_the_grid_default_it_uses(sixks_screen):
    """The single grid (50 x 40 mm) does not fit half a plate: the plate default is named."""
    placements, report = build_plate(
        sixks_screen, plate_w_mm=PLATE_WIDTH_MM, plate_h_mm=PLATE_HEIGHT_MM,
        margin_mm=PLATE_MARGIN_MM, square_line=Width(mm=DEFAULT_SQUARE_LINE_MM),
        widths=(Width(mm=0.2),), lines=5, grid_line=Width(mm=DEFAULT_GRID_LINE_MM),
        grid_gap=Width(mm=DEFAULT_GRID_GAP_MM), grid_width_mm=PLATE_GRID_WIDTH_MM,
        grid_height_mm=PLATE_GRID_HEIGHT_MM, direction="both", at_mm=None)
    text = "\n".join(report)
    assert [placement.name for placement in placements] == ["frame", "marker", "bars", "grid"]
    assert "grid on a plate: 30.000 x 30.000 mm" in text
    assert "not the single-command 50 x 40 mm" in text
    assert "the left half is 921 px" in text
    assert "ONE letter F" in text


def test_a_plate_larger_than_the_screen_is_refused(tmp_path, capsys):
    target = tmp_path / "plate.png"
    assert main(["masks", "plate", *PLATE_SCREEN, "--plate-mm", "100x100",
                 "-o", str(target)]) == 2
    err = capsys.readouterr().err
    assert "does not fit" in err
    assert "mm" in err and "px" in err
    assert not target.exists()


def test_a_figure_that_does_not_fit_the_frame_is_refused(tmp_path, capsys):
    """The plate does not shrink the grid to make it fit: it refuses and names it."""
    target = tmp_path / "plate.png"
    assert main(["masks", "plate", *PLATE_SCREEN, "--plate-mm", "20x16", "--margin-mm", "1",
                 "--widths-mm", "0.2", "--lines", "1", "--grid-mm", "15x5",
                 "--line-mm", "0.1", "--gap-mm", "0.1", "-o", str(target)]) == 2
    err = capsys.readouterr().err
    assert "figure grid" in err
    assert "does not fit the plate frame" in err
    assert "mm" in err and "px" in err
    assert not target.exists()


def test_the_mirror_reflects_the_whole_plate_once(tmp_path, capsys):
    direct = pixels(run_mask(tmp_path, "plate", *PLATE_ARGS, name="direct.png"))
    capsys.readouterr()
    mirrored = pixels(run_mask(tmp_path, "plate", *PLATE_ARGS, "--mirror",
                               name="mirrored.png"))
    report = capsys.readouterr().out
    assert np.array_equal(mirrored, np.fliplr(direct))
    assert not np.array_equal(mirrored, direct)
    assert report.count("figure marker:") == 1, "the F is not drawn per figure"
    assert "mirror: on" in report


def test_the_plate_mirror_report_says_where_each_figure_lands(tmp_path, capsys):
    """Each figure's number is its LEFT edge after the flip, and the PNG agrees."""
    direct = pixels(run_mask(tmp_path, "plate", *PLATE_ARGS, name="direct.png"))
    report = capsys.readouterr().out
    mirrored = pixels(run_mask(tmp_path, "plate", *PLATE_ARGS, "--mirror",
                               name="mirrored.png"))
    out = capsys.readouterr().out
    assert np.array_equal(mirrored, np.fliplr(direct))
    screen_width_px = int(PLATE_SCREEN[1].split("x")[0])
    pixel_mm = 0.0344
    for name in ("frame", "marker", "bars", "grid"):
        x_px, y_px, width_px, height_px = _placement(report, name)
        flipped = screen_width_px - x_px - width_px
        assert (f"mirror: figure {name} sits at {flipped} px across = "
                f"{flipped * pixel_mm:.3f} mm") in out
        assert np.array_equal(
            mirrored[y_px:y_px + height_px, flipped:flipped + width_px],
            np.fliplr(direct[y_px:y_px + height_px, x_px:x_px + width_px])), \
            f"the {name} number is where the figure really landed"


# ─────────────────────────── patches (plan K1) ─────────────────────────────

PATCH_SCREEN = Screen(width_px=200, height_px=200, pixel_x_um=100.0, pixel_y_um=100.0)
"""100 um per pixel: a patch of 1 mm is 10 px, a stripe of 0.2 mm is 2 px, so the cells
read the drawing as plain run lengths. The patches figure is not clipped by the screen —
`masks.compose` does that — so the screen here is only the pixel scale."""


def test_a_patch_holds_whole_stripes_flush_with_the_near_edge():
    """Whole stripes only, the first flush with the edge: 10 px holds 2 + 1 gap thrice."""
    figure = build_patches(PATCH_SCREEN, 1.0, (Width(mm=0.2),), None, 0.5)
    column = runs_of_figure(figure.pixels[:, 0])
    assert column == [(255, 2), (0, 2), (255, 2), (0, 2), (255, 2)], \
        "stripes of 2 px, gap = width, three of them, no sliver at the far edge"
    assert "horizontal 3 stripes of 2 px, gap 2 px, leftover 0 px" in \
        "\n".join(figure.report)


def test_a_patch_is_whole_pixels_of_each_axis():
    """A 100 x 50 um pixel: the same 1 mm square is 10 px across and 20 px down."""
    screen = Screen(width_px=200, height_px=200, pixel_x_um=100.0, pixel_y_um=50.0)
    figure = build_patches(screen, 1.0, (Width(mm=0.2),), None, 0.5)
    assert (figure.width_px, figure.height_px) == (25, 20), \
        "10 px squares across, 20 px down; the 0.5 mm patch gap is 5 px across, 10 down"
    assert figure.pixels[0:4, 0].all(), "0.2 mm along Y is 4 px"
    assert not figure.pixels[4:8, 0].any(), "the gap is the width, also 4 px"


def test_the_two_squares_of_a_row_are_filled_the_other_way():
    """Left square: lines along X. Right square: lines along Y. One row, one width."""
    figure = build_patches(PATCH_SCREEN, 1.0, (Width(mm=0.2),), None, 0.5)
    left, right = figure.pixels[:, 0:10], figure.pixels[:, 15:25]
    assert left[0, :].all(), "the first horizontal stripe spans the whole left square"
    assert not left[2, :].any(), "and the gap after it spans it too"
    assert right[:, 0].all(), "the first vertical stripe runs the whole height"
    assert not right[:, 2].any()
    assert figure.width_px == 25 and figure.height_px == 10, "two squares and one gap"


def test_the_patch_rows_go_in_the_order_of_the_widths():
    """The order in the file IS the order on the plate: the wide stripe is the top row."""
    figure = build_patches(PATCH_SCREEN, 1.0, (Width(mm=0.2), Width(mm=0.1)), None, 0.5)
    assert figure.pixels[0:2, 0].all(), "row 1: the 0.2 mm stripe is 2 px"
    assert not figure.pixels[2:4, 0].any()
    assert figure.pixels[15, 0] and not figure.pixels[16, 0], \
        "row 2 (after the 5 px patch gap): the 0.1 mm stripe is 1 px"


def test_a_patch_may_have_a_gap_of_its_own():
    """`gap_mm` is not the width: 2 px stripe with a 1 px gap fits 3 stripes in 10 px."""
    figure = build_patches(PATCH_SCREEN, 1.0, (Width(mm=0.2),), Width(mm=0.1), 0.5)
    assert runs_of_figure(figure.pixels[:, 0]) == [(255, 2), (0, 1), (255, 2), (0, 1),
                                                   (255, 2)]
    assert not figure.pixels[8:10, 0].any(), "the 2 px leftover at the far edge is a gap"
    assert "horizontal 3 stripes of 2 px, gap 1 px, leftover 2 px" in \
        "\n".join(figure.report)


def test_a_patch_too_small_for_its_stripe_is_refused():
    """A stripe thicker than the square is a refusal with both numbers, not a blank patch."""
    with pytest.raises(Refusal, match=r"holds no horizontal stripe 0.200 mm tall"):
        build_patches(PATCH_SCREEN, 0.1, (Width(mm=0.2),), None, 0.5)
