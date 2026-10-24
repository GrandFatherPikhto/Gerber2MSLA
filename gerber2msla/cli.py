"""Command line entry point: ``gerber2msla <command> ...``.

The router only: the root parser, ``--version``, and the ONE-line refusal. The command
groups live next door — ``cli_masks.py`` draws masks, ``cli_px6s.py`` writes the printer
file (and reads it back), ``cli_board.py`` turns a board's Gerber into either of them.
Masks never move into the px6s module: the split is "masks here, write/dump there", not
the other way round.

Expected refusals (``masks.Refusal``) and unreadable printer files (``px6s.Px6sError``)
are printed as ONE line and return code 2, with no traceback: an unusable mask or template
is an answer, not a crash.

Messages are ASCII English, without i18n: the utility is small, and translations arrive
together with the Gerber input and the interface (rules: deepseek.md п.9).
"""
from __future__ import annotations

import argparse
import sys
from importlib.metadata import PackageNotFoundError, version

from . import cli_board, cli_masks, cli_px6s
from .masks import Refusal
from .px6s import Px6sError

PROG = "gerber2msla"
EXIT_OK = 0
EXIT_REFUSED = 2


def _version() -> str:
    """The installed version; a source checkout without metadata still runs."""
    try:
        return version(PROG)
    except PackageNotFoundError:
        return "unknown"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Expose photoresist on an MSLA printer: pixel-exact test masks and "
                    "one-layer printer files.")
    parser.add_argument("--version", action="version", version=f"{PROG} {_version()}")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    cli_masks.add_parser(commands)
    cli_px6s.add_parser(commands)
    cli_board.add_parser(commands)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        # No command is not an error: the help IS the answer.
        parser.print_help(file=sys.stdout)
        return EXIT_OK
    try:
        return args.handler(args)
    except (Refusal, Px6sError) as refusal:
        print(str(refusal), file=sys.stderr)
        return EXIT_REFUSED
