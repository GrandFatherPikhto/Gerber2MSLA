"""The `masks` command line: mandatory numbers, exclusions, defaults, wiring.

These cells moved out of `tests/test_cli.py` in the П2 fix, unchanged: a module's cells
live in the file of that module (`gerber2msla/cli_masks.py`), the same way the router cells
stay in `tests/test_cli.py`. Function names and assertions are the ORIGINAL ones from
Gerber2LDI `tests/test_tools_msla.py` (364fd28); the command is `gerber2msla masks …`.

A move is not a rewrite: `git diff --color-moved` shows these cells carried over.
"""
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from conftest import pixels, run_mask

from gerber2msla.cli import build_parser, main
from gerber2msla.px6s import read_file


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


# ─────────────── wiring of the command line (plan П5а, new cells) ──────────

def test_a_command_group_without_a_pattern_is_a_usage_error(capsys):
    """`masks` alone is a usage error, not a silent exit 0 with help."""
    with pytest.raises(SystemExit) as exc:
        main(["masks"])
    assert exc.value.code == 2
    assert "usage: gerber2msla" in capsys.readouterr().err


def test_at_places_the_figure_and_the_report_says_where(tmp_path, screen_args,
                                                        rect_pixel_args, capsys):
    """The flag must reach `compose`, not merely be parsed."""
    run_mask(tmp_path, "square", *screen_args, *rect_pixel_args, "--side-mm", "2",
             "--line-mm", "0.2", "--at", "1,1", "--no-marker")
    assert "at 1.000, 1.000 mm from the top-left pixel" in capsys.readouterr().out


def test_the_mask_defaults_are_marker_on_and_offs_off():
    """The report must not need a flag to be honest: the F is on, mirror and invert are off."""
    args = build_parser().parse_args(
        ["masks", "bars", "--screen-px", "240x120", "--pixel-um", "34.4x34.4",
         "-o", "mask.png"])
    assert args.marker is True
    assert args.mirror is False
    assert args.invert is False
    assert args.at is None


def test_both_square_forms_at_once_are_refused(tmp_path, screen_args, square_pixel_args,
                                                capsys):
    """The side and the line are millimetres OR whole pixels, never both."""
    target = tmp_path / "square.png"
    for arguments in (
        ["masks", "square", *screen_args, *square_pixel_args, "--side-mm", "2",
         "--side-px", "40"],
        ["masks", "square", *screen_args, *square_pixel_args, "--line-mm", "0.2",
         "--line-px", "6"],
    ):
        assert main([*arguments, "-o", str(target)]) == 2
        assert "not both" in capsys.readouterr().err
    assert not target.exists()


def test_side_px_reaches_the_square_builder(tmp_path, screen_args, rect_pixel_args,
                                            capsys):
    """The flag is parsed AND used: 40 px, not a fallback to the 100 mm default."""
    run_mask(tmp_path, "square", *screen_args, *rect_pixel_args, "--side-px", "40",
             "--line-px", "2", "--at", "0,0", "--no-marker")
    out = capsys.readouterr().out
    assert "drawn: 40 x 40 px" in out
    assert "1.376 x 1.200 mm" in out, "one count, two physical sides"


def test_plate_mm_reaches_the_layout(tmp_path, capsys):
    """The plate size is parsed AND used: 20 x 16 mm on the plate line, not the default."""
    run_mask(tmp_path, "plate", "--screen-px", "1200x900", "--pixel-um", "34.4x34.4",
             "--plate-mm", "20x16", "--margin-mm", "1", "--widths-mm", "0.2",
             "--lines", "1", "--grid-mm", "5x5", "--line-mm", "0.1", "--gap-mm", "0.1")
    assert "plate: 20.000 x 16.000 mm" in capsys.readouterr().out


# ───────────────────── plate from a config (plan К2) ──────────────────────

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
TEMPLATE = ROOT / "tests" / "data" / "01_test02.px6s"
SCREEN_ARGS = ("--screen-px", "5760x3600", "--pixel-um", "34x34")
"""The real printer screen: the oracle is about PIXELS, so it runs on the real numbers."""


def _example(name: str) -> str:
    return str(EXAMPLES / name)


def test_the_example_reproduces_the_built_in_plate_pixel_for_pixel(tmp_path, capsys):
    """The config says what the code draws: same pixels; only the text chunks differ."""
    built_in = pixels(run_mask(tmp_path, "plate", *SCREEN_ARGS, name="built_in.png"))
    from_config = pixels(run_mask(tmp_path, "plate", "--config",
                                 _example("plate_70x78.toml"), *SCREEN_ARGS,
                                 name="from_config.png"))
    capsys.readouterr()
    assert np.array_equal(built_in, from_config), \
        "the example IS the built-in plate; if this fails, one of the two is wrong"


def test_the_config_lands_in_its_own_utf8_chunk_whole(tmp_path):
    """Russian comments are the operator's: the chunk is iTXt, and it reads back equal."""
    config = tmp_path / "plate.toml"
    text = ("# комментарий по-русски: пластина тестовая\n"
            "[plate]\nwidth_mm = 20\nheight_mm = 16\n\n"
            "[[figure]]\nkind = \"square\"\nat_mm = [1, 1]\nsize_mm = [18, 14]\n"
            "line_px = 6\n")
    config.write_text(text, encoding="utf-8")
    target = run_mask(tmp_path, "plate", "--config", str(config),
                      "--screen-px", "1200x900", "--pixel-um", "34.4x34.4",
                      name="config.png")
    with Image.open(target) as image:
        assert image.text["plate_config"] == text, "byte for byte, comments and all"
        assert "msla_tests" in image.text, "the report chunk is still there"
        assert "width_mm = 20" not in image.text["msla_tests"], \
            "the config body has its own chunk; it is not doubled into the report"


