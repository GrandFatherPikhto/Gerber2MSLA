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


@pytest.fixture(autouse=True)
def _working_directory_inside_tmp(tmp_path, monkeypatch):
    """Every cell runs with the working directory INSIDE `tmp_path` (rule of 25.10).

    No cell asks for a particular working directory: a config's paths count from the
    CONFIG's own folder. A mutant of that rule, however, resolves them from the cwd and
    writes its output there — so the cwd must be a folder pytest deletes, never the
    repository. The harness proves it after every mutation (`git status --porcelain`).
    """
    folder = tmp_path / "cwd"
    folder.mkdir(exist_ok=True)
    monkeypatch.chdir(folder)


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


# ────────────── plate from a config: the output lives in [output] (К2, Б0) ─────────────

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
TEMPLATE = ROOT / "tests" / "data" / "01_test02.px6s"
SCREEN_ARGS = ("--screen-px", "5760x3600", "--pixel-um", "34x34")
"""The real printer screen, for the BUILT-IN path and the oracle: pixels, not millimetres."""

SQUARE_BODY = ('[plate]\nwidth_mm = 20\nheight_mm = 16\nexposure_s = 25\n\n'
               '[[figure]]\nkind = "square"\nat_mm = [1, 1]\nsize_mm = [18, 14]\n'
               'line_px = 6\n')


def _config(tmp_path: Path, body: str = SQUARE_BODY, *, name: str = "plate.toml",
            template: str | None = None, pixel_um: str | None = None,
            px6s: str | None = "plate.px6s", png: str | None = None) -> Path:
    """A config whose [output] writes INTO tmp_path; its paths are relative to the file."""
    lines = ["[output]", f'template = "{TEMPLATE if template is None else template}"']
    if pixel_um is not None:
        lines.append(f"pixel_um = {pixel_um}")
    if px6s is not None:
        lines.append(f'px6s = "{px6s}"')
    if png is not None:
        lines.append(f'png = "{png}"')
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n\n" + body, encoding="utf-8")
    return path


def _run_config(tmp_path: Path, body: str = SQUARE_BODY, **kwargs) -> None:
    """`masks plate --config` with no -o: the output is the config's business (plan Б0)."""
    config = _config(tmp_path, body, **kwargs)
    assert main(["masks", "plate", "--config", str(config)]) == 0


def _example_in(tmp_path: Path, name: str) -> Path:
    """The example config with its [output] paths redirected into tmp_path.

    The example itself writes to `../out/` — that is its job; a cell must not leave files
    in the repository, and `-o` can no longer redirect it (plan Б0).
    """
    text = (EXAMPLES / name).read_text(encoding="utf-8")
    text = text.replace('"../tests/data/01_test02.px6s"', f'"{TEMPLATE}"')
    text = text.replace('"../out/', f'"{tmp_path}/')
    target = tmp_path / name
    target.write_text(text, encoding="utf-8")
    return target


# ───────────────────────────────── the oracle ─────────────────────────────────

def test_the_example_reproduces_the_built_in_plate_pixel_for_pixel(tmp_path, capsys):
    """The config says what the code draws: same pixels; only the text chunks differ."""
    built_in = pixels(run_mask(tmp_path, "plate", *SCREEN_ARGS, name="built_in.png"))
    config = _example_in(tmp_path, "plate_70x78.toml")
    assert main(["masks", "plate", "--config", str(config)]) == 0
    capsys.readouterr()
    assert np.array_equal(built_in, pixels(tmp_path / "plate_70x78.png")), \
        "the example IS the built-in plate; if this fails, one of the two is wrong"


# ─────────────────────────── [output]: where and what ───────────────────────────

def test_the_output_paths_count_from_the_config_file(tmp_path, monkeypatch, capsys):
    """A config moved next to its Gerbers cannot be broken by a `cd` (plan Б0)."""
    config = _config(tmp_path / "cfg", px6s="deep/plate.px6s")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert main(["masks", "plate", "--config", str(config)]) == 0
    written = tmp_path / "cfg" / "deep" / "plate.px6s"
    assert written.exists(), "the directory from the config was created, not the cwd"
    assert f"Wrote {written}" in capsys.readouterr().out


def test_a_config_can_write_only_a_png(tmp_path, capsys):
    """`png` without `px6s` is a plate to look at, not to expose."""
    _run_config(tmp_path, png="only.png", px6s=None)
    assert (tmp_path / "only.png").exists()
    assert not (tmp_path / "plate.px6s").exists(), "no .px6s was asked for"
    assert "px mask" in capsys.readouterr().out


