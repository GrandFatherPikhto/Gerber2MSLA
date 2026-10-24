# gerber2msla/patterns.py
"""Test patterns for an MSLA printer, in exact screen pixels: `bars`, `grid`, `square`.

`bars` and `grid` are COPIED from Gerber2LDI `tools/msla_tests.py` at commit 364fd28
(2026-10-23) — the last commit that touched the mask files and their cells; behaviour is
unchanged, the command line lives in `cli.py`, the drawing layer in `masks.py`. `square` is
NEW (plan `png2px6s`, П5а): the laser's square measures skew and scale through the machine
profile, while a rigid LCD grid has no skew — what it does have is a scale, so the square
measures the REAL pixel of each axis.

PATTERNS (the layout is the label: there is no caption on a mask)

  bars — groups of `--lines` lines, the gap equal to the line width, in the order of
         `--widths-mm`: a horizontal block (lines along X, so the Y resolution shows)
         and a vertical block to its right (lines along Y, the X resolution). Each
         block is SQUARE: a group measures the same physical distance both ways, which
         is what makes two axes comparable.
  grid — a rectangle filled with lines: the first line is flush with the near edge, a
         line is drawn only WHOLE, the leftover at the far edge is a gap, and `both`
         draws the union of the two directions — the same rule as `patterns/grid.py`
         of Gerber2LDI.
  patches — a row per width (plan K1): the LEFT square of a row is filled with stripes
         along X (the Y resolution shows), the RIGHT one with stripes along Y (the X
         resolution), and the gap inside a row equals the gap between the rows. Each
         square is filled under the same rule as `grid`: a stripe is drawn only WHOLE
         and the first is flush with the near edge, so the leftover at the far edge is
         a gap. A stripe is never stretched to fill the side — then the patch would
         measure a width nobody asked for.
  square — a CLOSED contour of one line width, side_x by side_y. The side and the line
         are whole pixels of their OWN axis, so on a non-square pixel one millimetre
         request is two pixel counts. The report carries the formulas with this order's
         numbers: pixel_um = measured_mm / n * 1000. The diagonals only check the
         measurement (d1 = d2 expected); there is no skew formula, because the LCD grid
         has no skew.
  text — a label in the utility's OWN 5 x 7 font (`font5x7.py`, plan Т1): one font dot is
         `stroke_px` x `stroke_px` SCREEN pixels, so the label is the same picture on any
         machine and does not lean on a non-square pixel. A character outside the font is
         a refusal with the character and its place; a space is never put in its stead.

A width may be asked for in MILLIMETRES or in WHOLE PIXELS of the screen (`--widths-px`,
`--line-px`, `--gap-px`, `--side-px`); the two forms exclude each other. The pixel form is
exactly what will be drawn — `n` pixels of EACH axis, so on a non-square pixel one number
is two physical widths — and carries no deviation warning, because there is no millimetre
request to be off from. A millimetre request is drawn at the nearest whole pixel and
announces the difference when it is coarser than 10 %: «0.050 mm along Y is drawn as
34.0 um (-32 %)».

No `gerber2ldi` import: this is a mask tool, not a laser job.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .font5x7 import BLANK, GLYPHS, GLYPH_HEIGHT, GLYPH_WIDTH, LETTER_GAP
from .masks import (MARKER_GAP_MM, UM_PER_MM, WHITE, Figure, Placement, Refusal, Screen,
                    _actual, _quantised, marker_pixels, origin_pixels)

DEFAULT_WIDTHS_MM = (0.200, 0.150, 0.100, 0.080, 0.060, 0.050)
DEFAULT_LINES = 5
DEFAULT_GRID_WIDTH_MM = 50.0
DEFAULT_GRID_HEIGHT_MM = 40.0
DEFAULT_GRID_LINE_MM = 0.2
DEFAULT_GRID_GAP_MM = 0.15
DEFAULT_SQUARE_SIDE_MM = 100.0
"""The laser's 150 mm square does not fit: this screen is 122.4 mm high."""
DEFAULT_SQUARE_LINE_MM = 0.2
PLATE_WIDTH_MM = 70.0
PLATE_HEIGHT_MM = 78.0
"""Denis' blank: 70 mm across the screen (X) by 78 mm down it (Y)."""
PLATE_MARGIN_MM = 2.0
PLATE_GRID_WIDTH_MM = 30.0
PLATE_GRID_HEIGHT_MM = 30.0
"""The single-command grid (50 x 40 mm) does not fit HALF of a 70 x 78 plate."""
BLOCK_GAP_MM = 2.0
"""Physical gap between the horizontal and the vertical block of `bars`, in mm."""
DIRECTIONS = ("both", "x", "y")

