"""`gerber2msla/plate_config.py` and `plate_layout.py`: the TOML config, read STRICTLY.

Plan `plan_2026_10_24_plate_config`, К1. Strictness is a property of the whole module,
so the cells are a TABLE — input x direction x branch, one `parametrize` row per branch:

    key strictness    an unknown key refused BY NAME at every level it can appear at
                      (the root, [plate], [marker], a [[figure]], the inline range
                      table); a missing key refused the same way — no defaults anywhere
    kind strictness   an unknown figure kind refused with the list of the kinds
    type strictness   bool is not a number (TOML `true`), a float is not a whole pixel
                      count, a pair is exactly two numbers, `inf` and a negative corner
                      are refusals; a config with no [[figure]] at all is a refusal
    syntax            a broken TOML names the LINE of the file
    widths            an inclusive range with a float tolerance (3 branches), a list in
                      the order given, the pixel form as whole pixels, the mm and px
                      forms excluding each other, an empty list and a backwards range
    patches gap       "same" means "the gap is the width" (no width of its own), gap_mm
                      and gap_px are widths, a word that is not "same" and two forms at
                      once are refusals
    plate layout      the plate is centred; a corner counts from the PLATE's corner; a
                      plate larger than the screen and a figure off the plate are
                      refusals with names; two figures on one pixel are refused with
                      BOTH names — that refusal is `masks.compose`'s, the single path
    marker            no [marker] means no letter F and the report says so in words; a
                      [marker] is ONE F, where the config puts it
    exposure          [plate] exposure_s is read and named in the report

Empty cells, named rather than hidden: `_syntax_line`'s REGEX FALLBACK (the path for a
`TOMLDecodeError` without `.lineno`, Python 3.11/3.12) cannot be reached on this machine's
3.14, so the cell covers the attribute path only — the fallback is the older-minor path of
the same property, and the property "the refusal names the line" is what the cell holds.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

from gerber2msla.masks import Refusal, Screen, marker_pixels
from gerber2msla.patterns import Width
from gerber2msla.plate_config import fill_path, load_plate_config, parse_plate_config
from gerber2msla.plate_layout import build_config_plate

SCREEN = Screen(width_px=200, height_px=200, pixel_x_um=100.0, pixel_y_um=100.0)
"""20 x 20 mm at 100 um per pixel: 1 mm is exactly 10 px on BOTH axes, so a wrong axis
shows as a wrong number and not as rounding noise. The plate is 16 x 16 mm = 160 px."""

OUTPUT = """
[output]
template = "t.px6s"
px6s = "plate.px6s"
"""
"""The printer and the output (plan Б0). Required in every config, and — being about the
printer rather than about the figures — not the subject of most cells below."""

BASE = OUTPUT + """
[plate]
width_mm = 16
height_mm = 16

