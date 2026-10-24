"""`font5x7.py` and `patterns.build_text` — the label on the plate (plan Т1, 24.10).

Cells closed here — what the font and the figure PROMISE:

    шрифт        все глифы попарно различны; у несимметричных (F, L, R, 2, 5, 7, s) картинка
                 не равна своему fliplr и своему flipud — иначе перевёрнутая пластина
                 читалась бы как правильная; у F перекладина сверху, у L — снизу, поэтому
                 глиф, перевёрнутый в таблице, врать не может
    сетка        "25s" при stroke_px = 6 — ровно (6·3 − 1)·6 = 102 px на 7·6 = 42 px
    промежуток   между буквами один пустой ЗНАК = 6 px чёрного, и он чёрный
    неквадрат    точка шрифта — квадрат в ПИКСЕЛЯХ: на пикселе 34 x 30 мкм картинка та же
    отказы       символ вне набора — с символом и местом в строке; пустая строка;
                 stroke_px < 1
    размещение   надпись поверх фигуры — отказ `compose` с ОБОИМИ именами; `--mirror`
                 отражает надпись вместе с пластиной (особого случая нет)

Empty cells and why: no cell for `dump`/`print-issues` of a plate with a label — that is
the acceptance of the plan (`out/plate_70x80_25s.px6s` rewritten with "25s"), and the
command line has no `text` figure of its own: the label comes from a config, whose parsing
cells live in `tests/test_plate_config.py`.
"""
from __future__ import annotations

import numpy as np
import pytest

from gerber2msla.font5x7 import BLANK, GLYPHS
from gerber2msla.masks import Refusal, Screen, compose
from gerber2msla.patterns import build_text
from gerber2msla.plate_config import fill_text, parse_plate_config
from gerber2msla.plate_layout import build_config_plate

ASYMMETRIC = ["F", "L", "R", "2", "5", "7", "s"]
"""Characters a plate is READ by: each must look different in a mirror and upside down."""

BODY = """
[output]
template = "t.px6s"
px6s = "plate.px6s"

[plate]
width_mm = 70
height_mm = 80

{figures}
"""

SQUARE_AND_TEXT = BODY.format(figures='''[[figure]]
kind = "square"
at_mm = [10, 10]
size_mm = [20, 20]
line_px = 6

[[figure]]
kind = "text"
at_mm = [10, 10]
text = "25s"
stroke_px = 6
''')

TEXT_ONLY = BODY.format(figures='''[[figure]]
kind = "text"
at_mm = [10, 10]
text = "25s"
stroke_px = 6
''')


def _bits(character: str) -> np.ndarray:
    """One glyph as a boolean picture of its dots: the shape, not the characters."""
    return np.array([[dot != BLANK for dot in row] for row in GLYPHS[character]])


def _message(text: str, stroke_px: int) -> str:
    """The one line the operator gets; a refusal that is not one line is a defect."""
    screen = Screen(width_px=5760, height_px=3600, pixel_x_um=34.0, pixel_y_um=34.0)
    with pytest.raises(Refusal) as caught:
        build_text(screen, text, stroke_px)
    message = str(caught.value)
    assert "\n" not in message, "a refusal is ONE line"
    return message


# ───────────────────────────────── the font ────────────────────────────────

def test_every_glyph_is_its_own_picture():
    """Two characters drawn the same way would make one of them unreadable for ever."""
    seen: dict[str, str] = {}
    for character, rows in GLYPHS.items():
        key = "".join(rows)
        assert key not in seen, f"{character!r} draws exactly what {seen[key]!r} draws"
        seen[key] = character


@pytest.mark.parametrize("character", ASYMMETRIC)
def test_an_asymmetric_character_differs_from_its_reflections(character):
    """A label is read in a mirror and upside down: these must give themselves away."""
    bits = _bits(character)
    assert not np.array_equal(bits, np.fliplr(bits)), "a mirrored label must read mirrored"
    assert not np.array_equal(bits, np.flipud(bits)), "a label turned over must read so"


def _ink_by_half(character: str) -> tuple[int, int]:
    """Lit dots in the TOP three rows and in the BOTTOM three: where the letter's bars are."""
    bits = _bits(character)
    return int(bits[:3].sum()), int(bits[-3:].sum())


@pytest.mark.parametrize("character, where", [("F", "top"), ("L", "bottom")])
def test_the_letters_that_say_which_way_is_up(character, where):
    """F's bar is at the top and L's at the bottom; a turned-over glyph would lie.

    This is not a second copy of the table: it is the property the plate is READ by. The
    marker of every mask in this utility is a letter F, and the whole point of it is that
    a mirrored or turned-over plate shows a letter that is wrong — which only works if the
    letter keeps its bar on the side the letter has it.
    """
    top, bottom = _ink_by_half(character)
    assert (top > bottom) if where == "top" else (bottom > top), \
        f"{character} must be heavier at its {where}: a turned-over glyph misleads"


def test_the_font_is_five_by_seven_and_holds_the_agreed_set():
    """The table is data: 5 x 7 dots per character, and no surprise characters."""
    for character, rows in GLYPHS.items():
        assert len(rows) == 7, f"{character!r} has {len(rows)} rows"
        for row in rows:
            assert len(row) == 5, f"{character!r} has a row of {len(row)} dots"
            assert set(row) <= {BLANK, "#"}, f"{character!r} has a row {row!r}"
    expected = set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
                   " .,-_: /()+=%".replace(" ", "")) | {" "}
    assert set(GLYPHS) == expected


