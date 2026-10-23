"""The printer-file commands: ``gerber2msla write …`` and ``gerber2msla dump …``.

`write` is thin: read the mask PNG, hand it to `px6s_write.write_file`, print the report.
`dump` is the other direction: print what `px6s.read_file` already parsed and, on request,
save layer 0 as a PNG. Everything about the format lives in `px6s.py` and
`px6s_write.py`; nothing about geometry is decided here and no byte-level knowledge is
added — the format is described in `docs/format_px6s.md`.

Refusals are expected answers, printed by `cli.main` as ONE line with code 2: a mask of the
wrong size or mode, values other than 0/255, a template that is not a version-517 px6s, a
file that cannot be read at all. Masks never move back here.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
from PIL import Image

from .masks import Refusal
from .px6s import Px6sFile, read_file
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
    """Add the `write` and `dump` commands to the root subparsers."""
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

    dump_parser = commands.add_parser(
        "dump", help="print what a px6s says, and save its layer 0 as a PNG",
        description="read a printer file back: version, machine, resolution and pixel, "
                    "both exposure times, bottom layers and layer count, lifts and speeds, "
                    "block addresses")
    dump_parser.add_argument("file", help="px6s to read (version 517)")
    dump_parser.add_argument("-o", "--output", default=None,
                             help="save layer 0 here as an 8-bit grey PNG")
    dump_parser.set_defaults(handler=_cmd_dump)


def _cmd_write(args: argparse.Namespace) -> int:
    mask = _read_mask(args.mask)
    target, report = write_file(args.template, mask, args.output, args.exposure_s,
                                mirror_x=args.mirror_x)
    print("\n".join(report))
    print(f"Wrote {target}: {mask.shape[1]} x {mask.shape[0]} px mask")
    return EXIT_OK


def _dump_lines(printer: Px6sFile) -> list[str]:
    """The parsed numbers in words: the reader's fields, in the order a printer asks them."""
    mark, header, machine = printer.mark, printer.header, printer.machine
    addressed = sorted(mark.addresses.items(), key=lambda item: item[1])
    lines = [
        f"file: {printer.path}",
        f"version: {mark.version}; blocks: {mark.table_count}",
        (f"machine: {machine.name} ({machine.layer_image_format})" if machine
         else "machine: not in the file"),
        f"resolution: {header.resolution_x} x {header.resolution_y} px; "
        f"pixel {header.pixel_size_um:.2f} um",
        f"exposure: normal {header.exposure_s:.3f} s, bottom "
        f"{header.bottom_exposure_s:.3f} s, bottom layers {header.bottom_layers:g}, "
        f"layers {printer.layer_count}",
        f"lift: height {header.lift_height_mm:.3f} mm at {header.lift_speed_mm_s:.3f} mm/s; "
        f"retract {header.retract_speed_mm_s:.3f} mm/s",
        "light pwm: not stored in px6s v517 (the printer profile says LightPWM_255; the "
        "file has no brightness field)",
    ]
    for index, layer in enumerate(printer.layers):
        lines.append(
            f"layer {index}: @ {layer.data_address}, {layer.data_length} bytes, "
            f"lift {layer.lift_height_mm:.3f} mm at {layer.lift_speed_mm_s:.3f} mm/s, "
            f"exposure {layer.exposure_s:.3f} s, nonzero {layer.non_zero_pixels} px")
    lines.append("blocks: " + ", ".join(f"{name}@{address}"
                                        for name, address in addressed))
    return lines


def _cmd_dump(args: argparse.Namespace) -> int:
    """Print the file's own numbers; save layer 0 only when asked to."""
    printer = read_file(args.file)
    print("\n".join(_dump_lines(printer)))
    if args.output is not None:
        image = printer.layer_image(0)
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(image).save(target)
        print(f"Wrote {target}: {image.shape[1]} x {image.shape[0]} px layer 0")
    return EXIT_OK


__all__ = ["add_parser"]
