"""The CLI: starts, prints help and version, and refuses what it cannot draw.

The frame cells (П0 of the plan `plan_2026_10_23_png2px6s`) and the command-line cells of
the mask tool, moved here from Gerber2LDI `tests/test_tools_msla.py` (364fd28) by П4:
flags and their exclusions, the mandatory screen and pixel, a refusal as ONE line without
a file left behind. Function names and assertions are the ORIGINAL ones; the command is
now `gerber2msla masks …`.

`test_every_subcommand_has_a_handler` is the NEW cell of П4: it holds the promise of this
file — a subcommand added to the tree without a handler is noticed here, not on the plate.
"""
import argparse

import pytest

from conftest import run_mask

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


@pytest.mark.parametrize("missing", ["--screen-px", "--pixel-um"])
def test_the_screen_and_the_pixel_are_mandatory(tmp_path, missing, screen_args,
                                                square_pixel_args):
    """No invented default: an unverified spec number is worse than a refusal."""
    given = square_pixel_args if missing == "--screen-px" else screen_args
    with pytest.raises(SystemExit) as exc:
        main(["masks", "grid", *given, "-o", str(tmp_path / "grid.png")])
    assert exc.value.code == 2


def test_both_forms_at_once_are_refused(tmp_path, screen_args, square_pixel_args, capsys):
    """Millimetres or pixels, never both: two answers to one question cannot be merged."""
    target = tmp_path / "mask.png"
    for arguments in (
        ["masks", "bars", *screen_args, *square_pixel_args, "--widths-mm", "0.2",
         "--widths-px", "6"],
        ["masks", "grid", *screen_args, *square_pixel_args, "--line-mm", "0.2",
         "--line-px", "6"],
        ["masks", "grid", *screen_args, *square_pixel_args, "--gap-mm", "0.15",
         "--gap-px", "4"],
    ):
        assert main([*arguments, "-o", str(target)]) == 2
        assert "not both" in capsys.readouterr().err
    assert not target.exists()


def test_grid_takes_its_line_and_gap_in_whole_pixels(tmp_path, screen_args, capsys):
    run_mask(tmp_path, "grid", *screen_args, "--pixel-um", "100x100",
             "--width-mm", "1", "--height-mm", "1", "--line-px", "3", "--gap-px", "1",
             "--at", "0,0", "--no-marker")
    captured = capsys.readouterr()
    assert "line: 3 px -> 300.0 um along X, 300.0 um along Y" in captured.out
    assert "gap: 1 px -> 100.0 um along X, 100.0 um along Y" in captured.out
    assert "is drawn as" not in captured.err
