"""The ``board`` command group: a Gerber layer (and its holes) → a mask or a printer file.

    gerber2msla board F_Cu.gbr [--drill PTH.drl ...] [--outline Edge_Cuts.gbr]
        (--template T.px6s [--pixel-um PXxPY] | --screen-px WxH --pixel-um PXxPY)
        [--exposure-s 25] [--at X,Y] [--mirror] [--invert] [--marker]
        -o out/top.png | -o out/top.px6s

    gerber2msla board --config board.toml       # the whole job is in the file

A CONFIG NAMES THE WHOLE JOB (plan Б2): the copper of every side, its drills, the shared
frame, its mirror and its time, the printer's template and the output folder — so every
flag that would answer one of those questions again is REFUSED BY NAME next to
``--config``, including the positional copper: one source of truth, no silent winner. The
work itself is `board_files.write_board`; this file only parses and prints.

SCREEN AND PIXEL (decision of 24.10, after Г1): the resolution is ALWAYS the printer's, so
with ``--template`` it comes from the file and ``--screen-px`` is refused — "the template
fixes the screen". The pixel is two different things and they are kept apart:

  * the pixel STORED IN THE FILE HEADER is a machine field: it is copied from the template
    byte for byte and never changes;
  * ``--pixel-um`` is a MEASUREMENT of how many screen pixels a millimetre of the board
    takes. It changes the geometry only, and it may be not square (34 x 30 is exactly what
    the square test of П5а exists to measure).

So the report says which pixel was used and what the header keeps:
``pixel: 34.00 x 30.00 um (measured, --pixel-um; the file header keeps 34.00)``. Without
``--template`` the pixel and the screen are mandatory, as in ``masks``, and the PNG carries
them (it is the only thing that can).

The function itself is `screen_choice.screen_for` (plan К2): ``masks plate --config`` asks
the same question, and a second copy of this answer is where two commands would start to
disagree about the same template.

Everything about geometry lives in `board.py`; placement, the mirror, the polarity and the
marker are `masks.compose`/`add_marker`; the printer file is the П2 writer and nothing else.
The CLI below only parses, chooses the screen, and prints.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from .board import build_board
from .board_config import load_board_config
from .board_files import write_board
from .cli_masks import _micrometres_pair, _millimetres_pair, _pixels_pair
from .cli_px6s import _positive_seconds
from .masks import Refusal, add_marker, compose, place_figure, write_mask
from .px6s import read_file
from .px6s_write import write_file
from .screen_choice import screen_for

EXIT_OK = 0

SUFFIXES = (".png", ".px6s")
"""A mask PNG or a printer file — nothing else: the suffix IS the choice of the output."""

BOARD_FLAGS = (
    ("copper", "the copper argument"),
    ("output", "-o/--output"),
    ("drill", "--drill"),
    ("outline", "--outline"),
    ("template", "--template"),
    ("screen_px", "--screen-px"),
    ("pixel_um", "--pixel-um"),
    ("exposure_s", "--exposure-s"),
    ("at", "--at"),
    ("mirror", "--mirror"),
    ("invert", "--invert"),
    ("marker", "--marker"),
)
"""Every flag that answers a question the config already answers — refused by name."""


# ───────────────────────────── the command ────────────────────────────────

def add_parser(commands) -> None:
    """Add the `board` command to the root subparsers."""
    parser = commands.add_parser(
        "board", help="a Gerber layer (and its holes) as a mask or a printer file",
        description="a board's copper, its drill holes and its outline → the screen's pixels: "
                    "a PNG mask, or a one-layer px6s written by the printer's own template")
    parser.add_argument("--config", default=None, metavar="FILE",
                        help="a TOML config that says the whole job: every side's copper, the "
                             "drills, the shared frame, the times, the template and the folder")
    parser.add_argument("copper", nargs="?", default=None,
                        help="Gerber copper layer (F_Cu or B_Cu); not with --config")
    parser.add_argument("--drill", action="append", default=[], metavar="FILE",
                        help="Excellon drill file; repeat it for PTH and NPTH — every hole is "
                             "subtracted from the copper")
    parser.add_argument("--outline", default=None, metavar="FILE",
                        help="Edge_Cuts Gerber: its bounding box is the frame, the only way the "
                             "top and the bottom of one board share it")
    parser.add_argument("--template", default=None, metavar="FILE",
                        help="one-layer px6s of this printer: the screen, the pixel of the file "
                             "header and the machine blocks")
    parser.add_argument("--screen-px", type=_pixels_pair, default=None, metavar="WxH",
                        help="the screen in whole pixels; not with --template")
    parser.add_argument("--pixel-um", type=_micrometres_pair, default=None, metavar="PXxPY",
                        help="the measured screen pixel; may be not square. Changes the GEOMETRY "
                             "only: the pixel in the file header stays the template's")
    parser.add_argument("--exposure-s", type=_positive_seconds, default=None,
                        help="exposure for BOTH the normal and the bottom layer, in seconds; "
                             "needed for a .px6s")
    parser.add_argument("--at", type=_millimetres_pair, default=None, metavar="X,Y",
                        help="top-left corner of the board in mm from the top-left pixel "
                             "(default: centred)")
    parser.add_argument("--mirror", action="store_true",
                        help="reflect the whole picture along X (off by default: the utility "
                             "does not mirror on its own)")
    parser.add_argument("--invert", action="store_true",
                        help="white becomes the gaps (the resist keeps what was NOT lit)")
    parser.add_argument("--marker", action="store_true",
                        help="put the letter F in the top-left corner (off by default: a board "
                             "cut to its own size has no room for it)")
    parser.add_argument("-o", "--output", default=None,
                        help="out/top.png for a mask, out/top.px6s for the printer file; "
                             "not with --config, whose [output] folder it takes")
    parser.set_defaults(handler=_cmd_board)


def _refuse_board_flags(args) -> None:
    """Every flag whose question the config already answers is refused BY NAME."""
    given = [flag for name, flag in BOARD_FLAGS if getattr(args, name, None)]
    if given:
        raise Refusal(f"{', '.join(given)} cannot be given with --config: the config names "
                      f"the copper, the drills, the frame, the sides, the times, the printer "
                      f"and the output folder (one source of truth)")


def _board_from_config(args) -> int:
    """The board a config asks for: sides, frame, times, printer and folder — all from it."""
    _refuse_board_flags(args)
    config = load_board_config(args.config)
    printer = read_file(config.output.template)
    # The screen is the template's; the pixel may be MEASURED in [output] (rule of Г2), and
    # then the geometry changes while the file header keeps the template's number.
    flags = SimpleNamespace(screen_px=None, pixel_um=config.output.pixel_um)
    screen, pixel_line = screen_for(flags, printer)
    lines = write_board(screen, config, pixel_line=pixel_line)
    # A warning is indented inside its side's block, so it is found by its own text, and it
    # goes to stderr: the report file still keeps it where the side's numbers are.
    for line in lines:
        if line.lstrip().startswith("warning: "):
            print(line.strip(), file=sys.stderr)
    print("\n".join(line for line in lines if not line.lstrip().startswith("warning: ")))
    return EXIT_OK


def _cmd_board(args) -> int:
    """Build the figure, place it, write it — and say where its pixel came from."""
    if args.config is not None:
        return _board_from_config(args)
    if args.copper is None:
        raise Refusal("the copper layer is mandatory: gerber2msla board F_Cu.gbr -o out/top.png "
                      "(or a --config whose [[side]] names its own copper)")
    if args.output is None:
        raise Refusal("an output path is mandatory: -o out/top.png (or a --config that names "
                      "its own folder in [output])")
    target = Path(args.output)
    suffix = target.suffix.lower()
    if suffix not in SUFFIXES:
        raise Refusal(f"the output must end in .png (a mask) or .px6s (a printer file), "
                      f"got {target.name}")

    printer = read_file(args.template) if args.template else None
    if suffix == ".px6s":
        if printer is None:
            raise Refusal("a .px6s needs --template: the machine blocks come from the real "
                          "printer file, not from a guess")
        if args.exposure_s is None:
            raise Refusal("a .px6s needs --exposure-s: one layer, its own exposure time")

    screen, pixel_line = screen_for(args, printer)
    figure = build_board(screen, args.copper, drills=args.drill, outline=args.outline)
    if args.marker:
        figure = add_marker(screen, figure)

    image, placed = compose(screen, [place_figure(screen, figure, args.at)],
                            mirror=args.mirror, invert=args.invert,
                            polarity_what="the copper")
    # The provenance goes INTO the figure's report, and the figure's report is what
    # `write_mask` puts into the PNG chunk: a mask file then says which pixel drew it.
    # `masks` is not touched — its own report stays what Gerber2LDI printed, byte for byte.
    report = (pixel_line, *figure.report)
    lines = (*report, *placed)
    for line in lines:
        if line.startswith("warning: "):
            print(line, file=sys.stderr)
    print("\n".join(line for line in lines if not line.startswith("warning: ")))

    if suffix == ".png":
        written = write_mask(target, screen, report, image)
        print(f"Wrote {written}: {screen.width_px} x {screen.height_px} px mask")
        return EXIT_OK

    written, report = write_file(args.template, image, target, args.exposure_s)
    print("\n".join(report))
    print(f"Wrote {written}: {screen.width_px} x {screen.height_px} px layer")
    return EXIT_OK


__all__ = ["add_parser"]