[[figure]]
kind = "square"
at_mm = [1, 1]
size_mm = [10, 10]
line_mm = 0.2
"""

PATCHES = BASE.replace(
    'kind = "square"\nat_mm = [1, 1]\nsize_mm = [10, 10]\nline_mm = 0.2',
    'kind = "patches"\nat_mm = [1, 1]\npatch_mm = 2\npatch_gap_mm = 0.5\n'
    'widths_mm = { from = 0.05, to = 0.20, step = 0.05 }\ngap = "same"')

GRID = BASE.replace(
    'kind = "square"\nat_mm = [1, 1]\nsize_mm = [10, 10]\nline_mm = 0.2',
    'kind = "grid"\nat_mm = [1, 1]\nsize_mm = [10, 10]\nline_mm = 0.2\n'
    'gap_mm = 0.2\ndirection = "both"')

TEXT = BASE.replace(
    'kind = "square"\nat_mm = [1, 1]\nsize_mm = [10, 10]\nline_mm = 0.2',
    'kind = "text"\nat_mm = [1, 1]\ntext = "25s"\nstroke_px = 6')
"""The label kind of plan Т1: the string and the size of ONE font dot."""

NO_FIGURES = OUTPUT + """
[plate]
width_mm = 16
height_mm = 16
"""


def _read(text: str, base: Path | None = None):
    return parse_plate_config(text, source="plate.toml", base=base)


def _message(text: str, base: Path | None = None) -> str:
    """The one line the operator gets; a refusal that is not one line is a defect."""
    with pytest.raises(Refusal) as caught:
        _read(text, base)
    message = str(caught.value)
    assert "\n" not in message, "a refusal is ONE line"
    return message


def _with_line(text: str, prefix: str, replacement: str) -> str:
    """Replace the one line starting with ``prefix`` — the configs differ by one key."""
    return re.sub(rf"^{prefix}.*$", replacement, text, flags=re.MULTILINE)


# ─────────────────────────────── reading ───────────────────────────────────

EVERY_KIND = BASE + '''
[[figure]]
kind = "bars"
at_mm = [1, 12]
widths_mm = [0.2, 0.1]
lines = 2

[[figure]]
kind = "patches"
at_mm = [1, 14]
patch_mm = 2
patch_gap_mm = 0.5
widths_px = [2, 1]
gap = "same"

[[figure]]
kind = "grid"
at_mm = [12, 1]
size_mm = [3, 3]
line_mm = 0.2
gap_mm = 0.2
direction = "both"

[[figure]]
kind = "text"
at_mm = [1, 14]
text = "25s"
stroke_px = 6
'''


def test_a_config_with_every_kind_is_read_into_specs():
    """Five kinds, the names numbered in the order of the FILE, the text kept whole."""
    config = _read(EVERY_KIND)
    assert [figure.kind for figure in config.figures] == ["square", "bars", "patches",
                                                          "grid", "text"]
    assert [figure.name for figure in config.figures] == ["square #1", "bars #2",
                                                          "patches #3", "grid #4",
                                                          "text #5"]
    assert (config.width_mm, config.height_mm) == (16.0, 16.0)
    assert config.marker_at_mm is None, "no [marker] table, no marker"
    assert config.text == EVERY_KIND, "the chunk of K2 carries the file as it was read"


UNKNOWN_KEY_CELLS = [
    ("root", "extra = 1\n" + BASE, "'extra'", "figure, marker, output, plate"),
    ("output", _with_line(BASE, "px6s", 'px6s = "plate.px6s"\npixels = [1, 1]'),
     "'pixels'", "the known keys are pixel_um, png, px6s, template"),
    ("plate", _with_line(BASE, "height_mm", "height_mm = 16\nwidht_mm = 8"),
     "'widht_mm'", "exposure_s, height_mm, rotate, width_mm"),
    ("marker", BASE.replace("[[figure]]", "[marker]\nat_mm = [1, 1]\nwidth_mm = 2\n\n"
                                          "[[figure]]"),
     "'width_mm'", "the known keys are at_mm"),
    ("figure", _with_line(BASE, "line_mm", "line_mm = 0.2\nlines = 5"),
     "'lines'", "at_mm, kind, line_mm, line_px, size_mm"),
    ("text figure", _with_line(TEXT, "stroke_px", "stroke_px = 6\nlines = 5"),
     "'lines'", "the known keys are at_mm, kind, stroke_px, text"),
    ("range table", PATCHES.replace("step = 0.05 }", "step = 0.05, count = 2 }"),
     "'count'", "the known keys are from, to, step"),
]


@pytest.mark.parametrize("level, text, named, known", UNKNOWN_KEY_CELLS,
                         ids=[cell[0] for cell in UNKNOWN_KEY_CELLS])
def test_an_unknown_key_is_refused_with_its_name(level, text, named, known):
    """A typo is never a silent default: the key is named, and so are the keys that fit."""
    message = _message(text)
    assert named in message, f"the refusal must name the key at the {level} level"
    assert "unknown key" in message
    assert known in message, "the operator is told which keys belong here"


MISSING_KEY_CELLS = [
    ("template", _with_line(BASE, "template", ""), "template"),
    ("width_mm", NO_FIGURES.replace("width_mm = 16\n", ""), "width_mm"),
    ("height_mm", _with_line(BASE, "height_mm", ""), "height_mm"),
    ("size_mm", _with_line(BASE, "size_mm", ""), "size_mm"),
    ("line", _with_line(BASE, "line_mm", ""), "line width"),
    ("direction", _with_line(GRID, "direction", ""), "direction"),
    ("patch_gap_mm", _with_line(PATCHES, "patch_gap_mm", ""), "patch_gap_mm"),
    ("widths", _with_line(PATCHES, "widths_mm", ""), "no widths"),
    ("gap", _with_line(PATCHES, "gap", ""), "no gap"),
    ("text", _with_line(TEXT, "text", ""), "text"),
    ("stroke_px", _with_line(TEXT, "stroke_px", ""), "stroke_px"),
]


@pytest.mark.parametrize("label, text, named", MISSING_KEY_CELLS,
                         ids=[cell[0] for cell in MISSING_KEY_CELLS])
def test_a_missing_key_is_refused_with_its_name(label, text, named):
    """The other half of "no defaults": nothing is filled in, the key is asked for."""
    message = _message(text)
    assert named in message
    assert "no defaults" in message, "the refusal says WHY it does not fill the gap"


def test_an_unknown_figure_kind_is_refused_with_the_list():
    """`patche` is not a figure: the refusal names the kinds that exist."""
    message = _message(BASE.replace('kind = "square"', 'kind = "patche"'))
    assert "unknown figure kind 'patche'" in message
    assert "the kinds are bars, grid, patches, square, text" in message


TYPE_CELLS = [
    ("bool is not a number", "height_mm = 16", "height_mm = true", "height_mm",
     "must be a number, got a boolean"),
    ("a table where a number goes", "height_mm = 16", "height_mm = [16]", "height_mm",
     "must be a number, got an array"),
    ("a string where a number goes", "height_mm = 16", "height_mm = 'sixteen'",
     "height_mm", "must be a number, got a string"),
    ("inf", "height_mm = 16", "height_mm = inf", "height_mm", "must be finite"),
    ("a pair of one", "size_mm = [10, 10]", "size_mm = [10]", "size_mm",
     "exactly two numbers"),
    ("a pair of three", "at_mm = [1, 1]", "at_mm = [1, 1, 1]", "at_mm",
     "exactly two numbers"),
    ("a scalar where a pair goes", "size_mm = [10, 10]", "size_mm = 10", "size_mm",
     "must be an array of two numbers"),
    ("a float where whole pixels go", "line_mm = 0.2", "line_px = 6.0", "line_px",
     "must be a whole number of pixels"),
    ("a negative corner", "at_mm = [1, 1]", "at_mm = [-1, 1]", "at_mm",
     "must not be negative"),
]


@pytest.mark.parametrize("label, old, new, named, expected", TYPE_CELLS,
                         ids=[cell[0] for cell in TYPE_CELLS])
def test_a_value_of_the_wrong_type_is_refused_with_its_key(label, old, new, named,
                                                           expected):
    """The key AND what was found: `true` is not a height, 6.0 is not a pixel count."""
    message = _message(BASE.replace(old, new))
    assert named in message and expected in message


TEXT_TYPE_CELLS = [
    ("a number where the label goes", 'text = "25s"', "text = 25", "'text'",
     "must be a string of characters"),
    ("a fraction of a dot", "stroke_px = 6", "stroke_px = 6.5", "stroke_px",
     "must be a whole number of pixels"),
    ("a bool where the dot goes", "stroke_px = 6", "stroke_px = true", "stroke_px",
     "must be a whole number of pixels"),
]


@pytest.mark.parametrize("label, old, new, named, expected", TEXT_TYPE_CELLS,
                         ids=[cell[0] for cell in TEXT_TYPE_CELLS])
def test_a_text_figure_of_the_wrong_type_is_refused_with_its_key(label, old, new, named,
                                                                 expected):
    """The label is a STRING and the dot is a WHOLE pixel count — no coercion either way."""
    message = _message(_with_line(TEXT, old, new))
    assert named in message and expected in message


@pytest.mark.parametrize("label, text, expected", [
    ("no figures", NO_FIGURES, "no [[figure]]"),
    ("an empty array", "figure = []\n" + NO_FIGURES, "no [[figure]]"),
    ("figure is not a list of tables", "figure = 5\n" + NO_FIGURES,
     "'figure' must be one or more [[figure]] tables"),
], ids=["no figures", "an empty array", "figure is a number"])
def test_a_plate_without_figures_is_refused(label, text, expected):
    """An empty plate draws nothing: the config must say what lies on it."""
    assert expected in _message(text)


def test_a_syntax_error_names_the_line_of_the_file():
    """A broken file is refused with the LINE, not with a Python traceback."""
    broken = "[plate]\nwidth_mm = 16\nheight_mm = = 16\n"
    message = _message(broken)
    assert message.startswith("plate.toml: line 3:"), message


# ───────────────────── the printer and the output (plan Б0) ─────────────────────

PNG_ONLY = BASE.replace('px6s = "plate.px6s"', 'png = "plate.png"')


def test_the_output_paths_count_from_the_config_directory(tmp_path):
    """Relative paths are resolved against the config's own directory (plan Б0)."""
    text = BASE.replace('"t.px6s"', '"templates/t.px6s"') \
               .replace('"plate.px6s"', '"out/plate.px6s"')
    config = _read(text, base=tmp_path)
    assert config.output.template == tmp_path / "templates" / "t.px6s"
    assert config.output.px6s == tmp_path / "out" / "plate.px6s"
    assert config.output.png is None, "no png key, no png file"
    assert config.output.pixel_um is None, "no measurement: the header's pixel is used"


