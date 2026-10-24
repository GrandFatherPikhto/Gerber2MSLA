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

import numpy as np

from .masks import (Figure, Placement, Refusal, Screen, _quantised, compose, marker_pixels,
                    place_figure)
from .patterns import build_bars, build_grid, build_patches, build_square, build_text
from .plate_config import (BarsSpec, FigureSpec, GridSpec, PatchesSpec, PlateConfig,
                           SquareSpec, TextSpec, fill_text)


def _corner_px(at_mm: tuple[float, float], screen: Screen) -> tuple[int, int]:
    """The corner of a figure INSIDE the plate, in whole pixels of each axis.

    Zero is legal here — a figure may sit on the plate's very corner — so this is not
    `masks._quantised`, which refuses a request below one pixel.
    """
    return (int(round(at_mm[0] / screen.pixel_x_mm)),
            int(round(at_mm[1] / screen.pixel_y_mm)))


def _figure_of(spec: FigureSpec, screen: Screen,
               exposure_s: float | None) -> Figure:
    """One spec, drawn by the very function the single command uses.

    ``exposure_s`` reaches the LABEL only: `text = "{exposure_s}s"` is the one substitution
    a config may hold (plan Т1 follow-up), and it is filled here, where the plate's own
    time is known — never by a second copy of the number in the file.
    """
    if isinstance(spec, SquareSpec):
        return build_square(screen, spec.size_mm[0], spec.size_mm[1], spec.line)
    if isinstance(spec, GridSpec):
        return build_grid(screen, spec.size_mm[0], spec.size_mm[1], spec.line, spec.gap,
                          spec.direction)
    if isinstance(spec, BarsSpec):
        return build_bars(screen, spec.widths, spec.lines)
    if isinstance(spec, PatchesSpec):
        return build_patches(screen, spec.patch_mm, spec.widths, spec.gap,
                             spec.patch_gap_mm)
    if isinstance(spec, TextSpec):
        return build_text(screen, fill_text(spec.text, exposure_s), spec.stroke_px)
    raise AssertionError(f"a figure spec this module does not know: {spec!r}")


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