DEVIATION_LIMIT = 0.10
"""How far the DRAWN width may sit from the requested one, as a fraction.

A 0.050 mm line on a 34 um pixel comes out 34 um — a third thinner than asked, and the
plate will show it. Ten percent is the point where the operator has to know; below it the
error is finer than what development alone does to an edge. The pixel form has no
millimetre request, so it never deviates.
"""


@dataclass(frozen=True, slots=True)
class Width:
    """A width as the operator asked for it: millimetres, or whole pixels of the screen.

    Both forms end in one pixel count PER AXIS, which is the only thing the drawing knows.
    """

    mm: float | None = None
    px: int | None = None

    @property
    def label(self) -> str:
        return f"{self.px} px" if self.px is not None else f"{self.mm:.3f} mm"


def _width_pixels(request: Width, pitch_mm: float, axis: str, what: str,
                  *, needed: bool = True) -> int:
    """The pixel count of one axis: asked for directly, or the nearest whole pixel."""
    if request.px is not None:
        return request.px
    return _quantised(request.mm, pitch_mm, axis, what, needed=needed)


def _width_part(request: Width, pixels: int, pitch_mm: float, axis: str,
                *, needed: bool = True) -> str:
    """One axis of a width, as it came out; the request label is printed once, outside.

    A pixel request already states its count in the label, so only the REAL size of those
    pixels is added here: «6 px -> 180.0 um along Y, 206.4 um along X».
    """
    if not needed:
        return f"{axis} not used in this direction"
    if request.px is not None:
        return f"{pixels * pitch_mm * UM_PER_MM:.1f} um along {axis}"
    return _actual(pixels, pitch_mm, axis)


def _deviation(request: Width, pixels: int, pitch_mm: float, axis: str) -> str | None:
    """The drawn width against the asked one; only a millimetre request can deviate."""
    if request.px is not None:
        return None
    drawn_mm = pixels * pitch_mm
    deviation = drawn_mm / request.mm - 1.0
    if abs(deviation) <= DEVIATION_LIMIT:
        return None
    return (f"{request.mm:.3f} mm along {axis} is drawn as "
            f"{drawn_mm * UM_PER_MM:.1f} um ({deviation * 100:+.0f} %)")


# ──────────────────────────────── patterns ─────────────────────────────────

def _duplicates(widths: tuple[Width, ...], pixels: list[int], axis: str,
                groups: str) -> list[str]:
    """Requested widths that share one pixel count: identical groups on the plate."""
    by_pixels: dict[int, list[str]] = {}
    for width, count in zip(widths, pixels):
        by_pixels.setdefault(count, []).append(width.label)
    said: list[str] = []
    for count in sorted(by_pixels):
        labels = by_pixels[count]
        if len(labels) > 1:
            listed = ", ".join(labels)
            said.append(f"widths {listed} give the same {count} px along {axis}: "
                        f"the {groups} will be identical")
    return said


