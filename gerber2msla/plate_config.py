# gerber2msla/plate_config.py
"""The plate config: a TOML file that says what lies on the plate — read STRICTLY.

    # millimetres; origin at the plate's top-left corner
    [plate]
    width_mm  = 70
    height_mm = 78
    exposure_s = 25                  # optional here; the .px6s writer needs it

    [marker]                         # optional: no [marker] means no letter F
    at_mm = [3.196, 3.196]           # one F per plate

    [[figure]]
    kind    = "square"               # square | bars | patches | grid
    at_mm   = [2, 2]
    size_mm = [66, 74]
    line_mm = 0.2                    # or line_px = 6

    [[figure]]
    kind         = "patches"         # one S x S patch per width: a row per width
    at_mm        = [5, 8]
    patch_mm     = 10
    patch_gap_mm = 1.5
    widths_mm    = { from = 0.05, to = 0.20, step = 0.05 }   # inclusive
    gap          = "same"            # gap = the stripe width; or gap_mm / gap_px

STRICT, IN BOTH DIRECTIONS. Every key a figure needs must be in the file — this config
has NO defaults, because a silent default is exactly how a typo (`widht_mm`) becomes a
plate nobody meant to expose. A key that is not in the table of its kind is refused with
its own name and the list of the keys that belong there; a missing key is refused the
same way; a value of the wrong type is refused with the key and the type found; an
unknown figure kind is refused with the list of kinds; a TOML syntax error is refused
with the LINE NUMBER of the file (``TOMLDecodeError.lineno`` on 3.14, the message text
before it). Refusals are single ASCII English lines, as everywhere in the utility;
the config text itself is the operator's and may be in any language — it travels into
the PNG chunk whole (plan K2), UTF-8.

WIDTHS come in the two forms the rest of the utility knows (``contracts.md``: a width
is a whole number of pixels of its own axis): millimetres (``widths_mm``, ``line_mm``,
``gap_mm``, ``patch_mm``, ``patch_gap_mm``) or whole screen pixels (``widths_px``,
``line_px``, ``gap_px``). A width LIST is either an array in the order to draw, or a
range ``{from, to, step}`` — INCLUSIVE, with a float tolerance, because
``(0.20 - 0.05) / 0.05`` is 2.9999999999999996 and the 0.20 width is the one the
operator asked for. ``step <= 0`` and ``from > to`` are refusals.

NOT HERE: pixels and pictures. This module turns the text into specs; the drawing is
``patterns.build_*`` and the placement is ``plate_layout.build_config_plate``. Nothing
below rounds a millimetre to a pixel, so a config can be checked without a screen.

Standard library only: ``tomllib`` is 3.11+, and the project's floor is 3.11.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from .config_strict import (_keys, _loads, _must_exist, _number, _pair, _read_text,
                            _required, _resolve, _string, _table, _text, _what, _whole)
from .masks import Refusal
from .patterns import DIRECTIONS, Width

KINDS = ("bars", "grid", "patches", "square", "text")
"""Every figure kind the config may ask for; anything else is a refusal, not a guess."""

FIGURE_KEYS: dict[str, tuple[str, ...]] = {
    "bars": ("at_mm", "kind", "lines", "widths_mm", "widths_px"),
    "grid": ("at_mm", "direction", "gap_mm", "gap_px", "kind", "line_mm", "line_px",
             "size_mm"),
    "patches": ("at_mm", "gap", "gap_mm", "gap_px", "kind", "patch_gap_mm", "patch_mm",
                "widths_mm", "widths_px"),
    "square": ("at_mm", "kind", "line_mm", "line_px", "size_mm"),
    "text": ("at_mm", "kind", "stroke_px", "text"),
}
"""The keys of each kind, sorted: this table IS the strictness of a figure.

The refusal that names an unknown key reads this very table, so a new key cannot be
added to the reader and forgotten in the message, or the other way round.
"""

PLATE_KEYS = ("exposure_s", "height_mm", "rotate", "width_mm")
ROTATIONS = (0, 90, 180, 270)
"""A quarter, half or three-quarter turn, COUNTER-clockwise about the plate's centre.

Absent means 0 — "the plate lies as drawn" — and the report says so in words: the turn is
a fact about the picture, and a plate that was not turned is not a plate that was.
"""
TEXT_PLACEHOLDER = "{exposure_s}"
"""The ONE substitution a label may hold: the plate's own exposure time.

