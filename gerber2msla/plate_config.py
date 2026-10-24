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
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from .masks import Refusal
from .patterns import DIRECTIONS, Width

KINDS = ("bars", "grid", "patches", "square")
"""Every figure kind the config may ask for; anything else is a refusal, not a guess."""

FIGURE_KEYS: dict[str, tuple[str, ...]] = {
    "bars": ("at_mm", "kind", "lines", "widths_mm", "widths_px"),
    "grid": ("at_mm", "direction", "gap_mm", "gap_px", "kind", "line_mm", "line_px",
             "size_mm"),
    "patches": ("at_mm", "gap", "gap_mm", "gap_px", "kind", "patch_gap_mm", "patch_mm",
                "widths_mm", "widths_px"),
    "square": ("at_mm", "kind", "line_mm", "line_px", "size_mm"),
}
"""The keys of each kind, sorted: this table IS the strictness of a figure.

The refusal that names an unknown key reads this very table, so a new key cannot be
added to the reader and forgotten in the message, or the other way round.
"""

PLATE_KEYS = ("exposure_s", "height_mm", "width_mm")
MARKER_KEYS = ("at_mm",)
ROOT_KEYS = ("figure", "marker", "plate")
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


FigureSpec = SquareSpec | GridSpec | BarsSpec | PatchesSpec


@dataclass(frozen=True, slots=True)
class PlateConfig:
    """A config read and checked: no pixels yet, only what the operator asked for."""

    width_mm: float
    height_mm: float
    exposure_s: float | None
    marker_at_mm: tuple[float, float] | None
    figures: tuple[FigureSpec, ...]
    text: str
    """The file as it was read: it goes into the PNG chunk whole, UTF-8 (plan K2)."""
    path: Path | None = None

    @property
    def label(self) -> str:
        return "<config>" if self.path is None else str(self.path)


# ───────────────────────────── refusal wording ─────────────────────────────

def _what(value: object) -> str:
    """What was found, in the operator's terms: a table, an array, the number 6.0..."""
    if isinstance(value, bool):
        return f"a boolean ({value!r})"
    if isinstance(value, (int, float)):
        return f"the number {value!r}"
    if isinstance(value, str):
        return f"a string ({value!r})"
    if isinstance(value, list):
        return f"an array of {len(value)} item(s)"
    if isinstance(value, dict):
        return "a table"
    return type(value).__name__


def _noun(count: int) -> str:
    return "key" if count == 1 else "keys"


def _table(value: object, where: str, source: str) -> dict:
    if type(value) is not dict:
        raise Refusal(f"{source}: {where} must be a table, got {_what(value)}")
    return value


def _keys(table: dict, allowed: tuple[str, ...], where: str, source: str) -> None:
    """Strictness, first half: a key that does not belong here is refused BY NAME."""
    unknown = sorted(set(table) - set(allowed))
    if unknown:
        listed = ", ".join(f"'{key}'" for key in unknown)
        raise Refusal(f"{source}: {where}: unknown {_noun(len(unknown))} {listed}; "
                      f"the known keys are {', '.join(allowed)}")


def _required(table: dict, key: str, where: str, source: str):
    """Strictness, second half: no key means no value — there are no defaults here."""
    if key not in table:
        raise Refusal(f"{source}: {where}: no '{key}': this config has no defaults, "
                      f"every key a figure needs must be in the file")
    return table[key]


def _number(value: object, key: str, where: str, source: str, *,
            positive: bool = True) -> float:
    """A millimetre-like number; ``int`` is fine (``width_mm = 70``), ``bool`` is not.

    ``True`` is an ``int`` in Python, so the type is compared by identity: a
    ``height_mm = true`` from the file is a refusal and never a plate 1 mm high.
    """
    if type(value) not in (int, float):
        raise Refusal(f"{source}: {where}: '{key}' must be a number, got {_what(value)}")
    number = float(value)
    if not math.isfinite(number):
        raise Refusal(f"{source}: {where}: '{key}' must be finite, got {value!r}")
    if positive and number <= 0.0:
        raise Refusal(f"{source}: {where}: '{key}' must be positive, got {value!r}")
    if not positive and number < 0.0:
        raise Refusal(f"{source}: {where}: '{key}' must not be negative, got {value!r}")
    return number


def _whole(value: object, key: str, where: str, source: str, *, minimum: int = 1) -> int:
    """A whole pixel count: ``6`` yes, ``6.0`` no — a count of pixels has no fraction."""
    if type(value) is not int:
        raise Refusal(f"{source}: {where}: '{key}' must be a whole number of pixels, "
                      f"got {_what(value)}")
    if value < minimum:
        raise Refusal(f"{source}: {where}: '{key}' must be at least {minimum}, got {value}")
    return value


def _pair(value: object, key: str, where: str, source: str, *,
          positive: bool = True) -> tuple[float, float]:
    """Two numbers: ``at_mm`` and ``size_mm``. Three is as wrong as one."""
    if type(value) is not list:
        raise Refusal(f"{source}: {where}: '{key}' must be an array of two numbers, "
                      f"got {_what(value)}")
    if len(value) != 2:
        raise Refusal(f"{source}: {where}: '{key}' must hold exactly two numbers, "
                      f"got {len(value)}")
    return (_number(value[0], f"{key}[0]", where, source, positive=positive),
            _number(value[1], f"{key}[1]", where, source, positive=positive))


def _string(value: object, key: str, where: str, source: str,
            choices: tuple[str, ...]) -> str:
    if type(value) is not str:
        raise Refusal(f"{source}: {where}: '{key}' must be a string, got {_what(value)}")
    if value not in choices:
        raise Refusal(f"{source}: {where}: '{key}' must be one of "
                      f"{', '.join(repr(choice) for choice in choices)}, got {value!r}")
    return value


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

def _syntax_line(exc: tomllib.TOMLDecodeError) -> int:
    """The line the TOML parser stopped on: an attribute on 3.14, the text before it.

    Both paths are kept on purpose: the attribute is the honest one, the regex is what
    the older minor versions have, and the project's floor is 3.11 — a refusal with the
    line number must not depend on which machine's Python read the file.
    """
    line = getattr(exc, "lineno", None)
    if isinstance(line, int) and line > 0:
        return line
    found = re.search(r"line (\d+)", str(exc))
    return int(found.group(1)) if found else 0


def parse_plate_config(text: str, *, source: str = "<config>",
                       path: Path | None = None) -> PlateConfig:
    """Read the config text into specs; every refusal is one line that names the place."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        message = getattr(exc, "msg", None) or str(exc)
        line = _syntax_line(exc)
        where = f"line {line}" if line else "a TOML syntax error"
        raise Refusal(f"{source}: {where}: {message}") from None

    data = _table(data, "the whole file", source)
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
                       marker_at_mm=marker_at_mm, figures=figures, text=text, path=path)


def load_plate_config(path: str | Path) -> PlateConfig:
    """Read the file as UTF-8 and parse it; a missing file is a refusal, not a trace."""
    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise Refusal(f"cannot read the plate config {target}: {exc}") from None
    except UnicodeDecodeError as exc:
        raise Refusal(f"the plate config {target} is not UTF-8: {exc}") from None
    return parse_plate_config(text, source=str(target), path=target)


__all__ = ["BarsSpec", "FIGURE_KEYS", "FigureSpec", "GridSpec", "KINDS", "PatchesSpec",
           "PlateConfig", "SquareSpec", "load_plate_config", "parse_plate_config"]