def test_a_config_can_write_only_the_px6s(tmp_path, capsys):
    """The other way round: a printer file and no PNG."""
    _run_config(tmp_path, px6s="only.px6s", png=None)
    assert (tmp_path / "only.px6s").exists()
    assert not (tmp_path / "only.png").exists()
    assert "px layer" in capsys.readouterr().out


def test_both_files_come_out_of_one_picture(tmp_path, capsys):
    """ONE `compose`, two files: drawn twice they could differ by a pixel (plan Б0)."""
    _run_config(tmp_path, px6s="both.px6s", png="both.png")
    capsys.readouterr()
    png_array = pixels(tmp_path / "both.png")
    layer = np.array(read_file(tmp_path / "both.px6s").layer_image(0))
    assert np.array_equal(png_array, layer), \
        "the PNG and the layer of one call are one picture, not two"


def test_an_output_with_neither_px6s_nor_png_is_refused(tmp_path, capsys):
    """A config that writes nothing does not say what it is for."""
    config = _config(tmp_path, px6s=None, png=None)
    assert main(["masks", "plate", "--config", str(config)]) == 2
    assert "writes nothing" in capsys.readouterr().err


def test_a_missing_template_file_is_refused_with_its_key_and_path(tmp_path, capsys):
    config = _config(tmp_path, template=str(tmp_path / "absent.px6s"))
    assert main(["masks", "plate", "--config", str(config)]) == 2
    err = capsys.readouterr().err
    assert "'template'" in err and "absent.px6s" in err


@pytest.mark.parametrize("flags", [
    ("-o", "x.png"), ("--template", "t.px6s"), ("--screen-px", "100x100"),
    ("--pixel-um", "34x34"), ("--exposure-s", "20"),
    ("--plate-mm", "70x78"), ("--at", "2,2"), ("--widths-mm", "0.2"), ("--lines", "3"),
    ("--grid-mm", "30x30"), ("--direction", "both"), ("--margin-mm", "2"),
    ("--square-line-mm", "0.2"), ("--line-mm", "0.2"), ("--gap-mm", "0.2"),
], ids=lambda flags: flags[0])
def test_a_flag_next_to_the_config_is_refused_by_name(tmp_path, capsys, flags):
    """Everything about the printer and the output is in [output]: a flag is a second
    answer, and a flag that is quietly ignored is the same lie as a quietly ignored key."""
    config = _config(tmp_path)
    code = main(["masks", "plate", "--config", str(config), *flags])
    assert code == 2
    err = capsys.readouterr().err
    assert flags[0] in err and "--config" in err
    assert not (tmp_path / "plate.px6s").exists(), "nothing is written on a refusal"


def test_an_overwrite_says_overwrote(tmp_path, capsys):
    """A generated file is written again every time; the report must not pretend it is new."""
    config = _config(tmp_path)
    assert main(["masks", "plate", "--config", str(config)]) == 0
    assert "Wrote" in capsys.readouterr().out
    assert main(["masks", "plate", "--config", str(config)]) == 0
    assert "overwrote" in capsys.readouterr().out


def test_pixel_um_changes_the_geometry_and_leaves_the_header_alone(tmp_path, capsys):
    """A MEASUREMENT, as in Г2: the drawing follows it, the file header keeps the template's."""
    _run_config(tmp_path, name="plain.toml", px6s="plain.px6s")
    plain = read_file(tmp_path / "plain.px6s")
    plain_report = capsys.readouterr().out
    _run_config(tmp_path, name="measured.toml", px6s="measured.px6s",
                pixel_um="[34.0, 30.0]")
    measured = read_file(tmp_path / "measured.px6s")
    measured_report = capsys.readouterr().out
    assert measured.header.pixel_size_um == 34.0, \
        "the header is the template's, whatever was measured"
    assert "measured, --pixel-um; the file header keeps 34.00" in measured_report
    assert "template header" in plain_report
    assert not np.array_equal(np.array(plain.layer_image(0)),
                              np.array(measured.layer_image(0))), \
        "a 34 x 30 um pixel draws the same plate with a different geometry"


# ───────────────────────────── the config as a record ─────────────────────────────

def test_the_config_lands_in_its_own_utf8_chunk_whole(tmp_path):
    """Russian comments are the operator's: the chunk is iTXt, and it reads back equal."""
    text = ("# комментарий по-русски: пластина тестовая\n" + SQUARE_BODY)
    config = _config(tmp_path, body="", png="config.png")
    config.write_text(config.read_text(encoding="utf-8") + text, encoding="utf-8")
    assert main(["masks", "plate", "--config", str(config)]) == 0
    with Image.open(tmp_path / "config.png") as image:
        assert image.text["plate_config"] == config.read_text(encoding="utf-8"), \
            "byte for byte, comments and all"
        assert "msla_tests" in image.text, "the report chunk is still there"
        assert "width_mm = 20" not in image.text["msla_tests"], \
            "the config body has its own chunk; it is not doubled into the report"