Denis, 25.10: he copied a config, changed `[plate] exposure_s` to 7, and the label went on
saying "25s" — the file said one thing and the plate another. Now the label can say
`text = "{exposure_s}s"` and follows the time by construction; any other brace is a typo
and is refused with its place.
"""
MARKER_KEYS = ("at_mm",)
OUTPUT_KEYS = ("pixel_um", "png", "px6s", "template")
ROOT_KEYS = ("figure", "marker", "output", "plate")
RANGE_KEYS = ("from", "to", "step")
RANGE_TOLERANCE = 1e-9
"""How far a float step may miss the end of its range before the last width is lost.

0.05 ... 0.20 step 0.05 is three steps, but (0.20 - 0.05) / 0.05 is 2.9999999999999996
in binary floating point: without the tolerance the range would drop the 0.20 width —
the widest one, and usually the one the operator is checking first.
"""


# ─────────────────────────────── the specs ─────────────────────────────────

@dataclass(frozen=True, slots=True)
class SquareSpec:
    """A closed contour; the side and the line are the operator's own request."""

    name: str
    at_mm: tuple[float, float]
    size_mm: tuple[float, float]
    line: Width
    kind: ClassVar[str] = "square"


@dataclass(frozen=True, slots=True)
class GridSpec:
    """A rectangle filled with lines, whole lines only, the first flush with the edge."""

    name: str
    at_mm: tuple[float, float]
    size_mm: tuple[float, float]
    line: Width
    gap: Width
    direction: str
    kind: ClassVar[str] = "grid"


@dataclass(frozen=True, slots=True)
class BarsSpec:
    """Groups of lines; the one figure whose bytes match Gerber2LDI 364fd28."""

    name: str
    at_mm: tuple[float, float]
    widths: tuple[Width, ...]
    lines: int
    kind: ClassVar[str] = "bars"


@dataclass(frozen=True, slots=True)
class PatchesSpec:
    """One S x S patch per width: horizontal stripes in the left square of a row,
    vertical stripes in the right one; ``gap`` None means "the gap is the width"."""

    name: str
    at_mm: tuple[float, float]
    patch_mm: float
    patch_gap_mm: float
    widths: tuple[Width, ...]
    gap: Width | None
    kind: ClassVar[str] = "patches"


@dataclass(frozen=True, slots=True)
class TextSpec:
    """A label in the utility's own font; ``stroke_px`` is the size of ONE font dot.

    The dot is whole SCREEN pixels, not millimetres (plan Т1): the label must be the same
    picture on every machine, and a non-square pixel must not lean the letters.
    """

    name: str
    at_mm: tuple[float, float]
    text: str
    stroke_px: int
    kind: ClassVar[str] = "text"


FigureSpec = SquareSpec | GridSpec | BarsSpec | PatchesSpec | TextSpec


@dataclass(frozen=True, slots=True)
class PlateOutput:
    """EVERYTHING about the printer: the template, the measurement, and where to write.

    ``template`` is ALWAYS required (plan Б0, decision of 24.10): the screen comes from
    the printer's own file and from nowhere else, because ``--screen-px`` and
    ``--pixel-um`` next to ``--config`` are refusals. The plan's "required when px6s is
    given" was too narrow — a PNG needs a screen too.

    ``pixel_um`` is a MEASUREMENT (rule Г2): it changes the geometry only, and the pixel
    stored in the file header stays the template's. Absent — the header's pixel is used.
    """

    template: Path
    pixel_um: tuple[float, float] | None = None
    px6s: Path | None = None
    png: Path | None = None


@dataclass(frozen=True, slots=True)
class PlateConfig:
    """A config read and checked: no pixels yet, only what the operator asked for."""

    width_mm: float
    height_mm: float
    exposure_s: float | None
    marker_at_mm: tuple[float, float] | None
    figures: tuple[FigureSpec, ...]
    output: PlateOutput
    text: str
    """The file as it was read: it goes into the PNG chunk whole, UTF-8 (plan K2)."""
    rotate: int = 0
    """Counter-clockwise turn of the finished plate: 0, 90, 180 or 270 degrees."""
    path: Path | None = None

    @property
    def label(self) -> str:
        return "<config>" if self.path is None else str(self.path)


# ───────────────────────────── refusal wording ─────────────────────────────