def test_the_px6s_takes_its_time_from_the_config(tmp_path, capsys):
    """`[plate] exposure_s` is the one source of truth: both fields, one bottom layer."""
    target = tmp_path / "plate.px6s"
    assert main(["masks", "plate", "--config", _example("plate_70x78.toml"),
                 "--template", str(TEMPLATE), "-o", str(target)]) == 0
    header = read_file(target).header
    assert header.exposure_s == 25.0, "the normal time"
    assert header.bottom_exposure_s == 25.0, "and the bottom one: layer 0 IS the bottom"
    assert header.bottom_layers == 1
    assert "exposure: 25 s from [plate] exposure_s" in capsys.readouterr().out


@pytest.mark.parametrize("flags", [
    ("--plate-mm", "70x78"), ("--at", "2,2"), ("--widths-mm", "0.2"), ("--lines", "3"),
    ("--grid-mm", "30x30"), ("--direction", "both"), ("--margin-mm", "2"),
    ("--square-line-mm", "0.2"), ("--line-mm", "0.2"), ("--gap-mm", "0.2"),
], ids=lambda flags: flags[0])
def test_a_built_in_layout_flag_next_to_the_config_is_refused_by_name(tmp_path, capsys,
                                                                     flags):
    """The config says what lies where: a second answer is refused, never ignored."""
    target = tmp_path / "plate.png"
    code = main(["masks", "plate", "--config", _example("plate_70x78.toml"),
                 *flags, *SCREEN_ARGS, "-o", str(target)])
    assert code == 2
    err = capsys.readouterr().err
    assert flags[0] in err and "--config" in err
    assert not target.exists()


def test_a_second_exposure_time_in_the_flags_is_refused(tmp_path, capsys):
    """One source of truth: the flag and `[plate] exposure_s` cannot both name the time."""
    code = main(["masks", "plate", "--config", _example("plate_70x78.toml"),
                 "--exposure-s", "20", "--template", str(TEMPLATE),
                 "-o", str(tmp_path / "plate.px6s")])
    assert code == 2
    err = capsys.readouterr().err
    assert "--exposure-s" in err and "one source of truth" in err


def test_a_px6s_without_the_time_in_the_config_is_refused_with_the_key(tmp_path, capsys):
    """The refusal names the KEY that is missing, not just the file."""
    config = tmp_path / "notime.toml"
    config.write_text("[plate]\nwidth_mm = 20\nheight_mm = 16\n\n[[figure]]\n"
                      "kind = \"square\"\nat_mm = [1, 1]\nsize_mm = [18, 14]\n"
                      "line_px = 6\n", encoding="utf-8")
    code = main(["masks", "plate", "--config", str(config), "--template", str(TEMPLATE),
                 "-o", str(tmp_path / "plate.px6s")])
    assert code == 2
    assert "'exposure_s'" in capsys.readouterr().err


def test_a_plate_px6s_needs_the_config(tmp_path, capsys):
    """Without a config there is no exposure time to write, and no layout to explain it."""
    code = main(["masks", "plate", *SCREEN_ARGS, "-o", str(tmp_path / "plate.px6s")])
    assert code == 2
    assert "needs --config" in capsys.readouterr().err


def test_a_broken_config_is_one_line_and_code_two(tmp_path, capsys):
    """The one-line refusal of the whole utility, not a traceback from tomllib."""
    config = tmp_path / "typo.toml"
    config.write_text("[plate]\nwidth_mm = 70\nwidht_mm = 78\n\n[[figure]]\n"
                      "kind = \"square\"\nat_mm = [1, 1]\nsize_mm = [18, 14]\n"
                      "line_px = 6\n", encoding="utf-8")
    code = main(["masks", "plate", "--config", str(config), *SCREEN_ARGS,
                 "-o", str(tmp_path / "plate.png")])
    assert code == 2
    err = capsys.readouterr().err.strip()
    assert "\n" not in err, f"a refusal is ONE line, got: {err!r}"
    assert "'widht_mm'" in err


def test_the_report_names_the_plate_the_figures_and_the_time(tmp_path, capsys):
    """The report is the operator's table: where each figure lies, in mm and in px."""
    run_mask(tmp_path, "plate", "--config", _example("plate_70x78_patches.toml"),
             *SCREEN_ARGS, name="patches.png")
    out = capsys.readouterr().out
    assert "plate: 70.000 x 78.000 mm" in out
    assert "centred on the 5760 x 3600 px screen" in out
    assert "figure patches #2: 632 x 1308 px" in out, \
        "two 294 px squares and a 44 px gap across; four 294 px rows and three 44 px gaps down"
    assert "from the plate's top-left corner" in out
    assert "exposure: 25 s from [plate] exposure_s" in out
    assert "config, whole, as read from" in out, "the config text is part of the report"


def test_the_patches_example_builds_with_its_rows_in_the_order_written(tmp_path, capsys):
    """The second example is a real plate: four rows, 0.05 mm at the top, 0.20 at the bottom."""
    run_mask(tmp_path, "plate", "--config", _example("plate_70x78_patches.toml"),
             *SCREEN_ARGS, name="patches_rows.png")
    out = capsys.readouterr().out
    assert "pattern: patches, 4 rows" in out
    assert "row 1: 0.050 mm" in out and "row 4: 0.200 mm" in out
