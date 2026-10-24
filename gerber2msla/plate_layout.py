# gerber2msla/plate_layout.py
"""The plate a CONFIG asks for: its specs plus the screen become a list of placements.

Two things happen here and nothing else: the figure of each spec is drawn by
`patterns.build_*` exactly as the single commands draw it, and its corner is counted
from the plate's own top-left corner. The plate is put in the middle of the screen —
the config does not move it, and ``--at`` next to ``--config`` is a refusal (decision of
24.10: one source of truth for the layout).

The numbers of the config are the operator's: ``at_mm`` counts from the plate's corner,
which is why a figure's ``Placement.at_mm`` stays None — `masks.compose` then reports the
corner in SCREEN millimetres, the number the reader can measure on the file, while this
module's own report line keeps the plate-relative request next to it.

Refusals, all with the figure's name (``kind #N``, N from 1 in the order of the file):

  * the plate is larger than the screen — the centred plate would hang off both sides;
  * a figure does not fit the plate — the plate never shrinks a figure to make it fit;
  * two figures paint the same pixel — this one is `masks.compose`'s, the single path of
    placement, and it names BOTH figures; nothing here guesses at overlaps.

Layout, marker, mirror and polarity stay where they were: one marker per plate (only if
the config has a ``[marker]`` table, and the report says so in words either way), one
mirror and one polarity swap for the whole picture.
"""
from __future__ import annotations

from .masks import (Figure, Placement, Refusal, Screen, _quantised, marker_pixels,
                    origin_pixels)
from .patterns import build_bars, build_grid, build_patches, build_square
from .plate_config import BarsSpec, FigureSpec, GridSpec, PlateConfig, SquareSpec


def _corner_px(at_mm: tuple[float, float], screen: Screen) -> tuple[int, int]:
    """The corner of a figure INSIDE the plate, in whole pixels of each axis.

    Zero is legal here — a figure may sit on the plate's very corner — so this is not
    `masks._quantised`, which refuses a request below one pixel.
    """
    return (int(round(at_mm[0] / screen.pixel_x_mm)),
            int(round(at_mm[1] / screen.pixel_y_mm)))


def _figure_of(spec: FigureSpec, screen: Screen) -> Figure:
    """One spec, drawn by the very function the single command uses."""
    if isinstance(spec, SquareSpec):
        return build_square(screen, spec.size_mm[0], spec.size_mm[1], spec.line)
    if isinstance(spec, GridSpec):
        return build_grid(screen, spec.size_mm[0], spec.size_mm[1], spec.line, spec.gap,
                          spec.direction)
    if isinstance(spec, BarsSpec):
        return build_bars(screen, spec.widths, spec.lines)
    return build_patches(screen, spec.patch_mm, spec.widths, spec.gap, spec.patch_gap_mm)


def _require_on_plate(name: str, figure: Figure, x_px: int, y_px: int,
                      plate_w_px: int, plate_h_px: int, screen: Screen) -> None:
    """A figure must stay on the plate: the plate is the board, the screen is not."""
    if (x_px >= 0 and y_px >= 0
            and x_px + figure.width_px <= plate_w_px
            and y_px + figure.height_px <= plate_h_px):
        return
    raise Refusal(
        f"the figure {name} {screen.mm_x(figure.width_px):.3f} x "
        f"{screen.mm_y(figure.height_px):.3f} mm ({figure.width_px} x "
        f"{figure.height_px} px) does not fit the plate: it would span {x_px} ... "
        f"{x_px + figure.width_px} px across and {y_px} ... {y_px + figure.height_px} px "
        f"down inside a {plate_w_px} x {plate_h_px} px plate. The plate does not shrink a "
        f"figure to make it fit: move it or make it smaller")


def build_config_plate(screen: Screen,
                       config: PlateConfig) -> tuple[tuple[Placement, ...], tuple[str, ...]]:
    """Every figure of the config, placed on a plate in the middle of the screen."""
    plate_w_px = _quantised(config.width_mm, screen.pixel_x_mm, "X", "the plate width")
    plate_h_px = _quantised(config.height_mm, screen.pixel_y_mm, "Y", "the plate height")
    if plate_w_px > screen.width_px or plate_h_px > screen.height_px:
        raise Refusal(
            f"the plate {config.width_mm:.3f} x {config.height_mm:.3f} mm is "
            f"{plate_w_px} x {plate_h_px} px, larger than the {screen.width_px} x "
            f"{screen.height_px} px screen: the plate is centred and would hang off both "
            f"sides")
    plate_x, plate_y = origin_pixels(screen, plate_w_px, plate_h_px, None)

    report = [
        f"plate: {config.width_mm:.3f} x {config.height_mm:.3f} mm "
        f"({plate_w_px} x {plate_h_px} px), centred on the {screen.width_px} x "
        f"{screen.height_px} px screen at {plate_x}, {plate_y} px",
        f"config: {config.label}, {len(config.figures)} figure(s) in the order of the file",
    ]
    if config.exposure_s is not None:
        report.append(f"exposure: {config.exposure_s:g} s from [plate] exposure_s: the "
                      f"printer file uses it for the layer AND for the bottom layer")

    placements: list[Placement] = []
    if config.marker_at_mm is None:
        report.append("no marker: the plate carries no orientation reference ([marker] "
                      "is not in the config)")
    else:
        offset_x, offset_y = _corner_px(config.marker_at_mm, screen)
        marker = Figure(pixels=marker_pixels(screen), report=())
        _require_on_plate("marker", marker, offset_x, offset_y, plate_w_px, plate_h_px,
                          screen)
        placements.append(Placement(figure=marker, x_px=plate_x + offset_x,
                                    y_px=plate_y + offset_y, name="marker"))
        report.append(
            f"marker: ONE letter F at {config.marker_at_mm[0]:.3f}, "
            f"{config.marker_at_mm[1]:.3f} mm from the plate's top-left corner "
            f"({offset_x}, {offset_y} px inside it)")

    for spec in config.figures:
        figure = _figure_of(spec, screen)
        offset_x, offset_y = _corner_px(spec.at_mm, screen)
        _require_on_plate(spec.name, figure, offset_x, offset_y, plate_w_px, plate_h_px,
                          screen)
        placements.append(Placement(figure=figure, x_px=plate_x + offset_x,
                                    y_px=plate_y + offset_y, name=spec.name))
        report.append(
            f"figure {spec.name}: {figure.width_px} x {figure.height_px} px = "
            f"{screen.mm_x(figure.width_px):.3f} x {screen.mm_y(figure.height_px):.3f} mm "
            f"at {spec.at_mm[0]:.3f}, {spec.at_mm[1]:.3f} mm from the plate's top-left "
            f"corner ({offset_x}, {offset_y} px inside it)")
        report.extend(f"  {line}" for line in figure.report)
    return tuple(placements), tuple(report)


__all__ = ["build_config_plate"]
