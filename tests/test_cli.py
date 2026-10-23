"""The ROUTER: starts, prints help and version, and turns a refusal into one line.

The frame cells (П0 of the plan `plan_2026_10_23_png2px6s`) and what only
`gerber2msla/cli.py` promises. The masks command line moved to `tests/test_cli_masks.py`
and the write command line to `tests/test_cli_px6s.py` in the П2 fix: a module's cells
live in the file of that module, and a move is not a rewrite — the moved cells kept
their names and assertions.

This file keeps two promises of the router itself:

  * `test_every_subcommand_has_a_handler` (the NEW cell of П4) — a subcommand added to the
    tree without a handler is noticed here, not on the plate;
  * `test_a_refusal_is_one_line_and_code_two` (П2 fix) — an expected refusal is an answer,
    not a traceback: one line on stderr, code 2, nothing written. One row per KIND of
    refusal (a mask that cannot be drawn, a printer file that cannot be read), so that a
    mutation catching only one of the two is killed here.
"""
import argparse

import pytest
from PIL import Image

from gerber2msla.cli import build_parser, main


def test_no_command_prints_help(capsys):
    """No command is not an error: the help IS the answer."""
    assert main([]) == 0
    assert "usage: gerber2msla" in capsys.readouterr().out


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.startswith("gerber2msla ")


def test_an_unknown_command_is_a_usage_error(capsys):
    """argparse answers with its own usage line and code 2, not with a traceback."""
    with pytest.raises(SystemExit) as exc:
        main(["bogus"])
    assert exc.value.code == 2
    assert "usage: gerber2msla" in capsys.readouterr().err


def _leaf_commands(parser: argparse.ArgumentParser):
    """Every (name, parser) that has no subcommands of its own — a command to run."""
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for name, sub in action.choices.items():
            nested = list(_leaf_commands(sub))
            if nested:
                yield from nested
            else:
                yield name, sub


def test_every_subcommand_has_a_handler():
    """A command that parses but has no handler would exit without drawing anything."""
    leaves = list(_leaf_commands(build_parser()))
    assert leaves, "the CLI must have at least one command to run"
    for name, sub in leaves:
        assert callable(sub.get_default("handler")), f"subcommand {name!r} has no handler"


REFUSAL_ROWS = (
    ("mask", "use either --widths-mm or --widths-px, not both"),
    ("px6s", "not a px6s"),
)
"""The two expected kinds of refusal the router must answer in one line."""


@pytest.mark.parametrize("kind, expected", REFUSAL_ROWS)
def test_a_refusal_is_one_line_and_code_two(tmp_path, kind, expected, capsys):
    """A refusal is an answer: one line on stderr, code 2, no traceback, no file."""
    target = tmp_path / "out.bin"
    if kind == "mask":
        arguments = ["masks", "bars", "--screen-px", "240x120", "--pixel-um", "34.4x34.4",
                     "--widths-mm", "0.2", "--widths-px", "6", "-o", str(target)]
    else:
        mask = tmp_path / "mask.png"
        Image.new("L", (8, 8), 0).save(mask)
        template = tmp_path / "not-a.px6s"
        template.write_bytes(b"NOTAPX6S" + b"\x00" * 64)
        arguments = ["write", str(mask), "--template", str(template), "-o", str(target),
                     "--exposure-s", "25"]
    assert main(arguments) == 2
    err = capsys.readouterr().err
    assert expected in err, f"the refusal must say what is wrong: {err!r}"
    assert len(err.strip().splitlines()) == 1, f"one line, not a traceback: {err!r}"
    assert "Traceback" not in err
    assert not target.exists()