def test_an_output_with_only_a_png_is_legal():
    """The PNG needs a screen too, so the template stays — and px6s may be absent."""
    config = _read(PNG_ONLY)
    assert config.output.png == Path("plate.png")
    assert config.output.px6s is None
    assert config.output.template == Path("t.px6s")


def test_an_output_with_neither_px6s_nor_png_is_refused():
    """A config that writes nothing does not say what it is for."""
    assert "writes nothing" in _message(_with_line(BASE, "px6s", ""))


def test_pixel_um_in_the_output_is_a_measurement_of_two_numbers():
    """It is not a default: absent means "the template header's pixel", which is named."""
    config = _read(_with_line(BASE, "template",
                              'template = "t.px6s"\npixel_um = [34.0, 30.0]'))
    assert config.output.pixel_um == (34.0, 30.0)


def test_a_bad_pixel_um_is_refused_with_its_axis():
    message = _message(_with_line(BASE, "template",
                                  'template = "t.px6s"\npixel_um = [0, 34]'))
    assert "'pixel_um[0]'" in message and "must be positive" in message


def test_load_refuses_a_missing_template_with_its_key_and_path(tmp_path):
    """The template is an INPUT: `load` checks it exists and names the key and the path."""
    config_file = tmp_path / "plate.toml"
    config_file.write_text(BASE)
    with pytest.raises(Refusal) as caught:
        load_plate_config(config_file)
    message = str(caught.value)
    assert "'template'" in message
    assert str(tmp_path / "t.px6s") in message
    assert "no such file exists" in message


