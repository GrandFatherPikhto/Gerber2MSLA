# gerber2msla/gerber_rows.py
"""Rasterisation by GEOMETRY: one image row at a time, on/off segments in mm.

COPIED from Gerber2LDI at commit 3c77f9f35c3cd9c55c3046f91fd8f7034d09898d
(2026-10-21), the last commit that touched them:

  * `gerber2ldi/scan/row.py` (88 lines) — `Segment`, `normalize`, `ScanRow`;
  * the `union` and `subtract` of `gerber2ldi/scan/ops.py` (138 lines);
  * `gerber2ldi/raster/rows.py` (105 lines) — `ROW_CENTRE`, `row_y`, `row_count`,
    `_crossings`, `polygon_intervals`, `row_segments`, `iter_rows`.

What the copy dropped, and WHY:

  * `iter_rows`'s `y_scale` — the laser's Y calibration. There is no laser here:
    the printer exposes a whole layer at once, so the geometry is used as drawn;
  * `intersect`, `shift`, `mirror`, `invert`, `shrink`, `scale` and the whole of
    `scan/skew.py` / `scan/compensate.py` — spot compensation, axis calibration and
    scan-line polarity, all of them laser-job steps. Whole-picture mirror and
    polarity belong to `masks.compose` here, applied once, after placement;
  * `GRID_TOLERANCE_MM`, `apply_skew`, `compensate` came with those modules.

Nothing else changed: the row invariant, the row height rule, the crossing rule and
the polarity sequence are the original's, line for line. The cells came with the
code — `tests/test_gerber_rows.py`, bodies compared by AST
(`diagnostics/accept_g0_ast_2026_10_24.py`).

Two rules this module owns, and the reason they are the original's:

  * "y строки = центр проезда лазера" — :func:`row_y`, one place. Here the "pass"
    is a row of SCREEN PIXELS, so the step is `pixel_y_mm` and the centre rule is
    what makes pixel sampling "nearest integer" instead of "nearest edge";
  * "строка растра → отрезки" — the polygon/scan-line intersection.

Note what is ABSENT on purpose: there is no X step. Drawing from geometry fixes the
X boundary exactly at the segment end; discretising X is the caller's job (the
pixels of the image), not the input's.

POLARITY is a sequence operation, not a boolean one: `%LPC*%` clears what was drawn
BEFORE it, so shapes are applied in file order (see `gerber_source`).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Iterator

from .gerber_source import Shape

ROW_CENTRE = 0.5
"""A row is taken at the CENTRE of the pass, not at its edge."""

BBox = tuple[float, float, float, float]

Segment = tuple[float, float]


def normalize(segments: Iterable[Segment]) -> tuple[Segment, ...]:
    """Sort, merge touching/overlapping, drop zero-length; reject reversed/non-finite.

    The single owner of the row invariant: every operation here returns its result
    through this function (map: "нормализация строки отрезков").

    Two rules that look like details and are not (Денис, 20.10):

      * a zero-length segment (``x1 == x0``) is DROPPED: erosion and clipping produce
        them legitimately, they carry no ink;
      * a REVERSED segment (``x1 < x0``) raises ``ValueError`` instead of being
        dropped. It can only come from a broken transformation — a naive mirror
        writes ``(2c - x0, 2c - x1)``, which flips every segment. Silently dropping
        those would turn the bottom layer into an empty file with no line in the log.
    """
    prepared: list[Segment] = []
    for x0, x1 in segments:
        if not (math.isfinite(x0) and math.isfinite(x1)):
            # NaN compares False with everything, so a NaN would sail through the
            # "reversed" test, merge into a neighbour and reach the image as a hole
            # in the wrong place. Infinity would produce an unbounded segment. Both
            # are broken geometry from upstream, so both raise like a reversed one.
            raise ValueError(
                f"non-finite segment coordinate ({x0!r}, {x1!r}): the geometry "
                f"upstream is broken, not the data to be clipped")
        if x1 < x0:
            raise ValueError(
                f"reversed segment ({x0!r}, {x1!r}): a transformation is wrong, "
                f"not the data — fix the transformation, do not drop the segment")
        if x1 == x0:
            continue
        prepared.append((x0, x1))
    if not prepared:
        return ()
    prepared.sort()
    merged: list[list[float]] = [[prepared[0][0], prepared[0][1]]]
    for x0, x1 in prepared[1:]:
        if x0 <= merged[-1][1]:
            if x1 > merged[-1][1]:
                merged[-1][1] = x1
        else:
            merged.append([x0, x1])
    return tuple((x0, x1) for x0, x1 in merged)


@dataclass(frozen=True, slots=True)
class ScanRow:
    """Immutable: the segments are normalised once, in ``__post_init__``.

    ``y_mm`` is the CENTRE of the pass, ``y0 + (i + 0.5) * step_y`` — the row grid
    decides that, this class only carries it.
    """

    y_mm: float
    segments: tuple[Segment, ...] = ()

    def __post_init__(self) -> None:
        if not math.isfinite(self.y_mm):
            raise ValueError(f"row height must be finite, got {self.y_mm!r}")
        object.__setattr__(self, "segments", normalize(self.segments))

    @classmethod
    def empty(cls, y_mm: float) -> "ScanRow":
        """A row with no ink — the form used for rows outside the figure."""
        return cls(y_mm, ())

    @property
    def is_empty(self) -> bool:
        return not self.segments


def union(a: Iterable[Segment], b: Iterable[Segment]) -> tuple[Segment, ...]:
    """Everything that is "on" in either list — a dark object adds copper."""
    return normalize(tuple(normalize(a)) + tuple(normalize(b)))


def subtract(a: Iterable[Segment], b: Iterable[Segment]) -> tuple[Segment, ...]:
    """``a - b``: what stays on after the second list is cleared away (`%LPC*%`)."""
    remaining = tuple(normalize(b))
    out: list[Segment] = []
    for x0, x1 in normalize(a):
        pieces: list[Segment] = [(x0, x1)]
        for c0, c1 in remaining:
            if not pieces:
                break
            cut: list[Segment] = []
            for p0, p1 in pieces:
                if c1 <= p0 or c0 >= p1:
                    cut.append((p0, p1))
                    continue
                if p0 < c0:
                    cut.append((p0, c0))
                if c1 < p1:
                    cut.append((c1, p1))
            pieces = cut
        out.extend(pieces)
    return normalize(out)


def row_y(y0_mm: float, index: int, step_y_mm: float) -> float:
    """Height of row ``index`` — the single owner of ``y0 + (i + 0.5)·step``."""
    return y0_mm + (index + ROW_CENTRE) * step_y_mm


def row_count(height_mm: float, step_y_mm: float) -> int:
    """How many rows fit a figure ``height_mm`` tall — whole rows, rounded."""
    if not math.isfinite(step_y_mm) or step_y_mm <= 0.0:
        raise ValueError(f"row step must be finite and positive, got {step_y_mm!r}")
    return int(round(height_mm / step_y_mm))


def _crossings(polygon: tuple[tuple[float, float], ...], y_mm: float) -> list[float]:
    """Half-open rule on the edges: a vertex on `y` is counted once, not twice."""
    xs: list[float] = []
    count = len(polygon)
    for i in range(count):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % count]
        if y1 == y2:
            continue
        if (y1 <= y_mm < y2) or (y2 <= y_mm < y1):
            xs.append(x1 + (y_mm - y1) * (x2 - x1) / (y2 - y1))
    xs.sort()
    return xs


def polygon_intervals(polygon: tuple[tuple[float, float], ...],
                      y_mm: float) -> tuple[Segment, ...]:
    """Where a closed polygon covers the line ``y = y_mm`` (even-odd rule)."""
    xs = _crossings(polygon, y_mm)
    return normalize((xs[i], xs[i + 1]) for i in range(0, len(xs) - 1, 2))


def row_segments(shapes: Iterable[Shape], y_mm: float) -> tuple[Segment, ...]:
    """The row at ``y_mm``: shapes applied in FILE ORDER, dark adds, clear erases."""
    accumulated: tuple[Segment, ...] = ()
    for shape in shapes:
        _x0, y0, _x1, y1 = shape.bbox
        if not (y0 <= y_mm <= y1):
            continue
        intervals: tuple[Segment, ...] = ()
        for polygon in shape.polygons:
            intervals = union(intervals, polygon_intervals(polygon, y_mm))
        if not intervals:
            continue
        accumulated = (union(accumulated, intervals) if shape.dark
                       else subtract(accumulated, intervals))
    return accumulated


def iter_rows(shapes: Iterable[Shape], box: BBox,
              step_y_mm: float) -> Iterator[ScanRow]:
    """Every row of the field, geometrically, one at a time, bottom row first.

    The step is the SCREEN PIXEL of Y (`pixel_y_mm`) and the row is taken at the
    CENTRE of that pixel, so a pixel is lit when its centre is inside the geometry.
    The rows ascend in Gerber's Y (bottom to top); turning them into image rows
    (top to bottom) is the ONE Y flip, and it belongs to the caller, not here.
    """
    x0, y0, _x1, y1 = box
    shapes = tuple(shapes)
    for index in range(row_count(y1 - y0, step_y_mm)):
        height = row_y(y0, index, step_y_mm)
        yield ScanRow(height, row_segments(shapes, height))
