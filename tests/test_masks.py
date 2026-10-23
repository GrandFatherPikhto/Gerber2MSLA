"""`gerber2msla/masks.py`: screen pixels, the marker, placement and the PNG.

Cells moved from Gerber2LDI `tests/test_tools_msla.py` (364fd28) by the plan
`plan_2026_10_23_png2px6s`, П4. Function names and assertions are the ORIGINAL ones —
only the way in changed: the package is imported and the command is
`gerber2msla masks …`. The picture is the evidence, not the report alone: every cell
reads the finished PNG back.

The small screen here (240 x 120 px, 34.4 um) and the PNG helpers live in `conftest.py`.

Cells:

    PNG                     режим L, ровно W×H пикселей, значения только 0 и 255
    ширина ниже пикселя     отказ одной строкой, файла не остаётся
    рисунок за экран        отказ с размерами в мм И пикселях, файла не остаётся
    зеркало и полярность    --mirror = np.fliplr от прямой, --invert = 255 − прямая
    кусок PNG               экран, пиксель, фактические ширины, зеркало, полярность
    метка                   F несимметрична по X и по Y, стоит в углу рисунка по
                            умолчанию, узор только сдвигается вправо, с --mirror отражена
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from conftest import pixels, run_mask

from gerber2msla import masks
from gerber2msla.cli import main


def test_the_mask_is_the_screen_in_two_values(tmp_path, screen_args, square_pixel_args):
    target = run_mask(tmp_path, "bars", *screen_args, *square_pixel_args,
                      "--widths-mm", "0.2,0.1", "--lines", "2")
    image = Image.open(target)
    assert image.mode == "L"
    assert image.size == (240, 120), "the PNG must be exactly the screen"
    assert set(np.unique(pixels(target)).tolist()) == {0, 255}


def test_a_width_below_one_pixel_is_refused(tmp_path, screen_args, square_pixel_args, capsys):
    """0.015 mm of a 34.4 um pixel rounds to zero pixels: no line exists, so refuse."""
    target = tmp_path / "bars.png"
    assert main(["masks", "bars", *screen_args, *square_pixel_args,
                 "--widths-mm", "0.015,0.2", "-o", str(target)]) == 2
    captured = capsys.readouterr()
    assert "below one 34.4 um pixel" in captured.err
    assert captured.out == ""
    assert not target.exists(), "a refusal must not leave half a mask behind"


def test_a_figure_off_the_screen_is_refused_in_millimetres_and_pixels(
        tmp_path, screen_args, square_pixel_args, capsys):
    target = tmp_path / "bars.png"
    assert main(["masks", "bars", *screen_args, *square_pixel_args, "--widths-mm", "0.2",
                 "--lines", "2", "--at", "5,0", "-o", str(target)]) == 2
    captured = capsys.readouterr()
    assert "does not fit" in captured.err
    assert "mm" in captured.err and "px" in captured.err, "both units, as the plan asks"
    assert not target.exists()


def test_mirror_and_invert_are_whole_picture_swaps(tmp_path, screen_args, square_pixel_args):
    """`--mirror` is a reflection of the finished picture, `--invert` swaps the values."""
    arguments = ("bars", *screen_args, *square_pixel_args, "--widths-mm", "0.2,0.1",
                 "--lines", "2")
    direct = pixels(run_mask(tmp_path, *arguments, name="direct.png"))
    mirrored = pixels(run_mask(tmp_path, *arguments, "--mirror", name="mirrored.png"))
    inverted = pixels(run_mask(tmp_path, *arguments, "--invert", name="inverted.png"))
    assert np.array_equal(mirrored, np.fliplr(direct))
    assert np.array_equal(inverted, 255 - direct)
    # The control: a picture that is symmetric would pass the two cells above for free.
    assert not np.array_equal(mirrored, direct), "mirroring must actually change the mask"


def test_the_png_remembers_what_it_is(tmp_path, screen_args, rect_pixel_args):
    """Screen, pixel, ACTUAL widths, mirror and polarity travel inside the file."""
    target = run_mask(tmp_path, "bars", *screen_args, *rect_pixel_args,
                      "--widths-mm", "0.2", "--lines", "2")
    text = Image.open(target).text["msla_tests"]
    assert "screen: 240 x 120 px" in text
    assert "pixel: 34.40 x 30.00 um" in text
    assert "0.200 mm -> 7 px along Y = 210.0 um, 6 px along X = 206.4 um" in text
    assert "mirror: off" in text
    assert "polarity: white = the lines" in text


def test_the_mirrored_file_says_it_is_mirrored(tmp_path, screen_args, square_pixel_args):
    """A mask found later must not be silently the wrong way round."""
    target = run_mask(tmp_path, "bars", *screen_args, *square_pixel_args,
                      "--widths-mm", "0.2", "--lines", "2", "--mirror")
    text = Image.open(target).text["msla_tests"]
    assert "mirror: on" in text


def _marker(screen_px: int = 240) -> np.ndarray:
    """The F of the small screen: 2 mm of a 34.4 um pixel, 120 px tall."""
    return masks.marker_pixels(masks.Screen(screen_px, 120, 34.4, 34.4))


def test_the_marker_is_a_letter_f_asymmetric_in_both_axes():
    """A symmetric mark would not tell a mirrored exposure from an upside-down one.

    The reading key is the shape itself: the stem on the left, the arms to the top-right.
    """
    marker = _marker(5760)
    assert marker.any(), "the marker must draw something"
    assert not np.array_equal(marker, np.fliplr(marker)), "a mirrored F must differ"
    assert not np.array_equal(marker, np.flipud(marker)), "an upside-down F must differ"
    assert int(marker[:, 0].sum()) > int(marker[:, -1].sum()), "the stem is on the left"
    assert int(marker[0, :].sum()) > int(marker[-1, :].sum()), "the arms are at the top"


def test_the_marker_is_on_by_default_and_the_pattern_only_moves_right(
        tmp_path, screen_args, square_pixel_args):
    """The mark must not be drawn ON the pattern: it would corrupt what the pattern measures."""
    arguments = ("bars", *screen_args, *square_pixel_args, "--widths-mm", "0.2",
                 "--lines", "2", "--at", "0,0")
    plain = pixels(run_mask(tmp_path, *arguments, name="plain.png"))
    bare = pixels(run_mask(tmp_path, *arguments, "--no-marker", name="bare.png"))
    marker = _marker()
    marker_height, marker_width = marker.shape
    gap = int(round(masks.MARKER_GAP_MM / 0.0344))

    assert not np.array_equal(plain, bare), "the marker is on by default"
    assert np.array_equal(plain[:marker_height, :marker_width], marker)
    assert not plain[:marker_height, marker_width:marker_width + gap].any(), "a gap, not a touch"
    shift = marker_width + gap
    assert np.array_equal(plain[:, shift:], bare[:, :-shift]), "the pattern only moved right"


def test_the_marker_moves_with_the_mirror(tmp_path, screen_args, square_pixel_args,
                                         screen_width_px):
    """The picture is reflected as a whole: the F is found MIRRORED, on the other side.

    Mirroring reverses the order of the parts, so the marker that sat at the figure's
    left ends up at the figure's right: column ``x`` goes to ``width − 1 − x``.
    """
    arguments = ("bars", *screen_args, *square_pixel_args, "--widths-mm", "0.2",
                 "--lines", "2", "--at", "0,0")
    plain = pixels(run_mask(tmp_path, *arguments, name="plain.png"))
    mirrored = pixels(run_mask(tmp_path, *arguments, "--mirror", name="mirrored.png"))
    marker = _marker()
    marker_height, marker_width = marker.shape
    figure_left = int(np.nonzero(plain.any(axis=0))[0][0])
    left = screen_width_px - figure_left - marker_width
    found = mirrored[:marker_height, left:left + marker_width]
    assert np.array_equal(found, np.fliplr(marker))
    assert not np.array_equal(found, marker), "the reflected F must not read as straight"


def test_the_report_says_where_the_marker_is_and_how_to_read_it(
        tmp_path, screen_args, square_pixel_args, capsys):
    run_mask(tmp_path, "bars", *screen_args, *square_pixel_args,
             "--widths-mm", "0.2", "--lines", "2")
    out = capsys.readouterr().out
    assert "marker: the letter F in the top-left corner of the figure" in out
    assert "the pattern starts" in out
    assert "stem is on the LEFT" in out


# ─────────────────── placement of many figures (plan П5б) ──────────────────

def _white(width: int, height: int) -> masks.Figure:
    return masks.Figure(pixels=np.full((height, width), masks.WHITE, dtype=np.uint8),
                        report=())


def test_figures_are_pasted_at_their_pixels():
    """A placement is a pixel corner: the figure lands there, nothing is re-centred."""
    screen = masks.Screen(40, 30, 34.4, 34.4)
    image, lines = masks.compose(
        screen, (masks.Placement(_white(3, 2), 7, 9, name="a"),),
        mirror=False, invert=False)
    assert image[9:11, 7:10].all(), "the figure sits at its (x, y)"
    assert int((image > 0).sum()) == 6, "nothing else is painted"
    assert lines[0].startswith("figure a: 0.103 x 0.069 mm (3 x 2 px), at ")
    assert "(7, 9 px)" in lines[0]


def test_two_figures_that_overlap_are_refused():
    """A plate never shrinks a figure to make it fit: the clash is an answer."""
    screen = masks.Screen(100, 100, 34.4, 34.4)
    placements = (masks.Placement(_white(10, 10), 5, 5, name="a"),
                  masks.Placement(_white(10, 10), 10, 10, name="b"))
    with pytest.raises(masks.Refusal) as exc:
        masks.compose(screen, placements, mirror=False, invert=False)
    message = str(exc.value)
    assert "figure a" in message and "figure b" in message
    assert "overlap" in message
    assert "mm" in message and "px" in message


def test_a_named_figure_off_the_screen_is_refused_with_its_name():
    screen = masks.Screen(20, 20, 34.4, 34.4)
    with pytest.raises(masks.Refusal) as exc:
        masks.compose(screen, (masks.Placement(_white(5, 5), 18, 0, name="grid"),),
                      mirror=False, invert=False)
    message = str(exc.value)
    assert "figure grid" in message
    assert "does not fit" in message