# The strict helpers (`_what`, `_table`, `_keys`, `_required`, `_number`, `_whole`,
# `_pair`, `_string`, `_loads`, `_read_text`) live in `config_strict.py`: the board
# config of plan Б1 asks the same questions, and a second copy of "an unknown key is a
# refusal" is where the two configs would start to disagree. What stays here is what is
# about WIDTHS and about this file's own keys.


def _one_of(table: dict, keys: tuple[str, ...], where: str, source: str,
            what: str) -> tuple[str, object]:
    """Exactly one of the forms: millimetres or pixels, never both, never neither."""
    present = [key for key in keys if key in table]
    if len(present) > 1:
        raise Refusal(f"{source}: {where}: {what} given twice "
                      f"({', '.join(present)}): use one of them")
    if not present:
        raise Refusal(f"{source}: {where}: no {what}: give one of "
                      f"{', '.join(keys)} (this config has no defaults)")
    return present[0], table[present[0]]


# ──────────────────────────────── widths ───────────────────────────────────

def _width(key: str, value: object, where: str, source: str) -> Width:
    """One width in either form; the ``_px`` key is the only thing that decides which."""
    if key.endswith("_px"):
        return Width(px=_whole(value, key, where, source))
    return Width(mm=_number(value, key, where, source))


def _range(key: str, table: dict, where: str, source: str, *, pixel: bool) -> list:
    """``{from, to, step}``, INCLUSIVE; the step may be a float that misses the end."""
    inside = f"{where}: '{key}'"
    _keys(table, RANGE_KEYS, inside, source)
    for name in RANGE_KEYS:
        _required(table, name, inside, source)
    read = (lambda item, field: _whole(item, f"{key}.{field}", where, source)) \
        if pixel else (lambda item, field: _number(item, f"{key}.{field}", where, source))
    start = read(table["from"], "from")
    stop = read(table["to"], "to")
    step = read(table["step"], "step")
    if start > stop:
        raise Refusal(f"{source}: {where}: '{key}' runs backwards: from {start!r} is "
                      f"greater than to {stop!r}")
    count = int(math.floor((stop - start) / step + RANGE_TOLERANCE)) + 1
    return [start + index * step for index in range(count)]


def _widths(table: dict, where: str, source: str) -> tuple[Width, ...]:
    """The widths of a figure: an array in the order to draw, or an inclusive range."""
    key, value = _one_of(table, ("widths_mm", "widths_px"), where, source, "widths")
    pixel = key.endswith("_px")
    make = (lambda number: Width(px=number)) if pixel else (lambda number: Width(mm=number))
    if type(value) is list:
        if not value:
            raise Refusal(f"{source}: {where}: '{key}' is an empty array: a figure needs "
                          f"at least one width")
        return tuple(make(_whole(item, f"{key}[{index}]", where, source)
                          if pixel else
                          _number(item, f"{key}[{index}]", where, source))
                     for index, item in enumerate(value))
    if type(value) is not dict:
        raise Refusal(f"{source}: {where}: '{key}' must be an array of widths or a range "
                      f"table {{ from, to, step }}, got {_what(value)}")
    return tuple(make(number) for number in _range(key, value, where, source, pixel=pixel))


def _rotation(table: dict, where: str, source: str) -> int:
    """``[plate] rotate``: a quarter turn, and nothing else. Absent means 0."""
    if "rotate" not in table:
        return 0
    value = table["rotate"]
    if type(value) is not int or value not in ROTATIONS:
        raise Refusal(f"{source}: {where}: 'rotate' must be 0, 90, 180 or 270 (whole "
                      f"degrees, counter-clockwise), got {value!r}")
    return value


def _placeholders(text: str, where: str, source: str) -> None:
    """Only ``{exposure_s}`` may stand in the label, exactly once; any other brace is a typo.

    The character number is what the operator needs: a Cyrillic "с" inside a brace looks
    like a substitution to the eye, and "line 12 of your config" is the only useful answer.
    """
    index = 0
    seen = 0
    while index < len(text):
        character = text[index]
        if character in "{}":
            if text.startswith(TEXT_PLACEHOLDER, index):
                seen += 1
                if seen > 1:
                    raise Refusal(f"{source}: {where}: 'text' holds {TEXT_PLACEHOLDER} "
                                  f"twice: one substitution is allowed, because the plate "
                                  f"has one exposure time")
                index += len(TEXT_PLACEHOLDER)
                continue
            raise Refusal(f"{source}: {where}: character {index + 1} of 'text' is "
                          f"{character!r}: the only substitution is "
                          f"{TEXT_PLACEHOLDER!r}, and any other brace is a typo, not a "
                          f"label")
        index += 1


