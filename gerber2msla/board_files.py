# gerber2msla/board_files.py
"""A board from a TOML config: every side built, composed, written and explained.

The config names ONE frame (``[board] outline``) and ONE output folder (``[output] dir``),
and this module is where those two promises are kept:

  * every file of the board is built from the same outline, so the top and the bottom land
    on the same pixels of the screen — the report prints the frame ONCE, because a second
    line of it could only disagree with the first;
  * the exposure file of a side follows the config (``holes = false`` keeps a tenting
    mask), while its ``<side>_align.px6s`` ALWAYS carries the holes — an alignment file is
    useless without them — and takes its own ``align_s``;
  * the mirror is the side's own, and it is made ONCE, by ``masks.compose``: the П2
    writer's own ``mirror_x`` stays off, which is why its line says "mirror: off" even
    when the side is mirrored. One mirror was asked for, one mirror was made.

Nothing here chooses the screen or the pixel: the caller passes both the screen and the
line that says where its pixel came from (`screen_choice.screen_for`), exactly as the
built-in ``board`` command does — one answer about one template serves both commands.

A PNG and a printer file of one picture come from the SAME ``compose`` result, because two
drawings of one side could differ by a pixel, and then nobody knows which one was exposed.

Overwriting is allowed (plan Б0): a file is generated from the config again, so the report
says ``overwrote <path>``. There is no backup and no protection — a config is a recipe,
and a recipe that refuses to cook twice is not a recipe.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .board import build_board
from .board_config import BoardConfig, SideSpec
from .masks import Figure, Screen, compose, place_figure, write_mask
from .px6s_write import write_file

REPORT_FILE = "board_report.txt"
"""The report and the config text, next to the files: a month later the folder alone does
not say what was exposed."""


# ─────────────────────────────── the picture ───────────────────────────────

def _picture(screen: Screen, config: BoardConfig, side: SideSpec,
             with_holes: bool) -> tuple[Figure, np.ndarray, tuple[str, ...]]:
    """One picture of one side: the copper built, placed in the middle, composed ONCE.

    ``with_holes`` is the ONE difference between a working file and an alignment file: the
    config decides it for the working file (``holes``), while the alignment file always
    takes the drills (plan Б1). Everything else — copper, frame, mirror, placement — is
    the same code, so the two files cannot drift apart.
    """
    figure = build_board(screen, side.copper,
                         drills=config.drills if with_holes else (),
                         outline=config.outline)
    image, placed = compose(screen, [place_figure(screen, figure, None)],
                            mirror=side.mirror, invert=False,
                            polarity_what="the copper")
    return figure, image, placed


def _white(image: np.ndarray, screen: Screen) -> str:
    """The white of the COMPOSED picture: the number the printer will light."""
    count = int(np.count_nonzero(image))
    return (f"white: {count} px = "
            f"{count * screen.pixel_x_mm * screen.pixel_y_mm:.3f} mm2")


def _without_frame(report: tuple[str, ...]) -> tuple[str, ...]:
    """A figure's report minus its frame line: the board prints the frame ONCE, on top.

    Each FILE still carries its own frame line — it is its own record — but the folder's
    report has one, because the outline fixes it for every file of the board.
    """
    return tuple(line for line in report if not line.startswith("frame: "))


def _drilled(figure: Figure) -> tuple[str, ...]:
    """The drill-file lines and the holes line of a figure, whole.

    `build_board` puts the sampling line before the drills and ends with the white line, so
    the lines between them are exactly the holes' account — counting the holes a second
    time here, with a second wording, is how two reports start to disagree.
    """
    lines = figure.report
    start = next(i for i, line in enumerate(lines) if line.startswith("sampling: ")) + 1
    stop = next(i for i, line in enumerate(lines) if line.startswith("white: "))
    return tuple(lines[start:stop])


# ──────────────────────────────── the files ────────────────────────────────

def _write_px6s(screen: Screen, config: BoardConfig, image: np.ndarray, name: str,
                seconds: float) -> list[str]:
    """One printer file from one picture; the П2 writer, and no second path to a px6s."""
    target = config.output.dir / name
    existed = target.exists()      # asked BEFORE the write: after it the answer is yes
    written, report = write_file(config.output.template, image, target, seconds)
    return [f"{'overwrote' if existed else 'Wrote'} {written}: "
            f"{screen.width_px} x {screen.height_px} px layer, {seconds:g} s",
            *(f"  {line}" for line in report)]


def _write_png(screen: Screen, config: BoardConfig, image: np.ndarray, name: str,
               report: tuple[str, ...]) -> list[str]:
    """One mask PNG of the very same picture, with the config text in its own chunk."""
    target = config.output.dir / name
    existed = target.exists()
    written = write_mask(target, screen, report, image, config_text=config.text)
    return [f"{'overwrote' if existed else 'Wrote'} {written}: "
            f"{screen.width_px} x {screen.height_px} px mask"]


# ──────────────────────────────── the board ────────────────────────────────

def write_board(screen: Screen, config: BoardConfig, *,
                pixel_line: str) -> tuple[str, ...]:
    """Every side of the config, written into ``[output] dir``; returns the printed lines.

    ``pixel_line`` comes from `screen_choice.screen_for`: the report of the FOLDER has to
    carry the same sentence as the report of the command, so it is passed, not repeated.
    """
    folder = config.output.dir
    folder.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [
        f"board: {config.label}, {len(config.sides)} side(s), one frame and one folder",
        pixel_line,
        ("png: on ([output] png = true) — every printer file gets a PNG of the same picture"
         if config.output.png else
         "png: off ([output] png = false) — printer files only, no PNG to look at"),
        "mirror: made ONCE per side by compose; the px6s writer's own mirror stays off, so "
        "its 'mirror: off' line means the file stores no SECOND reflection",
    ]
    if config.pixel_um is None:
        lines.append(
            "pixel_um: not in [output] — the geometry is the template header's pixel; add "
            "it once the square test has measured this printer")

    frame_printed = False
    for side in config.sides:
        figure, image, placed = _picture(screen, config, side, with_holes=side.holes)
        if not frame_printed:
            # ONE frame line for the whole board: the outline fixes it for every file, and
            # a second copy of it could only disagree with the first (plan «одна рамка»).
            lines.append(next(line for line in figure.report
                              if line.startswith("frame: ")))
            frame_printed = True
        lines.append(
            f"side {side.name}: {Path(side.copper).name}, mirror "
            f"{'on' if side.mirror else 'off'}, holes "
            f"{'subtracted (a working mask WITH holes)' if side.holes else 'none (a tenting mask)'}"
            f", exposure {side.exposure_s:g} s")
        lines.extend(f"  {line}" for line in (*_without_frame(figure.report), *placed))
        report = (pixel_line, *figure.report, *placed)
        lines.extend(_write_px6s(screen, config, image, side.exposure_file,
                                 side.exposure_s))
        if config.output.png:
            lines.extend(_write_png(
                screen, config, image,
                Path(side.exposure_file).with_suffix(".png").name, report))

        if side.align_s is None:
            lines.append(f"side {side.name} align: none — the side has no 'align_s', so no "
                         f"alignment file is written")
            continue
        align_figure, align_image, align_placed = _picture(screen, config, side,
                                                           with_holes=True)
        lines.append(
            f"side {side.name} align: {Path(side.copper).name}, mirror "
            f"{'on' if side.mirror else 'off'}, holes ALWAYS subtracted (this is the file "
            f"the two sides are aligned by), {side.align_s:g} s")
        lines.extend(f"  {line}" for line in _drilled(align_figure))
        lines.append(f"  {_white(align_image, screen)}")
        align_report = (pixel_line, *align_figure.report, *align_placed)
        lines.extend(_write_px6s(screen, config, align_image, side.align_file,
                                 side.align_s))
        if config.output.png:
            lines.extend(_write_png(
                screen, config, align_image,
                Path(side.align_file).with_suffix(".png").name, align_report))

    report_path = folder / REPORT_FILE
    text = "\n".join((
        *lines,
        "",
        f"config, whole, as read from {config.label}:",
        *(f"  {line}" for line in config.text.splitlines()),
        "",
    ))
    report_path.write_text(text, encoding="utf-8")
    return (*lines, f"report: {report_path} — the whole report and the config text")


__all__ = ["REPORT_FILE", "write_board"]