def test_the_px6s_takes_its_time_from_the_config(tmp_path, capsys):
    """`[plate] exposure_s` is the one source of truth: both fields, one bottom layer."""
    _run_config(tmp_path)
    header = read_file(tmp_path / "plate.px6s").header
    assert header.exposure_s == 25.0, "the normal time"
    assert header.bottom_exposure_s == 25.0, "and the bottom one: layer 0 IS the bottom"
    assert header.bottom_layers == 1
    assert "exposure: 25 s from [plate] exposure_s" in capsys.readouterr().out


def test_a_px6s_without_the_time_in_the_config_is_refused_with_the_key(tmp_path, capsys):
    """The refusal names the KEY that is missing, not just the file."""
    body = SQUARE_BODY.replace("exposure_s = 25\n", "")
    config = _config(tmp_path, body)
    assert main(["masks", "plate", "--config", str(config)]) == 2
    assert "'exposure_s'" in capsys.readouterr().err


def test_a_plate_px6s_needs_the_config(tmp_path, capsys):
    """Without a config there is no exposure time to write, and no layout to explain it."""
    code = main(["masks", "plate", *SCREEN_ARGS, "-o", str(tmp_path / "plate.px6s")])
    assert code == 2
    assert "needs --config" in capsys.readouterr().err


def test_an_output_path_without_a_config_is_mandatory(tmp_path, capsys):
    """`-o` is no longer an argparse requirement, so it has its own one-line refusal."""
    code = main(["masks", "plate", *SCREEN_ARGS])
    assert code == 2
    assert "output path is mandatory" in capsys.readouterr().err


def test_a_broken_config_is_one_line_and_code_two(tmp_path, capsys):
    """The one-line refusal of the whole utility, not a traceback from tomllib."""
    body = SQUARE_BODY.replace("height_mm = 16", "widht_mm = 16")
    config = _config(tmp_path, body)
    assert main(["masks", "plate", "--config", str(config)]) == 2
    err = capsys.readouterr().err.strip()
    assert "\n" not in err, f"a refusal is ONE line, got: {err!r}"
    assert "'widht_mm'" in err


def test_the_report_names_the_plate_the_figures_and_the_time(tmp_path, capsys):
    """The report is the operator's table: where each figure lies, in mm and in px."""
    config = _example_in(tmp_path, "plate_70x78_patches.toml")
    assert main(["masks", "plate", "--config", str(config)]) == 0
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
    config = _example_in(tmp_path, "plate_70x78_patches.toml")
    assert main(["masks", "plate", "--config", str(config)]) == 0
    out = capsys.readouterr().out
    assert "pattern: patches, 4 rows" in out
    assert "row 1: 0.050 mm" in out and "row 4: 0.200 mm" in out


@pytest.mark.parametrize("name, label", [
    ("plate_70x80_20s.toml", "20s"),
    ("plate_70x80_25s.toml", "25s"),
    ("plate_70x80_30s.toml", "30s"),
])
def test_every_time_plate_carries_its_own_label(tmp_path, capsys, name, label):
    """Each plate of the series says its own exposure time in the plate's own font (Т1).

    The label comes from `{exposure_s}`, not from a second copy of the number in the file
    (25.10: a copied config kept saying "25s" after the time was changed to 7 s).
    """
    config = _example_in(tmp_path, name)
    assert 'text = "{exposure_s}s"' in config.read_text(encoding="utf-8"), \
        "the example must ask for the plate's own time, not repeat it"
    assert main(["masks", "plate", "--config", str(config)]) == 0
    out = capsys.readouterr().out
    assert f"pattern: text {label!r}" in out
    assert "drawn: 102 x 42 px = 3.468 x 1.428 mm" in out
    written = tmp_path / f"{name.removesuffix('.toml')}.px6s"
    assert written.is_file(), f"the label's plate was not written: {written}"


def test_a_quarter_turn_puts_the_plate_on_its_side(tmp_path, capsys):
    """`[plate] rotate = 90` turns the finished plate and centres it again (25.10)."""
    config = _example_in(tmp_path, "plate_70x80_20s_rot90.toml")
    assert main(["masks", "plate", "--config", str(config)]) == 0
    out = capsys.readouterr().out
    assert ("plate: 70.000 x 80.000 mm (2059 x 2353 px) turned 90 degrees "
            "counter-clockwise to 2353 x 2059 px, centred on the 5760 x 3600 px screen at "
            "1703, 770 px") in out
    assert "pattern: text '20s'" in out, "the label is turned with the plate"