def test_a_config_file_that_cannot_be_read_is_refused(tmp_path):
    """Both branches of the read: no file at all, and bytes that are not UTF-8.

    A config printed from a Windows editor in cp1251 is the real case: the file is there,
    the bytes are not TOML's, and the operator gets one line instead of a traceback.
    """
    with pytest.raises(Refusal, match="cannot read the plate config"):
        load_plate_config(tmp_path / "absent.toml")
    foreign = tmp_path / "cp1251.toml"
    foreign.write_bytes("[plate]\n# \u043a\u043e\u043c\u043c\u0435\u043d\u0442\u0430\u0440\u0438\u0439\n"
                        .encode("cp1251"))
    with pytest.raises(Refusal, match="is not UTF-8"):
        load_plate_config(foreign)


# ──────────────────────────────── widths ───────────────────────────────────

RANGE_CELLS = [
    ("0.05 step 0.05 to 0.20", (0.05, 0.20, 0.05), [0.05, 0.10, 0.15, 0.20]),
    ("0.1 step 0.1 to 0.3", (0.1, 0.3, 0.1), [0.1, 0.2, 0.3]),
    ("0.05 step 0.07 to 0.20", (0.05, 0.20, 0.07), [0.05, 0.12, 0.19]),
]


@pytest.mark.parametrize("label, bounds, expected", RANGE_CELLS,
                         ids=[cell[0] for cell in RANGE_CELLS])