def build_config_plate(screen: Screen, config: PlateConfig,
                       seconds: float | None = None,
                       ) -> tuple[tuple[Placement, ...], tuple[str, ...]]:
    """The whole plate as ONE figure: drawn, then turned, then centred on the screen.

    ``seconds`` is the exposure time of THIS file: a series (plan of 25.10) writes one file
    per time, and the label `{exposure_s}` must say this file's time, not the first one.
    ``None`` is a config that names no time at all (a PNG-only plate).

    ``[plate] rotate`` turns the FINISHED plate — every figure and the marker — by 90, 180
    or 270 degrees COUNTER-clockwise, and the turned plate is centred again (plan of 25.10:
    a 70 x 80 mm plate at 90 degrees is 2353 x 2059 px and sits at 1703, 770 px). So the
    picture is composed on a plate-sized screen first and handed to `masks.compose` as one
    figure named ``plate``: placement, mirror and polarity stay the ONE path, and the turn
    is a fact about the plate, not about each figure.

    A quarter turn on a non-square pixel is a refusal: the axes would swap their meaning and
    every distance on the plate would be measured against the wrong pitch.
    """
    plate_w_px = _quantised(config.width_mm, screen.pixel_x_mm, "X", "the plate width")
    plate_h_px = _quantised(config.height_mm, screen.pixel_y_mm, "Y", "the plate height")
    if plate_w_px > screen.width_px or plate_h_px > screen.height_px:
        raise Refusal(
            f"the plate {config.width_mm:.3f} x {config.height_mm:.3f} mm is "
            f"{plate_w_px} x {plate_h_px} px, larger than the {screen.width_px} x "
            f"{screen.height_px} px screen: the plate is centred and would hang off both "
            f"sides")

    report = [
        f"config: {config.label}, {len(config.figures)} figure(s) in the order of the file",
    ]
    if seconds is not None:
        report.append(f"exposure: {seconds:g} s from [plate] exposure_s: the printer file "
                      f"uses it for the layer AND for the bottom layer")

    placements: list[Placement] = []
    if config.marker_at_mm is None:
        report.append("no marker: the plate carries no orientation reference ([marker] "
                      "is not in the config)")
    else:
        offset_x, offset_y = _corner_px(config.marker_at_mm, screen)
        marker = Figure(pixels=marker_pixels(screen), report=())
        _require_on_plate("marker", marker, offset_x, offset_y, plate_w_px, plate_h_px,
                          screen)
        placements.append(Placement(figure=marker, x_px=offset_x, y_px=offset_y,
                                    name="marker"))
        report.append(
            f"marker: ONE letter F at {config.marker_at_mm[0]:.3f}, "
            f"{config.marker_at_mm[1]:.3f} mm from the plate's top-left corner "
            f"({offset_x}, {offset_y} px inside it)")

    for spec in config.figures:
        figure = _figure_of(spec, screen, seconds)
        offset_x, offset_y = _corner_px(spec.at_mm, screen)
        _require_on_plate(spec.name, figure, offset_x, offset_y, plate_w_px, plate_h_px,
                          screen)
        placements.append(Placement(figure=figure, x_px=offset_x, y_px=offset_y,
                                    name=spec.name))
        report.append(
            f"figure {spec.name}: {figure.width_px} x {figure.height_px} px = "
            f"{screen.mm_x(figure.width_px):.3f} x {screen.mm_y(figure.height_px):.3f} mm "
            f"at {spec.at_mm[0]:.3f}, {spec.at_mm[1]:.3f} mm from the plate's top-left "
            f"corner ({offset_x}, {offset_y} px inside it)")
        report.extend(f"  {line}" for line in figure.report)

    # The plate alone, on a screen of its own size: the figures are placed and checked by
    # the same compose, and the turn below is applied to the finished picture.
    plate_screen = Screen(width_px=plate_w_px, height_px=plate_h_px,
                          pixel_x_um=screen.pixel_x_um, pixel_y_um=screen.pixel_y_um)
    picture, _ = compose(plate_screen, placements, mirror=False, invert=False)

    if config.rotate:
        if config.rotate in (90, 270) and screen.pixel_x_um != screen.pixel_y_um:
            raise Refusal(
                f"the plate is turned by {config.rotate} degrees and the screen pixel is "
                f"not square ({screen.pixel_x_um:.2f} x {screen.pixel_y_um:.2f} um): a "
                f"quarter turn would put every distance on the axis of the other pitch")
        picture = np.rot90(picture, config.rotate // 90)   # counter-clockwise, as asked

    turned_h, turned_w = picture.shape
    if turned_w > screen.width_px or turned_h > screen.height_px:
        raise Refusal(
            f"the plate turned by {config.rotate} degrees is {turned_w} x {turned_h} px, "
            f"larger than the {screen.width_px} x {screen.height_px} px screen: the plate "
            f"is centred and would hang off both sides")

    plate = Figure(pixels=picture, report=())
    placed = place_figure(screen, plate, None, name="plate")
    if config.rotate:
        report.append(
            f"plate: {config.width_mm:.3f} x {config.height_mm:.3f} mm "
            f"({plate_w_px} x {plate_h_px} px) turned {config.rotate} degrees "
            f"counter-clockwise to {turned_w} x {turned_h} px, centred on the "
            f"{screen.width_px} x {screen.height_px} px screen at {placed.x_px}, "
            f"{placed.y_px} px")
    else:
        report.append(
            f"plate: {config.width_mm:.3f} x {config.height_mm:.3f} mm "
            f"({plate_w_px} x {plate_h_px} px), centred on the {screen.width_px} x "
            f"{screen.height_px} px screen at {placed.x_px}, {placed.y_px} px")
        report.append("rotate: 0 (no [plate] rotate: the plate lies as drawn)")
    return (placed,), tuple(report)


__all__ = ["build_config_plate"]
