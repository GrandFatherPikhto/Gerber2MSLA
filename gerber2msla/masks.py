# gerber2msla/masks.py
"""Drawing layer of the MSLA test masks: screen pixels, the marker, placement, the PNG.

The drawing layer came from Gerber2LDI `tools/msla_masks.py` (commit 364fd28, 2026-10-23);
since П5б placement is a LIST of figures with pixel positions — one path for a single
pattern and for a plate of several (plan `png2px6s`). One marker, one mirror and one
polarity swap are applied to the WHOLE picture in `compose`; an overlap or a figure off
the screen is a refusal that names the figures, in millimetres and pixels.

THE PIXEL RULE: `n = round(size / pitch)` pixels of THAT axis. `n = 0` is a refusal — a
line thinner than a pixel does not exist — and rounding, not truncation, keeps a drawn
line at the nearest pixel edge instead of making every dimension thinner than asked.

`patterns.py` imports `_quantised` and `_actual` on purpose: the modules are ONE tool, and
the leading underscore means "not for the operator", not "not for the other half". Nothing
here knows what a test pattern is.

Standard library + `numpy` + `Pillow` only. Messages are ASCII English ("um", not "µm")
because they also travel into the PNG text chunk.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
from PIL import Image, PngImagePlugin

WHITE = 255
UM_PER_MM = 1000.0
REPORT_KEY = "msla_tests"

MARKER_MM = 2.0
"""Side of the marker square in millimetres. Its pixel count follows each axis."""
MARKER_LINE_PX = 3
"""Stem and arm width of the marker in PIXELS: below ~100 um a line disappears in development."""
MARKER_GAP_MM = 1.0
"""Gap between the marker and the pattern, in millimetres — they must not touch."""


class Refusal(Exception):
    """The operator asked for something that cannot be drawn; the message says why."""


@dataclass(frozen=True, slots=True)
class Screen:
    """The LCD in pixels, and the size of ONE pixel on each axis in micrometres."""

    width_px: int
    height_px: int
    pixel_x_um: float
    pixel_y_um: float

    @property
    def pixel_x_mm(self) -> float:
        return self.pixel_x_um / UM_PER_MM

    @property
    def pixel_y_mm(self) -> float:
        return self.pixel_y_um / UM_PER_MM

    def mm_x(self, pixels: int) -> float:
        return pixels * self.pixel_x_mm

    def mm_y(self, pixels: int) -> float:
        return pixels * self.pixel_y_mm


@dataclass(frozen=True, slots=True)
class Figure:
    """A drawing in its own pixels, plus the report lines that belong to it."""

    pixels: np.ndarray
    report: tuple[str, ...]

    @property
    def width_px(self) -> int:
        return int(self.pixels.shape[1])

    @property
    def height_px(self) -> int:
        return int(self.pixels.shape[0])


@dataclass(frozen=True, slots=True)
class Placement:
    """One figure and the pixel of the screen its top-left corner lands on.

    ``name`` is None for the single pattern of a mask command (the report then says
    "figure: ..."), and the figure's name on a plate ("figure bars: ...").
    """

    figure: Figure
    x_px: int
    y_px: int
    name: str | None = None
    at_mm: tuple[float, float] | None = None


# ───────────────────────────── pixel binding ───────────────────────────────

def _quantised(size_mm: float, pitch_mm: float, axis: str, what: str,
               *, needed: bool = True) -> int:
    """A size in WHOLE pixels of one axis; ``needed`` and zero is a refusal.

    Rounding, not truncation: `round` is the nearest pixel edge, `int` would bias every
    dimension downwards and make a 0.06 mm line thinner than asked on both axes.
    """
    pixels = int(round(size_mm / pitch_mm))
    if needed and pixels < 1:
        raise Refusal(f"{what} {size_mm:.3f} mm is below one "
                      f"{pitch_mm * UM_PER_MM:.1f} um pixel along {axis}")
    return pixels


def _actual(pixels: int, pitch_mm: float, axis: str, *, needed: bool = True) -> str:
    """One axis of a request, as it came out: pixels and their real size in micrometres."""
    if not needed:
        return f"{axis} not used in this direction"
    return f"{pixels} px along {axis} = {pixels * pitch_mm * UM_PER_MM:.1f} um"


# ───────────────────────────────── marker ──────────────────────────────────

def marker_pixels(screen: Screen) -> np.ndarray:
    """The letter F in whole pixels: stem on the left, arms to the top-right.

    Asymmetric in BOTH axes on purpose — that is the whole point of it: a mirrored
    exposure puts the stem on the right, an upside-down one puts the arms at the bottom,
    and both are read off the developed plate by eye, without a microscope.
    """
    width = _quantised(MARKER_MM, screen.pixel_x_mm, "X", "the marker side")
    height = _quantised(MARKER_MM, screen.pixel_y_mm, "Y", "the marker side")
    if width < 3 * MARKER_LINE_PX or height < 2 * MARKER_LINE_PX:
        raise Refusal(
            f"the pixel is too coarse for the marker: a {MARKER_MM:.1f} mm side is "
            f"{width} x {height} px, the F needs {3 * MARKER_LINE_PX} px across and "
            f"{2 * MARKER_LINE_PX} px down of {MARKER_LINE_PX} px lines (use --no-marker)")
    pixels = np.zeros((height, width), dtype=np.uint8)
    pixels[:, 0:MARKER_LINE_PX] = WHITE                     # the stem
    pixels[0:MARKER_LINE_PX, 0:width] = WHITE               # the top arm, full length
    middle = height // 2
    arm = max(MARKER_LINE_PX, width * 7 // 10)              # the middle arm, shorter
    pixels[middle:middle + MARKER_LINE_PX, 0:arm] = WHITE
    return pixels


def add_marker(screen: Screen, figure: Figure) -> Figure:
    """Put the F at the top-left corner of the figure; the pattern moves right of it.

    The pattern keeps its own geometry — same rows, same blocks, same widths — it only
    moves. A marker drawn ON the pattern would corrupt exactly what the pattern measures.
    """
    marker = marker_pixels(screen)
    marker_height, marker_width = int(marker.shape[0]), int(marker.shape[1])
    gap = _quantised(MARKER_GAP_MM, screen.pixel_x_mm, "X", "the marker gap")
    pixels = np.zeros((max(figure.height_px, marker_height),
                       marker_width + gap + figure.width_px), dtype=np.uint8)
    pixels[0:marker_height, 0:marker_width] = marker
    pixels[0:figure.height_px, marker_width + gap:] = figure.pixels
    report = figure.report + (
        f"marker: the letter F in the top-left corner of the figure, {marker_width} x "
        f"{marker_height} px = {screen.mm_x(marker_width):.3f} x "
        f"{screen.mm_y(marker_height):.3f} mm, line {MARKER_LINE_PX} px; the pattern "
        f"starts {gap} px = {screen.mm_x(gap):.3f} mm to its right",
        "marker: on a straight exposure the stem is on the LEFT and the arms point to the "
        "top-right; a mirrored one puts the stem on the RIGHT, an upside-down one puts the "
        "arms at the bottom",
    )
    return Figure(pixels=pixels, report=report)


# ──────────────────────────── placement and output ─────────────────────────

def origin_pixels(screen: Screen, width_px: int, height_px: int,
                  at_mm: tuple[float, float] | None) -> tuple[int, int]:
    """Top-left pixel of a ``width_px`` x ``height_px`` box: centred, or at ``at_mm``."""
    if at_mm is None:
        return ((screen.width_px - width_px) // 2,
                (screen.height_px - height_px) // 2)
    return (int(round(at_mm[0] / screen.pixel_x_mm)),
            int(round(at_mm[1] / screen.pixel_y_mm)))


def place_figure(screen: Screen, figure: Figure, at_mm: tuple[float, float] | None,
                 *, name: str | None = None) -> Placement:
    """One placement for one figure; a single mask command uses exactly this."""
    x_px, y_px = origin_pixels(screen, figure.width_px, figure.height_px, at_mm)
    return Placement(figure=figure, x_px=x_px, y_px=y_px, name=name, at_mm=at_mm)


def _label(placement: Placement) -> str:
    """``figure`` for the single unnamed pattern, ``figure <name>`` for one of many."""
    return "figure" if placement.name is None else f"figure {placement.name}"


def _where(placement: Placement, screen: Screen) -> str:
    """Where the figure was put, in the operator's terms.

    A single pattern may be centred; a named figure of a plate always has an explicit
    corner, and that corner is quoted in millimetres and pixels.
    """
    if placement.at_mm is not None:
        return (f"at {placement.at_mm[0]:.3f}, {placement.at_mm[1]:.3f} mm "
                f"from the top-left pixel")
    if placement.name is None:
        return "centred"
    return (f"at {screen.mm_x(placement.x_px):.3f}, {screen.mm_y(placement.y_px):.3f} mm "
            f"from the top-left pixel")


def compose(screen: Screen, placements: Sequence[Placement], *,
            mirror: bool, invert: bool) -> tuple[np.ndarray, tuple[str, ...]]:
    """Paste every figure, then mirror and invert the WHOLE picture.

    One path for one figure and for a plate of several: an unnamed placement is the single
    pattern, a named one is a figure of the plate. A clash is a refusal — the plate never
    shrinks a figure silently to make it fit.
    """
    image = np.zeros((screen.height_px, screen.width_px), dtype=np.uint8)
    owner = np.full((screen.height_px, screen.width_px), -1, dtype=np.int32)
    lines: list[str] = []
    for index, placement in enumerate(placements):
        figure = placement.figure
        x_px, y_px = placement.x_px, placement.y_px
        width_px, height_px = figure.width_px, figure.height_px
        if not (0 <= x_px and 0 <= y_px
                and x_px + width_px <= screen.width_px
                and y_px + height_px <= screen.height_px):
            raise Refusal(
                f"the {_label(placement)} {screen.mm_x(width_px):.3f} x "
                f"{screen.mm_y(height_px):.3f} mm ({width_px} x {height_px} px) does not fit "
                f"the {screen.width_px} x {screen.height_px} px screen "
                f"{_where(placement, screen)}: it would span {x_px} ... {x_px + width_px} px across "
                f"and {y_px} ... {y_px + height_px} px down")

        painted = figure.pixels > 0
        taken = owner[y_px:y_px + height_px, x_px:x_px + width_px]
        clash = taken[painted] >= 0
        if clash.any():
            other = placements[int(taken[painted][0])]
            raise Refusal(
                f"{_label(placement)} at {x_px}, {y_px} px "
                f"({screen.mm_x(x_px):.3f}, {screen.mm_y(y_px):.3f} mm) and "
                f"{_label(other)} at {other.x_px}, {other.y_px} px "
                f"({screen.mm_x(other.x_px):.3f}, {screen.mm_y(other.y_px):.3f} mm) "
                f"overlap: both paint the same pixels. The plate does not shrink a figure "
                f"to make it fit — move it or make it smaller")
        taken[painted] = index
        region = image[y_px:y_px + height_px, x_px:x_px + width_px]
        region[:] = np.maximum(region, figure.pixels)
        lines.append(
            f"{_label(placement)}: {screen.mm_x(width_px):.3f} x "
            f"{screen.mm_y(height_px):.3f} mm ({width_px} x {height_px} px), "
            f"{_where(placement, screen)} ({x_px}, {y_px} px)")

    if mirror:
        image = np.fliplr(image)
        lines.append("mirror: on (the whole picture is reflected along X; a figure at x px "
                     "of the plate is at width - 1 - x on it)")
    else:
        lines.append("mirror: off")
    if invert:
        image = WHITE - image
        lines.append("polarity: white = the gaps (inverted: the resist keeps what was NOT lit)")
    else:
        lines.append("polarity: white = the lines (a negative resist keeps what was lit)")
    return image, tuple(lines)


def write_mask(path: str | Path, screen: Screen, report: Sequence[str],
               image: np.ndarray) -> Path:
    """Write the PNG (mode L, exactly the screen) with the report in a text chunk."""
    text = (
        "msla_tests: a test mask for an MSLA printer",
        f"screen: {screen.width_px} x {screen.height_px} px",
        f"pixel: {screen.pixel_x_um:.2f} x {screen.pixel_y_um:.2f} um",
        *report,
    )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    info = PngImagePlugin.PngInfo()
    info.add_text(REPORT_KEY, "\n".join(text))
    Image.fromarray(image, mode="L").save(target, format="PNG", pnginfo=info)
    return target