def build_bars(screen: Screen, widths: tuple[Width, ...], lines: int) -> Figure:
    """Groups of bars: horizontal block, then the vertical block to its right."""
    along_y = [_width_pixels(width, screen.pixel_y_mm, "Y", "the width") for width in widths]
    along_x = [_width_pixels(width, screen.pixel_x_mm, "X", "the width") for width in widths]

    group_gap_y = max(along_y)          # one largest width, as the plan asks
    group_gap_x = max(along_x)
    heights = [(2 * lines - 1) * count for count in along_y]
    block_height = sum(heights) + (len(widths) - 1) * group_gap_y
    # The block is SQUARE in millimetres: its width in X pixels follows from its height.
    block_width = _quantised(screen.mm_y(block_height), screen.pixel_x_mm, "X",
                             "the horizontal block")
    widths_v = [(2 * lines - 1) * count for count in along_x]
    stack_width = sum(widths_v) + (len(widths) - 1) * group_gap_x
    block_v_height = _quantised(screen.mm_x(stack_width), screen.pixel_y_mm, "Y",
                               "the vertical block")
    block_gap = _quantised(BLOCK_GAP_MM, screen.pixel_x_mm, "X", "the block gap")

    figure = np.zeros((max(block_height, block_v_height),
                       block_width + block_gap + stack_width), dtype=np.uint8)
    y = 0
    for index, height in enumerate(heights):
        for line in range(lines):
            top = y + line * 2 * along_y[index]
            figure[top:top + along_y[index], 0:block_width] = WHITE
        y += height + group_gap_y
    x = block_width + block_gap
    for index, width in enumerate(widths_v):
        for line in range(lines):
            left = x + line * 2 * along_x[index]
            figure[0:block_v_height, left:left + along_x[index]] = WHITE
        x += width + group_gap_x

    report = [
        f"pattern: bars, {lines} lines per group, gap = line width, groups in the order given",
        "layout: horizontal block at the left (lines along X: the Y resolution), vertical "
        f"block to its right (lines along Y: the X resolution), {BLOCK_GAP_MM:.3f} mm between them",
        "each block is square in millimetres, so a group measures the same span both ways",
        "widths (requested -> actual):",
        *(f"  {width.label} -> {_width_part(width, along_y[index], screen.pixel_y_mm, 'Y')}, "
          f"{_width_part(width, along_x[index], screen.pixel_x_mm, 'X')}"
          for index, width in enumerate(widths)),
    ]
    # A warning is part of the report: a mask that lies about its own numbers is worse
    # than no mask, and the file must say so a month later too.
    warnings = (_duplicates(widths, along_y, "Y", "horizontal groups")
                + _duplicates(widths, along_x, "X", "vertical groups")
                + [text for text in (_deviation(width, along_y[index], screen.pixel_y_mm, "Y")
                                     for index, width in enumerate(widths)) if text]
                + [text for text in (_deviation(width, along_x[index], screen.pixel_x_mm, "X")
                                     for index, width in enumerate(widths)) if text])
    return Figure(pixels=figure,
                  report=tuple(report) + tuple(f"warning: {text}" for text in warnings))


def _fit_count(extent: int, line: int, gap: int) -> int:
    """How many WHOLE lines fit: line ``i`` sits at ``i·(line + gap)``, first flush.

    One rule for every filled rectangle of the tool — `grid` and the patches of a plate
    both ask it, so the leftover at the far edge is a gap in both and never a thin line
    of a width nobody asked for.
    """
    if line < 1 or extent < line:
        return 0
    return (extent - line) // (line + gap) + 1