def test_a_range_of_widths_is_inclusive(label, bounds, expected):
    """`to` is IN the range: (0.20 - 0.05) / 0.05 is 2.9999999999999996 in floats."""
    start, stop, step = bounds
    text = _with_line(PATCHES, "widths_mm",
                      f"widths_mm = {{ from = {start}, to = {stop}, step = {step} }}")
    config = _read(text)
    assert [width.mm for width in config.figures[0].widths] == pytest.approx(expected)


BAD_RANGE_CELLS = [
    ("step is zero", "widths_mm = { from = 0.05, to = 0.20, step = 0 }",
     "'widths_mm.step' must be positive"),
    ("step is negative", "widths_mm = { from = 0.05, to = 0.20, step = -0.05 }",
     "'widths_mm.step' must be positive"),
    ("from is greater than to", "widths_mm = { from = 0.20, to = 0.05, step = 0.05 }",
     "'widths_mm' runs backwards"),
    ("an empty list", "widths_mm = []", "is an empty array"),
    ("both forms", "widths_mm = [0.2]\nwidths_px = [6]", "widths given twice"),
    ("a width of zero", "widths_mm = [0.2, 0]", "'widths_mm[1]' must be positive"),
    ("a zero pixel width", "widths_px = [0]", "'widths_px[0]' must be at least 1"),
]


@pytest.mark.parametrize("label, widths_line, expected", BAD_RANGE_CELLS,
                         ids=[cell[0] for cell in BAD_RANGE_CELLS])
def test_a_bad_range_or_list_is_refused(label, widths_line, expected):
    """A range that cannot mean what it says is a refusal, never a silent shrink."""
    assert expected in _message(_with_line(PATCHES, "widths", widths_line))


def test_the_widths_keep_the_order_of_the_file():
    """The order IS the layout (rows top to bottom): it must not be sorted for us."""
    config = _read(_with_line(PATCHES, "widths_mm", "widths_mm = [0.2, 0.05, 0.15]"))
    assert [width.mm for width in config.figures[0].widths] == [0.2, 0.05, 0.15]


@pytest.mark.parametrize("label, gap_line, expected", [
    ("same", 'gap = "same"', None),
    ("millimetres", "gap_mm = 0.1", Width(mm=0.1)),
    ("pixels", "gap_px = 1", Width(px=1)),
], ids=["same", "millimetres", "pixels"])
def test_the_patches_gap_is_the_width_or_a_width_of_its_own(label, gap_line, expected):
    """`same` is not a width here: the builder then takes the width of each row."""
    config = _read(_with_line(PATCHES, "gap", gap_line))
    assert config.figures[0].gap == expected


@pytest.mark.parametrize("label, gap_line, expected", [
    ("a word that is not same", 'gap = "equal"', "'gap' must be one of 'same'"),
    ("two forms at once", 'gap = "same"\ngap_mm = 0.1', "gap given twice"),
], ids=["a word that is not same", "two forms at once"])
def test_a_bad_patches_gap_is_refused(label, gap_line, expected):
    assert expected in _message(_with_line(PATCHES, "gap", gap_line))


# ─────────────────────────────── the plate ─────────────────────────────────

SQUAT = Screen(width_px=200, height_px=200, pixel_x_um=100.0, pixel_y_um=50.0)
"""A NON-square pixel: 1 mm is 10 px across and 20 px down, so a swapped axis shows as
a swapped number and not as rounding noise."""


def _white_box(pixels: np.ndarray) -> tuple[int, int, int, int]:
    """The box of the white in a FIGURE's own pixels: left and upper IN, right and lower OUT."""
    rows, columns = np.nonzero(pixels)
    return (int(columns.min()), int(rows.min()),
            int(columns.max()) + 1, int(rows.max()) + 1)


