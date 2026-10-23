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
  square — a CLOSED contour of one line width, side_x by side_y. The side and the line
         are whole pixels of their OWN axis, so on a non-square pixel one millimetre
         request is two pixel counts. The report carries the formulas with this order's
         numbers: pixel_um = measured_mm / n * 1000. The diagonals only check the
         measurement (d1 = d2 expected); there is no skew formula, because the LCD grid
         has no skew.

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

from .masks import UM_PER_MM, WHITE, Figure, Refusal, Screen, _actual, _quantised

DEFAULT_WIDTHS_MM = (0.200, 0.150, 0.100, 0.080, 0.060, 0.050)
DEFAULT_LINES = 5
DEFAULT_GRID_WIDTH_MM = 50.0
DEFAULT_GRID_HEIGHT_MM = 40.0
DEFAULT_GRID_LINE_MM = 0.2
DEFAULT_GRID_GAP_MM = 0.15
DEFAULT_SQUARE_SIDE_MM = 100.0
"""The laser's 150 mm square does not fit: this screen is 122.4 mm high."""
DEFAULT_SQUARE_LINE_MM = 0.2
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

    def fit(extent: int, line: int, gap: int) -> int:
        """Whole lines only: line ``i`` sits at ``i·(line + gap)``, flush with the edge."""
        if line < 1 or extent < line:
            return 0
        return (extent - line) // (line + gap) + 1

    count_x = fit(rect_y, line_y, gap_y) if along_x else 0
    count_y = fit(rect_x, line_x, gap_x) if along_y else 0
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
        "measure both sides with calipers: the square measures the REAL pixel of each axis "
        "(the printer profile is not a spec sheet)",
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