def build_grid(screen: Screen, width_mm: float, height_mm: float, line: Width,
               gap: Width, direction: str) -> Figure:
    """A rectangle filled with lines: first line flush, whole lines only, rest is a gap."""
    along_x = direction in ("both", "x")     # lines along X, stacked in Y
    along_y = direction in ("both", "y")     # lines along Y, stacked in X
    rect_x = _quantised(width_mm, screen.pixel_x_mm, "X", "the rectangle width")
    rect_y = _quantised(height_mm, screen.pixel_y_mm, "Y", "the rectangle height")
    line_x = _width_pixels(line, screen.pixel_x_mm, "X", "the line", needed=along_y)
    gap_x = _width_pixels(gap, screen.pixel_x_mm, "X", "the gap", needed=along_y)
    line_y = _width_pixels(line, screen.pixel_y_mm, "Y", "the line", needed=along_x)
    gap_y = _width_pixels(gap, screen.pixel_y_mm, "Y", "the gap", needed=along_x)

    count_x = _fit_count(rect_y, line_y, gap_y) if along_x else 0
    count_y = _fit_count(rect_x, line_x, gap_x) if along_y else 0
    if along_x and count_x == 0:
        raise Refusal(f"the {screen.mm_y(rect_y):.3f} mm side holds no line "
                      f"{line.label} tall ({line_y} px of {rect_y} px)")
    if along_y and count_y == 0:
        raise Refusal(f"the {screen.mm_x(rect_x):.3f} mm side holds no line "
                      f"{line.label} wide ({line_x} px of {rect_x} px)")

    figure = np.zeros((rect_y, rect_x), dtype=np.uint8)
    for index in range(count_x):
        top = index * (line_y + gap_y)
        figure[top:top + line_y, 0:rect_x] = WHITE
    for index in range(count_y):
        left = index * (line_x + gap_x)
        figure[0:rect_y, left:left + line_x] = WHITE

    report = [
        f"pattern: grid {width_mm:.3f} x {height_mm:.3f} mm, line {line.label}, "
        f"gap {gap.label}, direction {direction}",
        f"rectangle (actual): {rect_x} x {rect_y} px = "
        f"{screen.mm_x(rect_x):.3f} x {screen.mm_y(rect_y):.3f} mm",
        f"line: {line.label} -> "
        f"{_width_part(line, line_x, screen.pixel_x_mm, 'X', needed=along_y)}, "
        f"{_width_part(line, line_y, screen.pixel_y_mm, 'Y', needed=along_x)}",
        f"gap: {gap.label} -> "
        f"{_width_part(gap, gap_x, screen.pixel_x_mm, 'X', needed=along_y)}, "
        f"{_width_part(gap, gap_y, screen.pixel_y_mm, 'Y', needed=along_x)}",
        f"lines: along X {count_x}, along Y {count_y}",
        "the first line is flush with the near edge, a line is drawn only whole, the "
        "leftover at the far edge is a gap",
    ]
    warnings = [text for text in (
        _deviation(line, line_x, screen.pixel_x_mm, "X") if along_y else None,
        _deviation(line, line_y, screen.pixel_y_mm, "Y") if along_x else None,
        _deviation(gap, gap_x, screen.pixel_x_mm, "X") if along_y else None,
        _deviation(gap, gap_y, screen.pixel_y_mm, "Y") if along_x else None,
    ) if text]
    return Figure(pixels=figure,
                  report=tuple(report) + tuple(f"warning: {text}" for text in warnings))