def test_a_corner_on_a_non_square_pixel_uses_its_own_axis():
    """`at_mm` is X then Y: on a 100 x 50 um pixel the two counts differ by a factor 2.

    Checked on the PIXELS of the plate (the plate is one figure since the turn of 25.10),
    so a swapped axis cannot hide behind a report line: 1 mm across is 10 px and 2 mm down
    is 40 px, and the white of a 5 x 2 mm contour starts exactly there.
    """
    text = _with_line(_with_line(BASE, "width_mm", "width_mm = 10"), "height_mm",
                      "height_mm = 5")
    text = _with_line(text, "size_mm", "size_mm = [5, 2]")
    text = _with_line(text, "at_mm", "at_mm = [1, 2]")
    placements, _ = build_config_plate(SQUAT, _read(text))
    picture = placements[0].figure.pixels
    assert picture.shape == (100, 100), "the plate 10 x 5 mm at 100 x 50 um = 100 x 100 px"
    assert _white_box(picture) == (10, 40, 60, 80), \
        "the contour starts 1 mm across (10 px) and 2 mm down (40 px) inside the plate"


def test_the_plate_is_centred_and_a_corner_counts_from_it():
    """`at_mm` counts from the PLATE's corner; the plate itself sits in the middle."""
    placements, report = build_config_plate(SCREEN, _read(BASE))
    assert [(placement.name, placement.x_px, placement.y_px) for placement in placements] \
        == [("plate", 20, 20)], "ONE picture, centred: the plate starts at 20, 20 px"
    text = "\n".join(report)
    assert "centred on the 200 x 200 px screen at 20, 20 px" in text
    assert ("at 1.000, 1.000 mm from the plate's top-left corner (10, 10 px inside it)"
            in text)
    assert "figure square #1:" in text, "the table row of the figure"
    assert "  pattern: square, side 10.000 x 10.000 mm" in text, \
        "the figure's own report travels with the plate"
    assert _white_box(placements[0].figure.pixels) == (10, 10, 110, 110), \
        "and the pixels agree with the line: the contour lies 1 mm inside the plate"


def test_a_plate_larger_than_the_screen_is_refused():
    """The centred plate would hang off both sides: a refusal with the numbers."""
    text = _with_line(BASE, "width_mm", "width_mm = 40")
    with pytest.raises(Refusal) as caught:
        build_config_plate(SCREEN, _read(text))
    message = str(caught.value)
    assert "400 x 160 px" in message and "larger than the 200 x 200 px screen" in message


def test_a_figure_that_does_not_fit_the_plate_is_refused_with_its_name():
    """The plate never shrinks a figure to make it fit, and the refusal says which one."""
    text = _with_line(BASE, "size_mm", "size_mm = [20, 10]")
    with pytest.raises(Refusal) as caught:
        build_config_plate(SCREEN, _read(text))
    message = str(caught.value)
    assert "the figure square #1" in message
    assert "does not fit the plate" in message
    assert "mm" in message and "px" in message


def test_two_figures_on_one_pixel_are_refused_with_both_names():
    """The overlap is `compose`'s refusal — the single placement path — and names BOTH.

    Since the plate is composed BEFORE it is placed (the turn of 25.10 needs the finished
    picture), the refusal comes out of `build_config_plate`; the property is the same one,
    and the names are the figures' own.
    """
    text = BASE + ('\n[[figure]]\nkind = "square"\nat_mm = [1, 1]\n'
                   'size_mm = [10, 10]\nline_mm = 0.2\n')
    with pytest.raises(Refusal) as caught:
        build_config_plate(SCREEN, _read(text))
    message = str(caught.value)
    assert "figure square #1" in message and "figure square #2" in message
    assert "overlap" in message


def test_no_marker_table_means_no_marker_and_the_report_says_so():
    """No silent F: the operator asked for a layout, and the layout has no marker."""
    placements, report = build_config_plate(SCREEN, _read(BASE))
    assert [placement.name for placement in placements] == ["plate"]
    assert ("no marker: the plate carries no orientation reference" in "\n".join(report))


def test_the_marker_is_one_f_where_the_config_puts_it():
    """One F per plate, at the corner the config names, inside the plate — in the pixels."""
    text = BASE.replace("[[figure]]", "[marker]\nat_mm = [2, 2]\n\n[[figure]]")
    placements, report = build_config_plate(SCREEN, _read(text))
    assert [placement.name for placement in placements] == ["plate"]
    picture = placements[0].figure.pixels
    letter = marker_pixels(SCREEN)
    assert letter.shape == (20, 20), "a 2 mm F at 100 um per pixel"
    assert np.array_equal(picture[20:40, 20:40], letter), \
        "the F sits 2 mm, 2 mm inside the plate, and the plate is a canvas of its own"
    assert "ONE letter F at 2.000, 2.000 mm" in "\n".join(report)