def fill_text(text: str, exposure_s: float | None, *, source: str = "the config") -> str:
    """The label as it will be DRAWN: the one placeholder becomes the exposure time.

    The number has no trailing zeros (``20``, ``7``, ``2.5``): a label is read by eye, and
    "20.000s" is noise next to "20s".
    """
    if TEXT_PLACEHOLDER not in text:
        return text
    if exposure_s is None:
        raise Refusal(f"{source}: the label {text!r} asks for {TEXT_PLACEHOLDER} and "
                      f"[plate] has no 'exposure_s': there is no time to write in it")
    return text.replace(TEXT_PLACEHOLDER, f"{exposure_s:g}")


def _patch_gap(table: dict, where: str, source: str) -> Width | None:
    """``gap = "same"`` (the gap is the stripe width), or one width of its own."""
    present = [key for key in ("gap", "gap_mm", "gap_px") if key in table]
    if len(present) > 1:
        raise Refusal(f"{source}: {where}: gap given twice "
                      f"({', '.join(present)}): use one of them")
    if not present:
        raise Refusal(f"{source}: {where}: no gap: give 'gap = \"same\"', 'gap_mm' or "
                      f"'gap_px' (this config has no defaults)")
    key = present[0]
    if key == "gap":
        _string(table[key], key, where, source, ("same",))
        return None                    # the width of the row is the gap of the row
    return _width(key, table[key], where, source)


# ─────────────────────────────── the figures ───────────────────────────────

def _figure(table: object, index: int, source: str) -> FigureSpec:
    """One ``[[figure]]``: its kind decides which keys exist at all."""
    where = f"figure #{index}"
    table = _table(table, where, source)
    kind = _required(table, "kind", where, source)
    if type(kind) is not str:
        raise Refusal(f"{source}: {where}: 'kind' must be a string, got {_what(kind)}")
    if kind not in KINDS:
        raise Refusal(f"{source}: {where}: unknown figure kind {kind!r}; the kinds are "
                      f"{', '.join(KINDS)}")
    _keys(table, FIGURE_KEYS[kind], where, source)
    name = f"{kind} #{index}"
    at_mm = _pair(_required(table, "at_mm", where, source), "at_mm", where, source,
                  positive=False)

    if kind == "square":
        size_mm = _pair(_required(table, "size_mm", where, source), "size_mm", where, source)
        line_key, line = _one_of(table, ("line_mm", "line_px"), where, source, "line width")
        return SquareSpec(name=name, at_mm=at_mm, size_mm=size_mm,
                          line=_width(line_key, line, where, source))

    if kind == "grid":
        size_mm = _pair(_required(table, "size_mm", where, source), "size_mm", where, source)
        line_key, line = _one_of(table, ("line_mm", "line_px"), where, source, "line width")
        gap_key, gap = _one_of(table, ("gap_mm", "gap_px"), where, source, "gap")
        return GridSpec(name=name, at_mm=at_mm, size_mm=size_mm,
                        line=_width(line_key, line, where, source),
                        gap=_width(gap_key, gap, where, source),
                        direction=_string(_required(table, "direction", where, source),
                                          "direction", where, source, DIRECTIONS))

    if kind == "bars":
        return BarsSpec(name=name, at_mm=at_mm, widths=_widths(table, where, source),
                        lines=_whole(_required(table, "lines", where, source), "lines",
                                     where, source))

    if kind == "text":
        characters = _required(table, "text", where, source)
        if type(characters) is not str:
            raise Refusal(f"{source}: {where}: 'text' must be a string of characters, got "
                          f"{_what(characters)}")
        _placeholders(characters, where, source)
        return TextSpec(name=name, at_mm=at_mm, text=characters,
                        stroke_px=_whole(_required(table, "stroke_px", where, source),
                                         "stroke_px", where, source))

    return PatchesSpec(
        name=name, at_mm=at_mm,
        patch_mm=_number(_required(table, "patch_mm", where, source), "patch_mm",
                         where, source),
        patch_gap_mm=_number(_required(table, "patch_gap_mm", where, source),
                             "patch_gap_mm", where, source, positive=False),
        widths=_widths(table, where, source),
        gap=_patch_gap(table, where, source),
    )