def build_patches(screen: Screen, side_mm: float, widths: tuple[Width, ...],
                  gap: Width | None, patch_gap_mm: float) -> Figure:
    """One S x S patch per width: horizontal square | vertical square, a row per width.

    Rows go top to bottom in the order of the widths, so the plate reads as the config
    does. Inside a row the gap between the two squares and the gap between the rows are
    ONE number (``patch_gap_mm``): the squares are spaced, not glued, and one number is
    one thing to explain to the operator. ``gap`` is the stripe gap of a row: None means
    "the gap IS the stripe width" (the convention of `bars`), otherwise its own width.
    """
    side_x = _quantised(side_mm, screen.pixel_x_mm, "X", "the patch side")
    side_y = _quantised(side_mm, screen.pixel_y_mm, "Y", "the patch side")
    patch_gap_x = _quantised(patch_gap_mm, screen.pixel_x_mm, "X", "the patch gap",
                             needed=False)
    patch_gap_y = _quantised(patch_gap_mm, screen.pixel_y_mm, "Y", "the patch gap",
                             needed=False)

    rows = len(widths)
    figure = np.zeros((rows * side_y + (rows - 1) * patch_gap_y,
                       2 * side_x + patch_gap_x), dtype=np.uint8)
    report = [
        f"pattern: patches, {rows} rows, one per width, the rows in the order given",
        f"patch: {side_x} x {side_y} px = {screen.mm_x(side_x):.3f} x "
        f"{screen.mm_y(side_y):.3f} mm per square, the gap between the squares and "
        f"between the rows {patch_gap_x} x {patch_gap_y} px = "
        f"{screen.mm_x(patch_gap_x):.3f} x {screen.mm_y(patch_gap_y):.3f} mm",
        "layout: the left square of a row holds stripes along X (the Y resolution), the "
        "right one stripes along Y (the X resolution); a stripe is whole and the first is "
        "flush with the near edge, the leftover at the far edge is a gap",
    ]
    along_y: list[int] = []
    along_x: list[int] = []
    for index, width in enumerate(widths):
        stripe_y = _width_pixels(width, screen.pixel_y_mm, "Y", "the stripe")
        stripe_x = _width_pixels(width, screen.pixel_x_mm, "X", "the stripe")
        gap_y = (stripe_y if gap is None
                 else _width_pixels(gap, screen.pixel_y_mm, "Y", "the gap"))
        gap_x = (stripe_x if gap is None
                 else _width_pixels(gap, screen.pixel_x_mm, "X", "the gap"))
        count_y = _fit_count(side_y, stripe_y, gap_y)
        count_x = _fit_count(side_x, stripe_x, gap_x)
        if count_y == 0:
            raise Refusal(f"the {side_mm:.3f} mm patch holds no horizontal stripe "
                          f"{width.label} tall ({stripe_y} px of {side_y} px)")
        if count_x == 0:
            raise Refusal(f"the {side_mm:.3f} mm patch holds no vertical stripe "
                          f"{width.label} wide ({stripe_x} px of {side_x} px)")
        top = index * (side_y + patch_gap_y)
        for number in range(count_y):
            start = top + number * (stripe_y + gap_y)
            figure[start:start + stripe_y, 0:side_x] = WHITE
        left = side_x + patch_gap_x
        for number in range(count_x):
            start = left + number * (stripe_x + gap_x)
            figure[top:top + side_y, start:start + stripe_x] = WHITE
        leftover_y = side_y - (count_y - 1) * (stripe_y + gap_y) - stripe_y
        leftover_x = side_x - (count_x - 1) * (stripe_x + gap_x) - stripe_x
        along_y.append(stripe_y)
        along_x.append(stripe_x)
        report.append(
            f"row {index + 1}: {width.label} -> {stripe_y} px along Y, {stripe_x} px along "
            f"X; horizontal {count_y} stripes of {stripe_y} px, gap {gap_y} px, leftover "
            f"{leftover_y} px; vertical {count_x} stripes of {stripe_x} px, gap {gap_x} px, "
            f"leftover {leftover_x} px")
    warnings = (_duplicates(widths, along_y, "Y", "horizontal patches")
                + _duplicates(widths, along_x, "X", "vertical patches")
                + [text for text in (_deviation(width, along_y[index], screen.pixel_y_mm, "Y")
                                     for index, width in enumerate(widths)) if text]
                + [text for text in (_deviation(width, along_x[index], screen.pixel_x_mm, "X")
                                     for index, width in enumerate(widths)) if text]
                + [text for text in (
                    _deviation(Width(mm=side_mm), side_x, screen.pixel_x_mm, "X"),
                    _deviation(Width(mm=side_mm), side_y, screen.pixel_y_mm, "Y")) if text])
    return Figure(pixels=figure,
                  report=tuple(report) + tuple(f"warning: {text}" for text in warnings))


