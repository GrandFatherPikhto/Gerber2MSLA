"""Command line entry point: ``gerber2msla <command> ...``.

Every command is a thin layer over the mask core: parse arguments, call one function,
print the result. No geometry, no units and no file format are decided here.

Expected refusals are printed as ONE line and return a non-zero code, with no traceback:
an unusable mask is an answer, not a crash. Warnings are lines on stderr.

Messages are ASCII English, without i18n: the utility is small, and translations arrive
together with the Gerber input and the interface (rules: deepseek.md п.9).
"""
from __future__ import annotations

import argparse
import sys
from importlib.metadata import PackageNotFoundError, version

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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        # No command yet: the help IS the answer (same as Gerber2LDI's CLI).
        parser.print_help(file=sys.stdout)
        return EXIT_OK
    return handler(args)