def test_the_exposure_time_is_read_and_named_in_the_report():
    """`[plate] exposure_s` belongs to the config (decision of 24.10): it is reported.

    Since 25.10 it is a TUPLE of times — a list is a series, one file per time — so one
    number is a tuple of one. This cell pins that shape and the line of the file's time.
    """
    text = _with_line(BASE, "height_mm", "height_mm = 16\nexposure_s = 25")
    config = _read(text)
    assert config.exposure_s == (25.0,), "one number, a tuple of one"
    assert config.times == (25.0,), "one entry per file to write"
    _, report = build_config_plate(SCREEN, config, 25.0)
    assert "exposure: 25 s from [plate] exposure_s" in "\n".join(report)


# ─────────────────────────── the series (25.10) ────────────────────────────

SERIES = (_with_line(BASE, "height_mm", "height_mm = 16\nexposure_s = [7, 25]")
          .replace('px6s = "plate.px6s"', 'px6s = "plate_{exposure_s}s.px6s"'))


def test_a_list_of_times_is_a_series_read_in_order():
    """One plate per time, in the order of the file — the copies of one config are gone."""
    config = _read(SERIES)
    assert config.exposure_s == (7.0, 25.0)
    assert config.times == (7.0, 25.0), "one entry per file to write"


def test_one_number_is_a_tuple_of_one_and_no_key_is_no_time():
    single = _read(_with_line(BASE, "height_mm", "height_mm = 16\nexposure_s = 25"))
    assert single.times == (25.0,)
    assert _read(BASE).exposure_s is None, "no [plate] exposure_s at all"
    assert _read(BASE).times == (None,), "one file, and it has no time to write"


@pytest.mark.parametrize("label, line, expected", [
    ("an empty list", "exposure_s = []", "empty array"),
    ("the same time twice", "exposure_s = [7, 7.0]", "holds 7 twice"),
    ("a string in the list", 'exposure_s = [7, "10"]', "'exposure_s[1]' must be a number"),
    ("a negative time", "exposure_s = [7, -1]", "'exposure_s[1]' must be positive"),
], ids=["an empty list", "the same time twice", "a string in the list", "a negative time"])
def test_a_series_that_cannot_write_one_file_per_time_is_refused(label, line, expected):
    assert expected in _message(_with_line(BASE, "height_mm", f"height_mm = 16\n{line}"))


def test_a_series_must_name_the_time_in_every_output_path():
    """Without the time the files would overwrite each other, and the last would win."""
    plain = _with_line(BASE, "height_mm", "height_mm = 16\nexposure_s = [7, 25]")
    assert "'px6s' has no {exposure_s}" in _message(plain)
    _read(SERIES)                       # with the time in the name it is a legal series


def test_a_series_must_name_the_time_in_the_png_too():
    text = _with_line(BASE, "height_mm", "height_mm = 16\nexposure_s = [7, 25]")
    text = text.replace('px6s = "plate.px6s"',
                        'px6s = "plate_{exposure_s}s.px6s"\npng = "plate.png"')
    assert "'png' has no {exposure_s}" in _message(text)


def test_a_second_brace_in_an_output_path_is_refused():
    text = _with_line(BASE, "height_mm", "height_mm = 16\nexposure_s = [7, 25]")
    text = text.replace('px6s = "plate.px6s"', 'px6s = "plate_{expo}s.px6s"')
    assert "character 7 of 'px6s'" in _message(text)


@pytest.mark.parametrize("name, seconds, expected", [
    ("out/plate_{exposure_s}s.px6s", 7.0, "out/plate_7s.px6s"),
    ("out/plate_{exposure_s}s.px6s", 2.5, "out/plate_2.5s.px6s"),
    ("out/plate.png", 7.0, "out/plate.png"),
], ids=["7 s", "2.5 s", "no substitution"])
def test_an_output_path_takes_the_time_into_its_name(name, seconds, expected):
    """The same number as the label: no trailing zeros, no padding."""
    assert fill_path(Path(name), seconds) == Path(expected)