def build_square(screen: Screen, side_x_mm: float, side_y_mm: float, line: Width) -> Figure:
    """A CLOSED contour: four strokes, side_x by side_y, in whole pixels of each axis.

    The two sides are separate arguments so that the plate frame (plan П5б) can be a
    rectangle with the same rule; the single `square` command passes one value twice.
    """
    n_x = _quantised(side_x_mm, screen.pixel_x_mm, "X", "the square side")
    n_y = _quantised(side_y_mm, screen.pixel_y_mm, "Y", "the square side")
    w_x = _width_pixels(line, screen.pixel_x_mm, "X", "the line")
    w_y = _width_pixels(line, screen.pixel_y_mm, "Y", "the line")
    if n_x <= 2 * w_x or n_y <= 2 * w_y:
        raise Refusal(
            f"the square {side_x_mm:.3f} x {side_y_mm:.3f} mm with a {line.label} line is "
            f"solid, not a contour: {n_x} x {n_y} px with {w_x} x {w_y} px strokes — the "
            f"side must exceed two line widths on EACH axis")

    figure = np.zeros((n_y, n_x), dtype=np.uint8)
    figure[0:w_y, :] = WHITE                  # the near edge, full width
    figure[n_y - w_y:, :] = WHITE             # the far edge
    figure[:, 0:w_x] = WHITE                  # the left edge
    figure[:, n_x - w_x:] = WHITE             # the right edge

    report = [
        f"pattern: square, side {side_x_mm:.3f} x {side_y_mm:.3f} mm, line {line.label}",
        f"drawn: {n_x} x {n_y} px = {screen.mm_x(n_x):.3f} x {screen.mm_y(n_y):.3f} mm, "
        f"strokes {w_x} x {w_y} px",
        "measure both sides with calipers, OUTER edge to outer edge: the drawn side is n px "
        "of the OUTER contour, so the outer edges are what the formula divides (the printer "
        "profile is not a spec sheet)",
        f"pixel_um_x = measured_x_mm / {n_x} * 1000",
        f"pixel_um_y = measured_y_mm / {n_y} * 1000",
        "diagonals: d1 = d2 expected; a difference is a measurement error or the plate "
        "moved during the exposure",
    ]
    warnings = [text for text in (
        _deviation(Width(mm=side_x_mm), n_x, screen.pixel_x_mm, "X"),
        _deviation(Width(mm=side_y_mm), n_y, screen.pixel_y_mm, "Y"),
        _deviation(line, w_x, screen.pixel_x_mm, "X"),
        _deviation(line, w_y, screen.pixel_y_mm, "Y"),
    ) if text]
    return Figure(pixels=figure,
                  report=tuple(report) + tuple(f"warning: {text}" for text in warnings))


# ───────────────────────────── text (plan Т1) ──────────────────────────────

def build_text(screen: Screen, text: str, stroke_px: int) -> Figure:
    """A label in the utility's own 5 x 7 font; one font dot is `stroke_px` screen pixels.

    The dot is a square IN PIXELS, not in millimetres: on a non-square pixel the letters
    keep their shape instead of leaning, and the report says so in words. A character
    outside `font5x7.GLYPHS` is a REFUSAL with the character and its place in the line — a
    space quietly put in its stead would make the label a different label.
    """
    if not text:
        raise Refusal("the label is empty: a 'text' figure needs the characters to draw")
    if stroke_px < 1:
        raise Refusal(f"stroke_px must be at least 1 whole screen pixel, got {stroke_px}")
    for place, character in enumerate(text, start=1):
        if character not in GLYPHS:
            raise Refusal(
                f"character {place} of the label {text!r} is {character!r}, and this font "
                f"has no such glyph: the set is 0-9, A-Z, a-z, space and . , - _ : / ( ) "
                f"+ = % (Latin only)")

    dots = len(text) * (GLYPH_WIDTH + LETTER_GAP) - LETTER_GAP
    width_px = dots * stroke_px
    height_px = GLYPH_HEIGHT * stroke_px
    pixels = np.zeros((height_px, width_px), dtype=np.uint8)
    for place, character in enumerate(text):
        left = place * (GLYPH_WIDTH + LETTER_GAP) * stroke_px
        for row, dots_row in enumerate(GLYPHS[character]):
            for column, dot in enumerate(dots_row):
                if dot != BLANK:
                    x_px = left + column * stroke_px
                    y_px = row * stroke_px
                    pixels[y_px:y_px + stroke_px, x_px:x_px + stroke_px] = WHITE

    white = int(np.count_nonzero(pixels))
    report = [
        f"pattern: text {text!r}, {len(text)} character(s), one font dot = {stroke_px} x "
        f"{stroke_px} px = {stroke_px * screen.pixel_x_um:.1f} x "
        f"{stroke_px * screen.pixel_y_um:.1f} um",
        f"font: {GLYPH_WIDTH} x {GLYPH_HEIGHT} dots per character, {LETTER_GAP} dot between "
        f"letters, drawn by this utility (no TTF: the same picture on every machine)",
        f"drawn: {width_px} x {height_px} px = {screen.mm_x(width_px):.3f} x "
        f"{screen.mm_y(height_px):.3f} mm",
        "a font dot is a square in PIXELS, not in millimetres: on a non-square pixel the "
        "letters keep their shape while their width in um differs per axis",
        f"white: {white} px",
    ]
    return Figure(pixels=pixels, report=tuple(report))


