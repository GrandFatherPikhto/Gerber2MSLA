# gerber2msla/board.py
"""A board's copper → screen pixels: the geometry of a real Gerber layer as a Figure.

THE PIXEL RULE, and the one thing this module exists to get right: a pixel is lit when
its CENTRE is inside the copper. The rows come from `gerber_rows.iter_rows` with the
step of one screen pixel, so row `i` is read at `y0 + (i + 0.5)·pixel_y_mm` — the centre
of its own pixel; an X segment `[a, b)` then lights the pixels whose centres are inside
[x0, y0..]. That is the same "nearest integer" rule the masks follow (`round`), applied
to geometry that is not a rectangle.

THE ONE Y FLIP lives here and nowhere else: `iter_rows` yields rows from the bottom of
the Gerber frame upwards, image rows run from the top of the PNG downwards, so row `i`
becomes image row `height_px - 1 - i`, once, in `build_board`. Without `--mirror` the
picture is then the board seen FROM ABOVE, the way KiCad draws it — for `F_Cu` and for
`B_Cu` alike.

What this module does NOT do, on purpose:

  * placement, the mirror and the polarity of the whole picture — `masks.compose` owns
    them, once, after placement (one path for one figure and for a plate);
  * the marker — the CLI decides whether a `2 mm` letter F fits on the workpiece;
  * any knowledge of the printer file — the caller writes the `Figure` with `masks` or
    with the П2 writer.

FRAME: `--outline Edge_Cuts.gbr` makes the frame the outline's bounding box, and that is
the only way the top and the bottom of one board land in the SAME frame; without it the
frame is the copper's own box and the report warns that two layers will not line up.

HOLES: `--drill FILE` (several allowed) subtracts every hole as a circle of the diameter
the file states — BLACK, AFTER the copper, so a pad with a hole keeps its ring. Without
`--drill` the figure is a tenting mask.

Messages are ASCII English ("um", not "µm"): the report also travels into the PNG chunk.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Sequence

import numpy as np

from .gerber_rows import iter_rows, row_count
from .gerber_source import Hole, load_drill, load_layer
from .masks import WHITE, Figure, Refusal, Screen, _quantised

BBox = tuple[float, float, float, float]

SMALL_HOLE_PX = 2.0
"""A hole narrower than this many pixels is announced: development may close it."""


# ───────────────────────────── frame and sampling ──────────────────────────

def _frame(copper_box: BBox, outline: str | Path | None) -> tuple[BBox, str, tuple[str, ...]]:
    """The box the picture covers, where it came from, and the warning if it came from copper.

    The frame is ONE box for the copper AND the holes: taking each of them by its own
    bounding box would put a drill file and a copper layer in different frames, and two
    layers of one board would never be aligned.
    """
    if outline is None:
        return (copper_box, "the copper's own bounding box (no --outline)",
                ("warning: no --outline: the frame is the copper's own bounding box, so two "
                 "layers of one board will NOT share a frame — pass the Edge_Cuts file",))
    # An outline with no objects never reaches this line: `load_layer` refuses a Gerber
    # without objects (its `bounding_box()` is None, and a file that draws nothing is not
    # a frame). So there is exactly ONE refusal for "nothing to take the frame from".
    edge = load_layer(outline)
    return edge.bbox, f"the outline {Path(outline).name}", ()


def _pixel_span(start_mm: float, stop_mm: float, origin_mm: float,
                pitch_mm: float, width_px: int) -> tuple[int, int]:
    """Whole pixels whose CENTRE lies in ``[start, stop)`` — half-open, one axis.

    A centre sits at ``origin + (j + 0.5)·pitch``, so the half-open segment maps to the
    half-open range ``[ceil((start-origin)/pitch - 0.5), ceil((stop-origin)/pitch - 0.5))``.
    Clipped to the picture; the caller never sees a negative index.
    """
    first = math.ceil((start_mm - origin_mm) / pitch_mm - 0.5)
    last = math.ceil((stop_mm - origin_mm) / pitch_mm - 0.5)
    return max(first, 0), min(last, width_px)


def _pixel_span_closed(low_mm: float, high_mm: float, origin_mm: float,
                       pitch_mm: float, width_px: int) -> tuple[int, int]:
    """``[first, last + 1)`` for a CLOSED interval — a hole's chord, edges included.

    A drill hit is a circle the file states by its diameter, so a pixel whose centre
    lands exactly on the rim is inside the hole; for copper the edge belongs to the
    segment's end and the rule stays half-open. Hence ``floor`` on the right end here
    and ``ceil`` in :func:`_pixel_span` — one pixel of difference, and the pixel a
    diameter too wide is exactly the "radius = diameter" defect this must not have.
    """
    first = math.ceil((low_mm - origin_mm) / pitch_mm - 0.5)
    last = math.floor((high_mm - origin_mm) / pitch_mm - 0.5)
    return max(first, 0), min(last + 1, width_px)


# ───────────────────────────────── holes ───────────────────────────────────

def _pour_holes(pixels: np.ndarray, holes: Sequence[Hole], screen: Screen,
                box: BBox) -> int:
    """Set every hole BLACK, after the copper; returns how many holes touched a pixel.

    The circle is sampled the same way as the copper: a pixel belongs to the hole when
    its CENTRE is inside the circle. Rows are taken through the row grid, each row's
    chord is the exact half-width ``sqrt(r² - dy²)``, so a hole cannot come out as a
    square and its diameter is the file's.
    """
    height_px, width_px = int(pixels.shape[0]), int(pixels.shape[1])
    pixel_x_mm, pixel_y_mm = screen.pixel_x_mm, screen.pixel_y_mm
    drawn = 0
    for hole in holes:
        radius = hole.diameter_mm / 2.0
        first_row = math.ceil((hole.y_mm - radius - box[1]) / pixel_y_mm - 0.5)
        last_row = math.floor((hole.y_mm + radius - box[1]) / pixel_y_mm - 0.5)
        touched = False
        for row_index in range(max(first_row, 0), min(last_row, height_px - 1) + 1):
            centre_y = box[1] + (row_index + 0.5) * pixel_y_mm
            dy = centre_y - hole.y_mm
            half = math.sqrt(max(radius * radius - dy * dy, 0.0))
            first, last = _pixel_span_closed(hole.x_mm - half, hole.x_mm + half,
                                             box[0], pixel_x_mm, width_px)
            if last <= first:
                continue
            pixels[height_px - 1 - row_index, first:last] = 0
            touched = True
        if touched:
            drawn += 1
    return drawn


# ───────────────────────────────── the board ───────────────────────────────

def build_board(screen: Screen, copper: str | Path, *,
                drills: Sequence[str | Path] = (),
                outline: str | Path | None = None) -> Figure:
    """Read a copper layer (and holes, and an outline) as pixels of the screen.

    The result is a `Figure` like the ones `bars` and `grid` build, so the placement,
    the mirror, the polarity swap and the PNG travel the ONE path of `masks.compose`.
    """
    # `load_layer` already refuses a Gerber with no objects, so the frame below always
    # exists: the "empty layer" refusal is the reader's one, and it names the file.
    layer = load_layer(copper)
    box, frame_source, warnings = _frame(layer.bbox, outline)

    width_px = _quantised(box[2] - box[0], screen.pixel_x_mm, "X", "the board width")
    # The Y count comes from the row grid's own owner: `iter_rows` yields exactly this
    # many rows, and a second rounding of the same expression could disagree with it.
    height_px = row_count(box[3] - box[1], screen.pixel_y_mm)
    if height_px < 1:
        raise Refusal(f"the board is {box[3] - box[1]:.3f} mm tall, below one "
                      f"{screen.pixel_y_um:.1f} um pixel along Y")
    if width_px > screen.width_px or height_px > screen.height_px:
        raise Refusal(
            f"the board is {width_px} x {height_px} px ({box[2] - box[0]:.3f} x "
            f"{box[3] - box[1]:.3f} mm) at {screen.pixel_x_um:.1f} x {screen.pixel_y_um:.1f} um "
            f"and does not fit the {screen.width_px} x {screen.height_px} px screen")

    pixels = np.zeros((height_px, width_px), dtype=np.uint8)
    rows = 0
    for index, row in enumerate(iter_rows(layer.shapes, box, screen.pixel_y_mm)):
        # THE ONE Y FLIP: row 0 is the BOTTOM of the board, image row 0 is its TOP.
        image_row = height_px - 1 - index
        rows += 1
        for start_mm, stop_mm in row.segments:
            first, last = _pixel_span(start_mm, stop_mm, box[0], screen.pixel_x_mm, width_px)
            if last > first:
                pixels[image_row, first:last] = WHITE

    holes: list[Hole] = []
    drill_lines: list[str] = []
    for path in drills:
        found = load_drill(path)
        # An empty drill file is legal (KiCad writes an empty NPTH.drl when nothing is
        # plated through), and the operator has to SEE which file gave nothing: a silent
        # zero looks exactly like a file that was never read.
        counted = f"{len(found)} hole" + ("" if len(found) == 1 else "s")
        drill_lines.append(f"{Path(path).name}: {counted}"
                           + ("" if found else " (the file has none)"))
        holes.extend(found)
    drawn = _pour_holes(pixels, holes, screen, box) if holes else 0

    small = [hole for hole in holes
             if hole.diameter_mm / min(screen.pixel_x_mm, screen.pixel_y_mm) < SMALL_HOLE_PX]
    if small:
        narrowest = min(small, key=lambda hole: hole.diameter_mm)
        warnings = (*warnings,
                    f"warning: {len(small)} of {len(holes)} hole(s) are under "
                    f"{SMALL_HOLE_PX:.0f} px across, the narrowest {narrowest.diameter_mm:.3f} mm "
                    f"= {narrowest.diameter_mm / min(screen.pixel_x_mm, screen.pixel_y_mm):.1f} px: "
                    f"development may close them")

    white_px = int(np.count_nonzero(pixels))
    copper_w_mm, copper_h_mm = layer.size_mm
    report = [
        f"copper: {Path(copper).name} — {len(layer.shapes)} objects, "
        f"{copper_w_mm:.3f} x {copper_h_mm:.3f} mm",
        f"frame: {frame_source}, {box[0]:.3f} .. {box[2]:.3f} x {box[1]:.3f} .. "
        f"{box[3]:.3f} mm = {width_px} x {height_px} px at {screen.pixel_x_um:.1f} x "
        f"{screen.pixel_y_um:.1f} um",
        f"sampling: a pixel is lit when its CENTRE is inside the copper; every row is read "
        f"at the centre of its own pixel ({rows} rows)",
        *drill_lines,
        (f"holes: {drawn} of {len(holes)} subtracted AFTER the copper, each a circle of its "
         f"own diameter"
         if holes else "holes: none — a tenting mask (no --drill)"),
        (f"white: {white_px} px of {width_px * height_px} = "
         f"{white_px * screen.pixel_x_mm * screen.pixel_y_mm:.3f} mm2"),
    ]
    return Figure(pixels=pixels, report=(*warnings, *report))
