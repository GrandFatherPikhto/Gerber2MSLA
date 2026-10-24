"""The ``masks`` command group: ``gerber2msla masks bars|grid|square|plate``.

Every command is a thin layer over the mask core: parse arguments, call one core
function, print the result. No geometry, no units and no file format are decided here.

`bars` and `grid` are COPIED from Gerber2LDI `tools/msla_tests.py` at commit 364fd28
(2026-10-23): the flags, their defaults, the report and the exit codes are the same; the
command is now a subcommand of this utility. The drawing layer lives in `masks.py`, the
patterns in `patterns.py`.

`plate` has TWO layouts: the built-in one (plan П5б, unchanged) and the one a TOML config
asks for (plans К2 and Б0). With ``--config`` the config is the ONLY source of truth: the
flags that place figures the built-in way are refused BY NAME, and so are ``-o``,
``--template``, ``--screen-px``, ``--pixel-um`` and ``--exposure-s`` — everything about
the printer and the output lives in the config's ``[output]`` table. Without ``--config``
nothing changes: ``-o`` is mandatory and the screen comes from ``--template`` or the two
flags, through the same `screen_for` the `board` command uses.

The root parser, `--version` and the one-line refusal live in `cli.py`; the printer-file
commands live in `cli_px6s.py`. This module only ADDS its command group to the root.

Messages are ASCII English, without i18n: the utility is small, and translations arrive
together with the Gerber input and the interface (rules: deepseek.md п.9).
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from types import SimpleNamespace

from .cli_px6s import _positive_seconds
from .masks import Refusal, Screen, add_marker, compose, place_figure, write_mask
from .patterns import (DEFAULT_GRID_GAP_MM, DEFAULT_GRID_HEIGHT_MM, DEFAULT_GRID_LINE_MM,
                       DEFAULT_GRID_WIDTH_MM, DEFAULT_LINES, DEFAULT_SQUARE_LINE_MM,
                       DEFAULT_SQUARE_SIDE_MM, DEFAULT_WIDTHS_MM, DIRECTIONS,
                       PLATE_GRID_HEIGHT_MM, PLATE_GRID_WIDTH_MM, PLATE_HEIGHT_MM,
                       PLATE_MARGIN_MM, PLATE_WIDTH_MM, Width, build_bars, build_grid,
                       build_plate, build_square)
from .plate_config import load_plate_config
from .plate_layout import build_config_plate
from .px6s import read_file
from .px6s_write import write_file
from .screen_choice import screen_for

EXIT_OK = 0
"""The same number as `cli.EXIT_OK`; a handler returns it without importing the router."""


# ───────────────────────────── argument types ──────────────────────────────

def _pixels_pair(text: str) -> tuple[int, int]:
    """argparse type: ``WxH`` in whole pixels. No invented default."""
    parts = text.replace(" ", "").lower().split("x")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise argparse.ArgumentTypeError(
            f"expected two whole pixel counts separated by x, got {text!r}")
    width, height = (int(part) for part in parts)
    if width < 1 or height < 1:
        raise argparse.ArgumentTypeError(f"the screen must be at least one pixel, got {text!r}")
    return width, height


def _micrometres_pair(text: str) -> tuple[float, float]:
    """argparse type: ``PXxPY`` in micrometres — a pixel may be not square."""
    parts = text.replace(" ", "").lower().split("x")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(
            f"expected two pixel sizes separated by x, got {text!r}")
    try:
        x_um, y_um = (float(part) for part in parts)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected two pixel sizes separated by x, got {text!r}") from None
    if not (math.isfinite(x_um) and math.isfinite(y_um)) or x_um <= 0.0 or y_um <= 0.0:
        raise argparse.ArgumentTypeError(
            f"expected two positive pixel sizes in um, got {text!r}")
    return x_um, y_um


def _mm_pair(text: str) -> tuple[float, float]:
    """argparse type: ``WxH`` in millimetres, both sizes positive and finite."""
    parts = text.replace(" ", "").lower().split("x")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(
            f"expected two sizes separated by x, got {text!r}")
    try:
        width, height = (float(part) for part in parts)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected two sizes separated by x, got {text!r}") from None
    if not (math.isfinite(width) and math.isfinite(height)) or width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError(
            f"expected two positive sizes in mm, got {text!r}")
    return width, height


def _millimetres_pair(text: str) -> tuple[float, float]:
    """argparse type: ``X,Y`` in millimetres from the top-left pixel of the PNG."""
    parts = text.replace(" ", "").split(",")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"expected two millimetres separated by a comma, got {text!r}")
    try:
        x_mm, y_mm = (float(part) for part in parts)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected two millimetres separated by a comma, got {text!r}") from None
    if not (math.isfinite(x_mm) and math.isfinite(y_mm)):
        raise argparse.ArgumentTypeError(
            f"expected two finite millimetres separated by a comma, got {text!r}")
    return x_mm, y_mm


def _width_list(text: str) -> tuple[float, ...]:
    """argparse type: comma separated positive widths, kept in the order given."""
    values: list[float] = []
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            value = float(item)
        except ValueError:
            raise argparse.ArgumentTypeError(f"expected a number, got {item!r}") from None
        if not math.isfinite(value) or value <= 0.0:
            raise argparse.ArgumentTypeError(f"expected a positive width in mm, got {item!r}")
        values.append(value)
    if not values:
        raise argparse.ArgumentTypeError("at least one width is required")
    return tuple(values)


def _pixel_list(text: str) -> tuple[int, ...]:
    """argparse type: comma separated WHOLE pixel counts, kept in the order given."""
    values: list[int] = []
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        if not item.isdigit() or int(item) < 1:
            raise argparse.ArgumentTypeError(
                f"expected a whole pixel count of at least one, got {item!r}")
        values.append(int(item))
    if not values:
        raise argparse.ArgumentTypeError("at least one width is required")
    return tuple(values)


def _whole_pixels(text: str) -> int:
    """argparse type: one whole pixel count, at least one."""
    text = text.strip()
    if not text.isdigit() or int(text) < 1:
        raise argparse.ArgumentTypeError(
            f"expected a whole pixel count of at least one, got {text!r}")
    return int(text)


def _line_count(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a whole number, got {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"a group needs at least one line, got {value}")
    return value


def _positive_mm(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a number, got {text!r}") from None
    if not math.isfinite(value) or value <= 0.0:
        raise argparse.ArgumentTypeError(f"expected a positive size in mm, got {text!r}")
    return value


# ────────────────────────────── argument tree ──────────────────────────────

def add_parser(commands: argparse._SubParsersAction) -> None:
    """Add the `masks` command group to the root subparsers."""
    masks = commands.add_parser(
        "masks", help="draw test masks in exact screen pixels",
        description="Draw test masks in exact screen pixels of the LCD.")
    kinds = masks.add_subparsers(dest="kind", metavar="PATTERN")
    kinds.required = True

    def common(kind: argparse.ArgumentParser, *, marker: bool = True) -> None:
        kind.add_argument("--screen-px", type=_pixels_pair, required=True,
                          help="screen size in pixels, WxH (no default: read the spec)")
        kind.add_argument("--pixel-um", type=_micrometres_pair, required=True,
                          help="one pixel in micrometres, PXxPY (a pixel may be not square)")
        kind.add_argument("-o", "--output", required=True, help="output PNG")
        kind.add_argument("--at", type=_millimetres_pair, default=None,
                          help="top-left corner of the figure, mm from the top-left pixel "
                               "(default: centred)")
        kind.add_argument("--mirror", action="store_true",
                          help="reflect the whole picture along X (a resist facing the screen)")
        kind.add_argument("--invert", action="store_true",
                          help="white = the gaps instead of the lines")
        if marker:
            kind.add_argument("--marker", action=argparse.BooleanOptionalAction, default=True,
                              help="draw the letter F in the top-left corner of the figure, so a "
                                   "mirrored or upside-down exposure is visible on the plate "
                                   "(--no-marker turns it off)")

    bars_parser = kinds.add_parser(
        "bars", help="lines and gaps of known widths, horizontal and vertical blocks",
        description="lines and gaps of known widths: horizontal block, vertical block to its right")
    common(bars_parser)
    bars_parser.add_argument("--widths-mm", type=_width_list, default=None,
                             help="bar widths in mm, in the order to draw them "
                                  f"(default {' '.join(f'{w:g}' for w in DEFAULT_WIDTHS_MM)})")
    bars_parser.add_argument("--widths-px", type=_pixel_list, default=None,
                             help="bar widths in WHOLE pixels of the screen, one count for "
                                  "both axes (excludes --widths-mm)")
    bars_parser.add_argument("--lines", type=_line_count, default=DEFAULT_LINES,
                             help="lines per group")
    bars_parser.set_defaults(handler=_cmd_bars)

    grid_parser = kinds.add_parser(
        "grid", help="a rectangle filled with lines",
        description="a rectangle filled with lines: the first line is flush with the near edge")
    common(grid_parser)
    grid_parser.add_argument("--width-mm", type=_positive_mm, default=DEFAULT_GRID_WIDTH_MM,
                             help="width of the rectangle in mm")
    grid_parser.add_argument("--height-mm", type=_positive_mm, default=DEFAULT_GRID_HEIGHT_MM,
                             help="height of the rectangle in mm")
    grid_parser.add_argument("--line-mm", type=_positive_mm, default=None,
                             help=f"line width in mm (default {DEFAULT_GRID_LINE_MM:g})")
    grid_parser.add_argument("--line-px", type=_whole_pixels, default=None,
                             help="line width in WHOLE pixels of the screen, both axes "
                                  "(excludes --line-mm)")
    grid_parser.add_argument("--gap-mm", type=_positive_mm, default=None,
                             help=f"gap between the lines in mm (default {DEFAULT_GRID_GAP_MM:g})")
    grid_parser.add_argument("--gap-px", type=_whole_pixels, default=None,
                             help="gap between the lines in WHOLE pixels of the screen, both "
                                  "axes (excludes --gap-mm)")
    grid_parser.add_argument("--direction", choices=DIRECTIONS, default="both",
                             help="lines along X, along Y, or both")
    grid_parser.set_defaults(handler=_cmd_grid)

    square_parser = kinds.add_parser(
        "square", help="a closed contour that measures the pixel of each axis",
        description="a closed square contour: the side and the line are whole pixels of "
                    "their own axis, and the report carries the measurement formulas")
    common(square_parser)
    square_parser.add_argument("--side-mm", type=_positive_mm, default=None,
                               help="side of the square in mm, one value for both axes "
                                    f"(default {DEFAULT_SQUARE_SIDE_MM:g}; the laser's 150 mm "
                                    "does not fit this screen)")
    square_parser.add_argument("--side-px", type=_whole_pixels, default=None,
                               help="side in WHOLE pixels of the screen, both axes "
                                    "(excludes --side-mm)")
    square_parser.add_argument("--line-mm", type=_positive_mm, default=None,
                               help=f"line width in mm (default {DEFAULT_SQUARE_LINE_MM:g})")
    square_parser.add_argument("--line-px", type=_whole_pixels, default=None,
                               help="line width in WHOLE pixels of the screen, both axes "
                                    "(excludes --line-mm)")
    square_parser.set_defaults(handler=_cmd_square)

    plate_parser = kinds.add_parser(
        "plate", help="every test on one plate: the built-in layout or a TOML config",
        description="every test on ONE plate: the built-in layout (frame, one marker, bars "
                    "on the left half, grid on the right half) or the layout a TOML config "
                    "asks for, in millimetres from the plate's own top-left corner — the "
                    "layout is the label")
    # NOT `common()`: with --template the screen is the file's, so --screen-px cannot be an
    # argparse-level requirement here; `screen_for` asks for both when there is no template.
    plate_parser.add_argument("--config", default=None, metavar="FILE",
                              help="TOML config of the plate: the figures and where they lie, "
                                   "the marker, and [plate] exposure_s; it has no defaults, "
                                   "so a missing key is a refusal")
    plate_parser.add_argument("--template", default=None, metavar="FILE",
                              help="one-layer px6s of this printer: the screen, the pixel of "
                                   "the file header and the machine blocks")
    plate_parser.add_argument("--screen-px", type=_pixels_pair, default=None,
                              help="screen size in pixels, WxH; not with --template")
    plate_parser.add_argument("--pixel-um", type=_micrometres_pair, default=None,
                              help="one pixel in micrometres, PXxPY; may be not square")
    plate_parser.add_argument("--exposure-s", type=_positive_seconds, default=None,
                              help="exposure for the .px6s, both fields; refused with "
                                   "--config, where [plate] exposure_s is the one source of truth")
    plate_parser.add_argument("-o", "--output", default=None,
                              help="out/plate.png for a mask, out/plate.px6s for the printer file; "
                                   "mandatory WITHOUT --config, refused WITH it (the config "
                                   "names its own [output])")
    plate_parser.add_argument("--mirror", action="store_true",
                              help="reflect the whole picture along X (a resist facing the screen)")
    plate_parser.add_argument("--invert", action="store_true",
                              help="white = the gaps instead of the lines")
    plate_parser.add_argument("--at", type=_millimetres_pair, default=None,
                              help="top-left corner of the BUILT-IN plate, mm from the "
                                   "top-left pixel (default: centred); not with --config")
    plate_parser.add_argument("--plate-mm", type=_mm_pair, default=None,
                              help="plate size WxH in mm; not with --config "
                                   f"(built-in default {PLATE_WIDTH_MM:g}x{PLATE_HEIGHT_MM:g})")
    plate_parser.add_argument("--margin-mm", type=_positive_mm, default=None,
                              help="margin from the plate edge to the frame; not with --config "
                                   f"(built-in default {PLATE_MARGIN_MM:g})")
    plate_parser.add_argument("--grid-mm", type=_mm_pair, default=None,
                              help="grid rectangle WxH in mm; not with --config (built-in "
                                   f"default {PLATE_GRID_WIDTH_MM:g}x{PLATE_GRID_HEIGHT_MM:g})")
    plate_parser.add_argument("--square-line-mm", type=_positive_mm, default=None,
                              help=f"frame line in mm (default {DEFAULT_SQUARE_LINE_MM:g}); "
                                   "not with --config")
    plate_parser.add_argument("--square-line-px", type=_whole_pixels, default=None,
                              help="frame line in WHOLE pixels (excludes --square-line-mm); "
                                   "not with --config")
    plate_parser.add_argument("--widths-mm", type=_width_list, default=None,
                              help="bar widths in mm, in the order to draw them "
                                   f"(default {' '.join(f'{w:g}' for w in DEFAULT_WIDTHS_MM)}); "
                                   "not with --config")
    plate_parser.add_argument("--widths-px", type=_pixel_list, default=None,
                              help="bar widths in WHOLE pixels, one count for both axes "
                                   "(excludes --widths-mm); not with --config")
    plate_parser.add_argument("--lines", type=_line_count, default=None,
                              help=f"lines per bars group (default {DEFAULT_LINES}); "
                                   "not with --config")
    plate_parser.add_argument("--line-mm", type=_positive_mm, default=None,
                              help=f"grid line width in mm (default {DEFAULT_GRID_LINE_MM:g}); "
                                   "not with --config")
    plate_parser.add_argument("--line-px", type=_whole_pixels, default=None,
                              help="grid line width in WHOLE pixels (excludes --line-mm); "
                                   "not with --config")
    plate_parser.add_argument("--gap-mm", type=_positive_mm, default=None,
                              help=f"gap between grid lines in mm (default "
                                   f"{DEFAULT_GRID_GAP_MM:g}); not with --config")
    plate_parser.add_argument("--gap-px", type=_whole_pixels, default=None,
                              help="gap between grid lines in WHOLE pixels "
                                   "(excludes --gap-mm); not with --config")
    plate_parser.add_argument("--direction", choices=DIRECTIONS, default=None,
                              help="grid lines along X, along Y, or both (default both); "
                                   "not with --config")
    plate_parser.set_defaults(handler=_cmd_plate)


# ──────────────────────────────── commands ─────────────────────────────────

def _screen(args: argparse.Namespace) -> Screen:
    width_px, height_px = args.screen_px
    pixel_x_um, pixel_y_um = args.pixel_um
    return Screen(width_px=width_px, height_px=height_px,
                  pixel_x_um=pixel_x_um, pixel_y_um=pixel_y_um)


def _widths(args: argparse.Namespace) -> tuple[Width, ...]:
    """``--widths-mm`` OR ``--widths-px``; neither means the millimetre default list."""
    if args.widths_mm is not None and args.widths_px is not None:
        raise Refusal("use either --widths-mm or --widths-px, not both")
    if args.widths_px is not None:
        return tuple(Width(px=count) for count in args.widths_px)
    return tuple(Width(mm=value) for value in (args.widths_mm or DEFAULT_WIDTHS_MM))


def _one_width(mm: float | None, px: int | None, default_mm: float,
               mm_name: str, px_name: str) -> Width:
    """One dimension of the grid: millimetres, whole pixels, or its millimetre default."""
    if mm is not None and px is not None:
        raise Refusal(f"use either {mm_name} or {px_name}, not both")
    if px is not None:
        return Width(px=px)
    return Width(mm=default_mm if mm is None else mm)


def _cmd_bars(args: argparse.Namespace) -> int:
    screen = _screen(args)
    return _emit(args, screen, build_bars(screen, _widths(args), args.lines))


def _cmd_grid(args: argparse.Namespace) -> int:
    screen = _screen(args)
    line = _one_width(args.line_mm, args.line_px, DEFAULT_GRID_LINE_MM,
                      "--line-mm", "--line-px")
    gap = _one_width(args.gap_mm, args.gap_px, DEFAULT_GRID_GAP_MM,
                     "--gap-mm", "--gap-px")
    figure = build_grid(screen, args.width_mm, args.height_mm, line, gap, args.direction)
    return _emit(args, screen, figure)


PLATE_LAYOUT_FLAGS = (
    ("plate_mm", "--plate-mm"), ("margin_mm", "--margin-mm"), ("grid_mm", "--grid-mm"),
    ("at", "--at"), ("widths_mm", "--widths-mm"), ("widths_px", "--widths-px"),
    ("lines", "--lines"), ("square_line_mm", "--square-line-mm"),
    ("square_line_px", "--square-line-px"), ("line_mm", "--line-mm"),
    ("line_px", "--line-px"), ("gap_mm", "--gap-mm"), ("gap_px", "--gap-px"),
    ("direction", "--direction"),
    #Everything about the printer and the output lives in [output] now (plan Б0).
    ("output", "-o"), ("template", "--template"), ("screen_px", "--screen-px"),
    ("pixel_um", "--pixel-um"), ("exposure_s", "--exposure-s"),
)
"""Flags that place figures the BUILT-IN way, or name the printer and the output.

