"""Command line entry point: ``gerber2msla <command> ...``.

Every command is a thin layer over the mask core: parse arguments, call one core
function, print the result. No geometry, no units and no file format are decided here.

`masks bars|grid` is COPIED from Gerber2LDI `tools/msla_tests.py` at commit 364fd28
(2026-10-23): the flags, their defaults, the report and the exit codes are the same; the
command is now a subcommand of this utility. The drawing layer lives in `masks.py`, the
patterns in `patterns.py`.

Expected refusals (`Refusal`) are printed as ONE line and return a non-zero code, with no
traceback: an unusable mask is an answer, not a crash. Warnings are lines on stderr —
never dialogs.

Messages are ASCII English, without i18n: the utility is small, and translations arrive
together with the Gerber input and the interface (rules: deepseek.md п.9).
"""
from __future__ import annotations

import argparse
import math
import sys
from importlib.metadata import PackageNotFoundError, version

from .masks import Refusal, Screen, add_marker, compose, write_mask
from .patterns import (DEFAULT_GRID_GAP_MM, DEFAULT_GRID_HEIGHT_MM, DEFAULT_GRID_LINE_MM,
                       DEFAULT_GRID_WIDTH_MM, DEFAULT_LINES, DEFAULT_SQUARE_LINE_MM,
                       DEFAULT_SQUARE_SIDE_MM, DEFAULT_WIDTHS_MM, DIRECTIONS, Width,
                       build_bars, build_grid, build_square)

PROG = "gerber2msla"
EXIT_OK = 0
EXIT_REFUSED = 2


def _version() -> str:
    """The installed version; a source checkout without metadata still runs."""
    try:
        return version(PROG)
    except PackageNotFoundError:
        return "unknown"


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

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Expose photoresist on an MSLA printer: pixel-exact test masks and "
                    "one-layer printer files.")
    parser.add_argument("--version", action="version", version=f"{PROG} {_version()}")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    masks = commands.add_parser(
        "masks", help="draw test masks in exact screen pixels",
        description="Draw test masks in exact screen pixels of the LCD.")
    kinds = masks.add_subparsers(dest="kind", metavar="PATTERN")
    kinds.required = True

    def common(kind: argparse.ArgumentParser) -> None:
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
    return parser


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
    """Marker, placement, PNG and the report — the same tail for every mask pattern."""
    if args.marker:
        figure = add_marker(screen, figure)
    image, placed = compose(screen, figure, args.at,
                            mirror=args.mirror, invert=args.invert)
    target = write_mask(args.output, screen, figure, image, placed)
    for line in figure.report:
        if line.startswith("warning: "):
            print(line, file=sys.stderr)
    print("\n".join(line for line in figure.report if not line.startswith("warning: ")))
    print("\n".join(placed))
    print(f"Wrote {target}: {screen.width_px} x {screen.height_px} px")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        # No command is not an error: the help IS the answer.
        parser.print_help(file=sys.stdout)
        return EXIT_OK
    try:
        return args.handler(args)
    except Refusal as refusal:
        print(str(refusal), file=sys.stderr)
        return EXIT_REFUSED
