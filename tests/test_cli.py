"""The CLI starts, prints help and version, and refuses an unknown command.

Cells of the plan `plan_2026_10_23_png2px6s` (П0, the skeleton). The mask commands and
their cells arrive with П4; this file keeps the command-line frame they plug into, so a
command added without a handler is noticed here.
"""
import pytest

from gerber2msla.cli import main


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
