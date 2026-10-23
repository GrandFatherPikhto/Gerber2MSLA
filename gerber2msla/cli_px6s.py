"""The printer-file command: ``gerber2msla write --template T.px6s mask.png -o out.px6s``.

The command line is thin: read the mask PNG, hand it to `px6s_write.write_file`, print the
report. Everything about the format and the template lives in `px6s_write.py` and
`px6s.py`; nothing about geometry is decided here.

Refusals are expected answers, printed by `cli.main` as ONE line with code 2: a mask of the
wrong size or mode, values other than 0/255, a template that is not a version-517 px6s.
The dump command (П3) will join this module — masks never move back here.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
from PIL import Image

from .masks import Refusal
from .px6s_write import write_file

EXIT_OK = 0


def _positive_seconds(text: str) -> float:
    """argparse type: a finite, positive exposure time in seconds."""
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a number of seconds, got {text!r}") from None
    if not math.isfinite(value) or value <= 0.0:
        raise argparse.ArgumentTypeError(f"expected a positive time in seconds, got {text!r}")
    return value


def _read_mask(path: str | Path) -> np.ndarray:
    """The mask PNG as an array; the mode and the size are the operator's answers."""
    try:
        image = Image.open(path)
        image.load()
    except OSError as error:
        raise Refusal(f"cannot read the mask {path}: {error.strerror or error}") from None
    if image.mode != "L":
        raise Refusal(f"the mask must be mode L (8-bit grey), got {image.mode}: "
                      f"{image.size[0]} x {image.size[1]} px")
    return np.array(image)


def add_parser(commands: argparse._SubParsersAction) -> None:
    """Add the `write` command to the root subparsers."""
    write_parser = commands.add_parser(
        "write", help="write a one-layer px6s from a mask, by a real template",
        description="write a one-layer printer file: the mask becomes the layer, the "
                    "template's machine blocks stay byte for byte")
    write_parser.add_argument("mask", help="mask PNG, exactly the template's resolution, "
                                           "mode L, 0/255")
    write_parser.add_argument("--template", required=True,
                              help="one-layer px6s of this printer, version 517")
    write_parser.add_argument("-o", "--output", required=True, help="output px6s")
    write_parser.add_argument("--exposure-s", type=_positive_seconds, required=True,
                              help="exposure for BOTH the normal and the bottom layer, "
                                   "in seconds")
    write_parser.add_argument("--mirror-x", action="store_true",
                              help="reflect the mask along X before encoding (off by "
                                   "default: the utility does not mirror on its own)")
    write_parser.set_defaults(handler=_cmd_write)


def _cmd_write(args: argparse.Namespace) -> int:
    mask = _read_mask(args.mask)
    target, report = write_file(args.template, mask, args.output, args.exposure_s,
                                mirror_x=args.mirror_x)
    print("\n".join(report))
    print(f"Wrote {target}: {mask.shape[1]} x {mask.shape[0]} px mask")
    return EXIT_OK


__all__ = ["add_parser"]