def test_an_output_path_that_asks_for_a_time_the_config_has_not_got_is_refused():
    with pytest.raises(Refusal) as caught:
        fill_path(Path("plate_{exposure_s}s.px6s"), None)
    assert "{exposure_s}" in str(caught.value)


# ──────────────────────── the label's substitution (25.10) ──────────────────

@pytest.mark.parametrize("label, line, expected", [
    ("another name in braces", 'text = "{expo}s"', "character 1 of 'text'"),
    ("a stray brace after the good one", 'text = "{exposure_s}s}"',
     "character 14 of 'text'"),
    ("the substitution twice", 'text = "{exposure_s}{exposure_s}"', "twice"),
], ids=["another name in braces", "a stray brace after the good one",
        "the substitution twice"])
def test_a_label_with_a_brace_that_is_not_the_one_substitution_is_refused(label, line,
                                                                          expected):
    """A brace is a promise: only `{exposure_s}` means anything, and the place is named."""
    assert expected in _message(_with_line(TEXT, "text", line))


# ──────────────────────────── the turn (25.10) ─────────────────────────────

def test_a_quarter_turn_is_read():
    """`[plate] rotate` is 0, 90, 180 or 270 degrees, counter-clockwise."""
    text = _with_line(BASE, "height_mm", "height_mm = 16\nrotate = 90")
    assert _read(text).rotate == 90
    assert _read(BASE).rotate == 0, "no [plate] rotate: the plate lies as drawn"


@pytest.mark.parametrize("line, expected", [
    ("rotate = 45", "'rotate' must be 0, 90, 180 or 270"),
    ("rotate = 90.0", "'rotate' must be 0, 90, 180 or 270"),
    ("rotate = '90'", "'rotate' must be 0, 90, 180 or 270"),
    ("rotate = -90", "'rotate' must be 0, 90, 180 or 270"),
], ids=["a fifth angle", "a float", "a string", "a negative angle"])
def test_a_turn_that_is_not_a_quarter_is_refused(line, expected):
    assert expected in _message(_with_line(BASE, "height_mm", f"height_mm = 16\n{line}"))


NON_SQUARE_PLATE = _with_line(_with_line(BASE, "width_mm", "width_mm = 10"),
                              "size_mm", "size_mm = [5, 5]")
"""10 x 16 mm at 100 um: 100 x 160 px, so the turn has sides to swap."""


def test_the_turn_is_the_turned_plate_centred_again():
    """A quarter COUNTER-clockwise, the sides swapped, and the turned plate centred."""
    plain, _ = build_config_plate(SCREEN, _read(NON_SQUARE_PLATE))
    turned, report = build_config_plate(
        SCREEN, _read(_with_line(NON_SQUARE_PLATE, "height_mm",
                                 "height_mm = 16\nrotate = 90")))
    drawn = plain[0].figure.pixels
    assert drawn.shape == (160, 100), "10 x 16 mm at 100 um = 100 x 160 px"
    assert turned[0].figure.pixels.shape == (100, 160), "the turn swaps the sides"
    assert np.array_equal(turned[0].figure.pixels, np.rot90(drawn)), \
        "counter-clockwise: a clockwise turn is a different plate"
    assert (turned[0].x_px, turned[0].y_px) == (20, 50), \
        "centred again on the 200 x 200 px screen"
    text = "\n".join(report)
    assert "turned 90 degrees counter-clockwise to 160 x 100 px" in text
    assert "centred on the 200 x 200 px screen at 20, 50 px" in text


def test_a_quarter_turn_on_a_non_square_pixel_is_refused():
    """A quarter turn would put every distance on the pitch of the other axis."""
    text = _with_line(_with_line(BASE, "width_mm", "width_mm = 8"), "height_mm",
                      "height_mm = 8\nrotate = 90")
    text = _with_line(text, "size_mm", "size_mm = [4, 4]")
    with pytest.raises(Refusal) as caught:
        build_config_plate(SQUAT, _read(text))
    assert "not square" in str(caught.value)
    assert "quarter turn" in str(caught.value)