# ───────────────────────────── plate (plan П5б) ────────────────────────────

def _require_inside(name: str, figure: Figure, x_px: int, y_px: int, *,
                    left: int, top: int, right: int, bottom: int,
                    screen: Screen) -> None:
    """A figure must sit inside the frame opening; the plate never shrinks it."""
    if (x_px >= left and y_px >= top
            and x_px + figure.width_px <= right
            and y_px + figure.height_px <= bottom):
        return
    raise Refusal(
        f"the figure {name} {screen.mm_x(figure.width_px):.3f} x "
        f"{screen.mm_y(figure.height_px):.3f} mm ({figure.width_px} x "
        f"{figure.height_px} px) does not fit the plate frame: it would span "
        f"{x_px} ... {x_px + figure.width_px} px across and {y_px} ... "
        f"{y_px + figure.height_px} px down; the room inside the frame is "
        f"{left} ... {right} px across and {top} ... {bottom} px down "
        f"({screen.mm_x(right - left):.3f} x {screen.mm_y(bottom - top):.3f} mm)")


def build_plate(screen: Screen, *, plate_w_mm: float, plate_h_mm: float, margin_mm: float,
                square_line: Width, widths: tuple[Width, ...], lines: int,
                grid_line: Width, grid_gap: Width, grid_width_mm: float,
                grid_height_mm: float, direction: str,
                at_mm: tuple[float, float] | None) -> tuple[tuple[Placement, ...],
                                                           tuple[str, ...]]:
    """One plate: frame, ONE marker, bars on the left half, grid on the right half.

    The layout is FIXED — a mask carries no captions, so the layout IS the label. Figures
    are built by the same rules as the single commands; an overlap or anything outside the
    frame is a refusal with names, millimetres and pixels, never a silent shrink.
    """
    plate_w_px = _quantised(plate_w_mm, screen.pixel_x_mm, "X", "the plate width")
    plate_h_px = _quantised(plate_h_mm, screen.pixel_y_mm, "Y", "the plate height")
    plate_x, plate_y = origin_pixels(screen, plate_w_px, plate_h_px, at_mm)
    margin_x = _quantised(margin_mm, screen.pixel_x_mm, "X", "the margin")
    margin_y = _quantised(margin_mm, screen.pixel_y_mm, "Y", "the margin")
    if plate_w_px <= 2 * margin_x or plate_h_px <= 2 * margin_y:
        raise Refusal(
            f"the plate {plate_w_mm:.3f} x {plate_h_mm:.3f} mm with a {margin_mm:.3f} mm "
            f"margin leaves no room for a frame: {plate_w_px} x {plate_h_px} px plate, "
            f"{margin_x} x {margin_y} px margin on each side")

    frame = build_square(screen, plate_w_mm - 2 * margin_mm, plate_h_mm - 2 * margin_mm,
                         square_line)
    frame_x = plate_x + margin_x
    frame_y = plate_y + margin_y
    w_x = _width_pixels(square_line, screen.pixel_x_mm, "X", "the frame line")
    w_y = _width_pixels(square_line, screen.pixel_y_mm, "Y", "the frame line")
    inner_left = frame_x + w_x
    inner_top = frame_y + w_y
    inner_right = frame_x + frame.width_px - w_x
    inner_bottom = frame_y + frame.height_px - w_y
    gap_x = _quantised(MARKER_GAP_MM, screen.pixel_x_mm, "X", "the figure gap")
    gap_y = _quantised(MARKER_GAP_MM, screen.pixel_y_mm, "Y", "the figure gap")
    room_left = inner_left + gap_x
    room_top = inner_top + gap_y
    room_right = inner_right - gap_x
    room_bottom = inner_bottom - gap_y
    half_w = (room_right - room_left - gap_x) // 2
    if half_w < 1:
        raise Refusal(
            f"the plate leaves no room for two halves: {room_right - room_left} px between "
            f"the frame and the {gap_x} px gaps is too narrow for bars and grid")

    marker = Figure(pixels=marker_pixels(screen), report=())
    bars = build_bars(screen, widths, lines)
    grid = build_grid(screen, grid_width_mm, grid_height_mm, grid_line, grid_gap, direction)

    bars_x = room_left
    bars_y = room_top + marker.height_px + gap_y
    grid_x = room_left + half_w + gap_x
    grid_y = room_top
    _require_inside("bars", bars, bars_x, bars_y, left=room_left, top=room_top,
                    right=room_right, bottom=room_bottom, screen=screen)
    _require_inside("grid", grid, grid_x, grid_y, left=room_left, top=room_top,
                    right=room_right, bottom=room_bottom, screen=screen)

    report = [
        f"plate: {plate_w_mm:.3f} x {plate_h_mm:.3f} mm ({plate_w_px} x {plate_h_px} px), "
        f"margin {margin_mm:.3f} mm = {margin_x} x {margin_y} px",
        f"frame: {frame.width_px} x {frame.height_px} px = "
        f"{screen.mm_x(frame.width_px):.3f} x {screen.mm_y(frame.height_px):.3f} mm, "
        f"line {square_line.label}",
        f"inside the frame: {inner_right - inner_left} x {inner_bottom - inner_top} px = "
        f"{screen.mm_x(inner_right - inner_left):.3f} x "
        f"{screen.mm_y(inner_bottom - inner_top):.3f} mm; figures keep "
        f"{gap_x} x {gap_y} px = {screen.mm_x(gap_x):.3f} x {screen.mm_y(gap_y):.3f} mm "
        f"from the frame and from each other",
        "layout: marker top-left, bars in the left half, grid in the right half — the "
        "layout IS the label (a mask has no captions)",
        f"halves: the left half is {half_w} px = {screen.mm_x(half_w):.3f} mm wide",
        f"grid on a plate: {grid_width_mm:.3f} x {grid_height_mm:.3f} mm "
        f"(the plate default is {PLATE_GRID_WIDTH_MM:g} x {PLATE_GRID_HEIGHT_MM:g} mm, not "
        f"the single-command {DEFAULT_GRID_WIDTH_MM:g} x {DEFAULT_GRID_HEIGHT_MM:g} mm: "
        f"that one does not fit the {half_w} px half)",
        f"marker: ONE letter F inside the frame, top-left, {marker.width_px} x "
        f"{marker.height_px} px = {screen.mm_x(marker.width_px):.3f} x "
        f"{screen.mm_y(marker.height_px):.3f} mm",
        *frame.report,
        *bars.report,
        *grid.report,
    ]
    placements = (
        Placement(frame, frame_x, frame_y, name="frame"),
        Placement(marker, room_left, room_top, name="marker"),
        Placement(bars, bars_x, bars_y, name="bars"),
        Placement(grid, grid_x, grid_y, name="grid"),
    )
    return placements, tuple(report)