# ──────────────────────────────── reading ──────────────────────────────────

def _output(data: dict, source: str, base: Path | None) -> PlateOutput:
    """The ``[output]`` table: the printer's file, the optional measurement, the paths.

    Both paths are optional, but not both absent: a config that writes nothing is a
    config that does not say what it is for — and next to ``--config`` there is no ``-o``
    to fall back on.
    """
    table = _table(_required(data, "output", "the top level", source), "the [output] table",
                   source)
    _keys(table, OUTPUT_KEYS, "[output]", source)
    template = _resolve(_text(_required(table, "template", "[output]", source), "template",
                              "[output]", source), base)
    pixel_um = None
    if "pixel_um" in table:
        pixel_um = _pair(table["pixel_um"], "pixel_um", "[output]", source)
    px6s = None
    if "px6s" in table:
        px6s = _resolve(_text(table["px6s"], "px6s", "[output]", source), base)
    png = None
    if "png" in table:
        png = _resolve(_text(table["png"], "png", "[output]", source), base)
    if px6s is None and png is None:
        raise Refusal(f"{source}: [output]: no 'px6s' and no 'png': the config writes "
                      f"nothing (there is no -o to fall back on next to --config)")
    return PlateOutput(template=template, pixel_um=pixel_um, px6s=px6s, png=png)


def parse_plate_config(text: str, *, source: str = "<config>",
                       base: Path | None = None,
                       path: Path | None = None) -> PlateConfig:
    """Read the config text into specs; every refusal is one line that names the place.

    ``base`` is the directory relative paths count from — the config file's own, when the
    text came from a file. With ``base=None`` the paths stay as written, which is what a
    cell about the FORMAT needs.
    """
    data = _loads(text, source)
    _keys(data, ROOT_KEYS, "the top level", source)

    plate = _table(_required(data, "plate", "the top level", source), "the [plate] table",
                   source)
    _keys(plate, PLATE_KEYS, "[plate]", source)
    width_mm = _number(_required(plate, "width_mm", "[plate]", source), "width_mm",
                       "[plate]", source)
    height_mm = _number(_required(plate, "height_mm", "[plate]", source), "height_mm",
                        "[plate]", source)
    exposure_s = None
    if "exposure_s" in plate:
        exposure_s = _number(plate["exposure_s"], "exposure_s", "[plate]", source)
    rotate = _rotation(plate, "[plate]", source)

    output = _output(data, source, base)

    marker_at_mm = None
    if "marker" in data:
        marker = _table(data["marker"], "the [marker] table", source)
        _keys(marker, MARKER_KEYS, "[marker]", source)
        marker_at_mm = _pair(_required(marker, "at_mm", "[marker]", source), "at_mm",
                             "[marker]", source, positive=False)

    # A plate with nothing on it is not a plate: the missing table and the empty array
    # are ONE refusal, worded for the operator, not for the parser.
    if "figure" not in data or data["figure"] == []:
        raise Refusal(f"{source}: no [[figure]]: a plate needs at least one figure")
    raw = data["figure"]
    if type(raw) is not list:
        raise Refusal(f"{source}: 'figure' must be one or more [[figure]] tables, "
                      f"got {_what(raw)}")
    figures = tuple(_figure(table, index, source)
                    for index, table in enumerate(raw, start=1))
    return PlateConfig(width_mm=width_mm, height_mm=height_mm, exposure_s=exposure_s,
                       marker_at_mm=marker_at_mm, figures=figures, output=output, text=text,
                       rotate=rotate, path=path)


def load_plate_config(path: str | Path) -> PlateConfig:
    """Read the file, resolve its paths against ITS directory, check the template exists."""
    target = Path(path)
    text = _read_text(target, "the plate config")
    config = parse_plate_config(text, source=str(target), base=target.parent, path=target)
    _must_exist(config.output.template, "template", "[output]", str(target))
    return config


__all__ = ["BarsSpec", "FIGURE_KEYS", "FigureSpec", "GridSpec", "KINDS", "OUTPUT_KEYS",
           "PLATE_KEYS", "PatchesSpec", "PlateConfig", "PlateOutput", "ROTATIONS",
           "SquareSpec", "TEXT_PLACEHOLDER", "TextSpec", "fill_text", "load_plate_config",
           "parse_plate_config"]