# ──────────────────────────────── the figure ───────────────────────────────

def test_the_label_is_whole_screen_pixels_of_the_font_grid(sixks_screen):
    """(6·n − 1) dots across, 7 dots down, one dot = stroke_px screen pixels."""
    figure = build_text(sixks_screen, "25s", 6)
    assert (figure.width_px, figure.height_px) == (102, 42), "(6·3 − 1)·6 = 102, 7·6 = 42"


def test_one_blank_dot_stands_between_letters_and_it_is_black(sixks_screen):
    """The gap is a font dot of its own: white there would join two letters."""
    figure = build_text(sixks_screen, "25s", 6)
    for place in (1, 2):
        end = place * 6 * 6                     # (5 dots + 1 gap) * stroke_px
        assert not figure.pixels[:, end - 6:end].any(), f"the gap before letter {place + 1}"


def test_a_non_square_pixel_does_not_lean_the_letters():
    """The dot is a square in PIXELS: the same picture, whatever the axes measure."""
    square = Screen(width_px=5760, height_px=3600, pixel_x_um=34.0, pixel_y_um=34.0)
    squat = Screen(width_px=5760, height_px=3600, pixel_x_um=34.0, pixel_y_um=30.0)
    one, other = build_text(square, "25s", 6), build_text(squat, "25s", 6)
    assert np.array_equal(one.pixels, other.pixels), \
        "the grid is in pixels, so a non-square pixel changes the millimetres only"
    assert any("square in PIXELS" in line for line in other.report), \
        "and the report says which of the two is meant"


def test_the_report_names_the_text_the_dot_and_the_size(sixks_screen):
    """An operator reads the label's own numbers: the string, the dot, the size."""
    report = "\n".join(build_text(sixks_screen, "25s", 6).report)
    assert "'25s'" in report
    assert "one font dot = 6 x 6 px = 204.0 x 204.0 um" in report
    assert "drawn: 102 x 42 px = 3.468 x 1.428 mm" in report


# ───────────────────────────────── refusals ────────────────────────────────

def test_a_character_outside_the_font_is_refused_with_it_and_its_place():
    """Cyrillic is not in the font (decision of 24.10): it is a refusal, not a space."""
    message = _message("25с", 6)
    assert "'с'" in message, "the character itself, not 'invalid character'"
    assert "character 3" in message, "and WHERE it stands in the line"
    assert "Latin only" in message


def test_an_empty_label_is_refused():
    assert "empty" in _message("", 6)


def test_a_dot_below_one_pixel_is_refused():
    """A font dot of zero pixels would draw nothing and say nothing."""
    assert "at least 1" in _message("25s", 0)


# ─────────────────────────────── placement ─────────────────────────────────

def test_a_label_over_a_figure_is_refused_by_compose_with_both_names(sixks_screen):
    """One path places every figure: the label is not a special case of anything.

    The plate is composed on a canvas of its own before it is placed (the turn of 25.10),
    so the refusal comes out of `build_config_plate` — from `compose` all the same.
    """
    config = parse_plate_config(SQUARE_AND_TEXT, source="plate.toml")
    with pytest.raises(Refusal) as caught:
        build_config_plate(sixks_screen, config)
    message = str(caught.value)
    assert "square #1" in message and "text #2" in message
    assert "overlap" in message


def test_the_mirror_reflects_the_label_with_the_plate(sixks_screen):
    """No special case: the label is reflected by the same whole-picture swap."""
    config = parse_plate_config(TEXT_ONLY, source="plate.toml")
    placements, _ = build_config_plate(sixks_screen, config)
    plain, _ = compose(sixks_screen, placements, mirror=False, invert=False)
    flipped, _ = compose(sixks_screen, placements, mirror=True, invert=False)
    assert np.array_equal(flipped, np.fliplr(plain))
    assert np.count_nonzero(flipped) == np.count_nonzero(plain)


# ────────────────── the label follows the plate's time (25.10) ──────────────

@pytest.mark.parametrize("seconds, expected", [
    (20.0, "20s"), (7.0, "7s"), (2.5, "2.5s"), (25.0, "25s"),
], ids=["20 s", "7 s", "2.5 s", "25 s"])
def test_the_time_in_a_label_has_no_trailing_zeros(seconds, expected):
    """Read by eye: "20s" and "7s", never "20.000s"."""
    assert fill_text("{exposure_s}s", seconds) == expected


def test_a_label_without_the_substitution_is_left_alone():
    assert fill_text("TOP", 20.0) == "TOP"


def test_a_label_that_asks_for_a_time_the_plate_has_not_got_is_refused():
    """`{exposure_s}` in a config with no `[plate] exposure_s` has nothing to say."""
    with pytest.raises(Refusal) as caught:
        fill_text("{exposure_s}s", None)
    message = str(caught.value)
    assert "'exposure_s'" in message and "\n" not in message


TEXT_OF_TIME = (TEXT_ONLY.replace("height_mm = 80", "height_mm = 80\nexposure_s = 7")
                .replace('text = "25s"', 'text = "{exposure_s}s"'))


def test_the_drawn_label_carries_the_time_it_was_built_with(sixks_screen):
    """The point of the substitution: a copied config with another time draws "7s"."""
    config = parse_plate_config(TEXT_OF_TIME, source="plate.toml")
    _, report = build_config_plate(sixks_screen, config)
    assert "pattern: text '7s'" in "\n".join(report), \
        "the file says {exposure_s}, the plate says 7s"