Next to --config each of them is a second answer to a question the config already
answered, so each is refused BY NAME: a flag that is quietly ignored is the same lie as a
config key that is quietly ignored (plans К2 and Б0). The screen and the pixel are in
this list too: with a config they come from ``[output] template`` and nowhere else."""

PLATE_SUFFIXES = (".png", ".px6s")
"""A mask PNG or a printer file — nothing else: the suffix IS the choice of the output."""


def _refuse_layout_flags(args: argparse.Namespace) -> None:
    """The built-in layout keys and a config cannot both say where a figure lies."""
    given = [flag for name, flag in PLATE_LAYOUT_FLAGS
             if getattr(args, name, None) is not None]
    if given:
        raise Refusal(f"{', '.join(given)} cannot be given with --config: the config says "
                      f"which figures lie on the plate and where (one source of truth)")


def _cmd_plate(args: argparse.Namespace) -> int:
    """The built-in plate, or the plate a TOML config asks for — one compose path."""
    if args.config is not None:
        return _plate_from_config(args)
    if args.output is None:
        raise Refusal("an output path is mandatory: -o out/plate.png (or a --config that "
                      "names its own output in [output])")
    target = Path(args.output)
    suffix = target.suffix.lower()
    if suffix not in PLATE_SUFFIXES:
        raise Refusal(f"the output must end in .png (a mask) or .px6s (a printer file), "
                      f"got {target.name}")
    if suffix == ".px6s":
        raise Refusal("a plate .px6s needs --config: the exposure time lives in "
                      "[plate] exposure_s, and the layout that produces the layer is the "
                      "config's — one source of truth")
    printer = read_file(args.template) if args.template else None
    screen, _ = screen_for(args, printer)   # the built-in report stays as П5б printed it
    plate_w_mm, plate_h_mm = args.plate_mm or (PLATE_WIDTH_MM, PLATE_HEIGHT_MM)
    grid_w_mm, grid_h_mm = args.grid_mm or (PLATE_GRID_WIDTH_MM, PLATE_GRID_HEIGHT_MM)
    margin_mm = PLATE_MARGIN_MM if args.margin_mm is None else args.margin_mm
    lines = DEFAULT_LINES if args.lines is None else args.lines
    direction = "both" if args.direction is None else args.direction
    square_line = _one_width(args.square_line_mm, args.square_line_px,
                             DEFAULT_SQUARE_LINE_MM, "--square-line-mm", "--square-line-px")
    line = _one_width(args.line_mm, args.line_px, DEFAULT_GRID_LINE_MM,
                      "--line-mm", "--line-px")
    gap = _one_width(args.gap_mm, args.gap_px, DEFAULT_GRID_GAP_MM,
                     "--gap-mm", "--gap-px")
    placements, report = build_plate(
        screen, plate_w_mm=plate_w_mm, plate_h_mm=plate_h_mm, margin_mm=margin_mm,
        square_line=square_line, widths=_widths(args), lines=lines,
        grid_line=line, grid_gap=gap, grid_width_mm=grid_w_mm, grid_height_mm=grid_h_mm,
        direction=direction, at_mm=args.at)
    return _finish(args, screen, placements, report=report)


def _plate_from_config(args: argparse.Namespace) -> int:
    """The plate a config asks for: figures, marker, time, printer and outputs — all from it.

    ONE picture: `compose` runs once and BOTH files are written from it, because a PNG and
    a .px6s of one plate drawn twice could differ by a pixel, and then nobody knows which
    one was exposed. The report and the PNG chunk carry the config TEXT whole: a month
    later the file alone does not say what was exposed.
    """
    _refuse_layout_flags(args)      # -o, --template, --screen-px, --pixel-um are in the list
    config = load_plate_config(args.config)
    if config.output.px6s is not None and config.exposure_s is None:
        raise Refusal(f"{config.label}: [plate] has no 'exposure_s': "
                      f"{config.output.px6s} needs the exposure time, and next to --config "
                      f"the flag is not an option")
    printer = read_file(config.output.template)
    # The screen is the template's; the pixel may be MEASURED in [output] (rule of Г2) and
    # then the geometry changes while the file header keeps the template's number.
    flags = SimpleNamespace(screen_px=None, pixel_um=config.output.pixel_um)
    screen, pixel_line = screen_for(flags, printer)
    placements, report = build_config_plate(screen, config)
    image, placed = compose(screen, placements, mirror=args.mirror, invert=args.invert)
    lines = (pixel_line, *report, *placed)
    for line in lines:
        if line.startswith("warning: "):
            print(line, file=sys.stderr)
    print("\n".join(line for line in lines if not line.startswith("warning: ")))
    print(f"config, whole, as read from {config.label}:")
    for line in config.text.splitlines():
        print(f"  {line}")

    png = config.output.png
    if png is not None:
        existed = png.exists()      # asked BEFORE the write: after it the answer is yes
        written = write_mask(png, screen, lines, image, config_text=config.text)
        print(f"{'overwrote' if existed else 'Wrote'} {written}: "
              f"{screen.width_px} x {screen.height_px} px mask")
    px6s = config.output.px6s
    if px6s is not None:
        existed = px6s.exists()
        px6s.parent.mkdir(parents=True, exist_ok=True)
        written, writer_lines = write_file(config.output.template, image, px6s,
                                           config.exposure_s)
        print("\n".join(writer_lines))
        print(f"{'overwrote' if existed else 'Wrote'} {written}: "
              f"{screen.width_px} x {screen.height_px} px layer")
    return EXIT_OK


def _cmd_square(args: argparse.Namespace) -> int:
    """One side value for both axes; the core takes side_x and side_y (plan П5б)."""
    screen = _screen(args)
    if args.side_mm is not None and args.side_px is not None:
        raise Refusal("use either --side-mm or --side-px, not both")
    if args.side_px is not None:
        side_x_mm = args.side_px * screen.pixel_x_mm
        side_y_mm = args.side_px * screen.pixel_y_mm
    else:
        side_x_mm = side_y_mm = (DEFAULT_SQUARE_SIDE_MM if args.side_mm is None
                                 else args.side_mm)
    line = _one_width(args.line_mm, args.line_px, DEFAULT_SQUARE_LINE_MM,
                      "--line-mm", "--line-px")
    figure = build_square(screen, side_x_mm, side_y_mm, line)
    return _emit(args, screen, figure)


def _emit(args: argparse.Namespace, screen: Screen, figure) -> int:
    """One figure with its marker; placed by the same list path as a plate."""
    if args.marker:
        figure = add_marker(screen, figure)
    return _finish(args, screen, (place_figure(screen, figure, args.at),),
                   report=figure.report)


def _finish(args: argparse.Namespace, screen: Screen, placements, *,
            report: tuple[str, ...] = ()) -> int:
    """Compose the placements, write the PNG and print the report."""
    image, placed = compose(screen, placements, mirror=args.mirror, invert=args.invert)
    lines = (*report, *placed)
    target = write_mask(args.output, screen, lines, image)
    for line in lines:
        if line.startswith("warning: "):
            print(line, file=sys.stderr)
    print("\n".join(line for line in lines if not line.startswith("warning: ")))
    print(f"Wrote {target}: {screen.width_px} x {screen.height_px} px")
    return EXIT_OK


__all__ = ["add_parser"]
