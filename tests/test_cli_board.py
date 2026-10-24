"""The `board` command (plan Г2, rules of 24.10 about the screen and the pixel).

Cells closed here — the table of what the command line decides:

    формат выхода         `-o *.png` — маска, `-o *.px6s` — файл принтера; иное — отказ
    экран                 ВСЕГДА из шаблона; `--screen-px` с `--template` — отказ одной строкой
    пиксель               без `--pixel-um` — из заголовка; с ним — замер, ЗАГОЛОВОК НЕ МЕНЯЕТСЯ
    высота платы          замер 34x30 и заголовок 34.00 дают РАЗНУЮ высоту в px
    заголовок файла       у этих двух файлов блоки header/machine/software/extra байт в байт
    круг                  board → .px6s → dump -o → та же PNG, что board → .png
    отказы                больше экрана; не Gerber; не Excellon; `.px6s` без шаблона и без времени;
                          без шаблона и без экрана/пикселя; неизвестное расширение

Empty cells and why: no cell for `--at`, `--mirror`, `--invert` and `--marker` — they are
`masks`' own flags, their cells are in `test_masks.py`, and this command hands the figure to
the same `compose`; no cell for an unreadable template — `tests/test_cli_px6s.py` covers the
reader's refusals.

The template `tests/data/01_test02.px6s` is the real one-layer file of this printer (5760 x
3600 px, pixel 34.00 um) and is read only: the screen and the header pixel are ITS numbers.

A refusal comes back as code 2 and ONE line on stderr (`cli.main` catches `Refusal`); only an
argparse type error raises `SystemExit`, and those cells are not here.
"""
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from gerber2msla.cli import main
from gerber2msla.px6s import read_file
from gerber2msla.px6s_write import _template_blocks

DATA = Path(__file__).resolve().parents[1] / "tests" / "data"
TEMPLATE = DATA / "01_test02.px6s"

HEADER = "%FSLAX46Y46*%\n%MOMM*%\n%TF.FileFunction,Copper,L1,Top*%\n"
FOOTER = "M02*\n"
EXCELLON = """M48
FMAT,2
METRIC
T1C0.600
%
G90
G05
T1
X1.0Y0.5
M30
"""


def _coord(value: float) -> str:
    return f"{int(round(value * 1e6))}"


def _region(points) -> str:
    first_x, first_y = points[0]
    lines = [f"X{_coord(first_x)}Y{_coord(first_y)}D02*", "G36*"]
    for x, y in points[1:]:
        lines.append(f"X{_coord(x)}Y{_coord(y)}D01*")
    lines.append(f"X{_coord(first_x)}Y{_coord(first_y)}D01*")
    lines.append("G37*")
    return "\n".join(lines) + "\n"


def _layer(*bodies: str) -> str:
    return HEADER + "".join(bodies) + FOOTER


@pytest.fixture
def template() -> Path:
    """The template is IN GIT: its absence is a break, not a reason to skip a guard."""
    if not TEMPLATE.is_file():
        pytest.fail(f"no {TEMPLATE}: the real template is committed, so a missing file "
                    f"breaks every cell that reads it")
    return TEMPLATE


@pytest.fixture
def board_files(tmp_path) -> dict[str, Path]:
    """A 2 x 1 mm board: copper pad, its outline and one 0.6 mm hole in the middle."""
    copper = tmp_path / "F_Cu.gbr"
    copper.write_text(_layer("%ADD10R,2.0X1.0*%\n%LPD*%\nG01*\nD10*\n"
                             f"X{_coord(1.0)}Y{_coord(0.5)}D03*\n"))
    outline = tmp_path / "Edge_Cuts.gbr"
    outline.write_text(_layer(_region([(0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0)])))
    drill = tmp_path / "PTH.drl"
    drill.write_text(EXCELLON)
    return {"copper": copper, "outline": outline, "drill": drill, "dir": tmp_path}


def _run(capsys, *args: str) -> str:
    """Run the command line; a non-zero code is part of the call. Returns stdout."""
    code = main(list(args))
    captured = capsys.readouterr()
    assert code == 0, f"the tool refused with {code}: {captured.err}"
    return captured.out


def _refused(capsys, *args: str) -> str:
    """Run the command line expecting a refusal; returns the ONE line it printed."""
    code = main(list(args))
    assert code == 2, f"expected a refusal, got code {code}: {capsys.readouterr()}"
    error = capsys.readouterr().err
    assert error.count("\n") == 1, f"a refusal is ONE line, got: {error!r}"
    return error


def _blocks(path: Path) -> dict[str, bytes]:
    """The file's blocks by name — the same slicing the writer uses, not a second idea."""
    return {block.name: block.payload for block in _template_blocks(read_file(path))}


def _pixels(path: Path) -> np.ndarray:
    return np.array(Image.open(path))


# ─────────────────────────── the suffix chooses ────────────────────────────

def test_the_suffix_chooses_the_mask_or_the_printer_file(capsys, template, board_files):
    """`-o *.png` writes the mask, `-o *.px6s` the layer; both say what they wrote."""
    mask = board_files["dir"] / "top.png"
    out = _run(capsys, "board", str(board_files["copper"]), "--outline",
               str(board_files["outline"]), "--drill", str(board_files["drill"]),
               "--template", str(template), "-o", str(mask))
    assert "Wrote" in out and "px mask" in out
    assert _pixels(mask).shape == (3600, 5760)

    layer = board_files["dir"] / "top.px6s"
    out = _run(capsys, "board", str(board_files["copper"]), "--outline",
               str(board_files["outline"]), "--drill", str(board_files["drill"]),
               "--template", str(template), "--exposure-s", "25", "-o", str(layer))
    assert "Wrote" in out and "px layer" in out
    printer = read_file(layer)
    assert printer.layer_count == 1
    assert printer.header.exposure_s == pytest.approx(25.0)
    assert printer.header.bottom_exposure_s == pytest.approx(25.0)


def test_an_unknown_suffix_is_refused(capsys, template, board_files):
    """Only a mask PNG or a printer file: the suffix IS the choice, so a third is a refusal."""
    error = _refused(capsys, "board", str(board_files["copper"]), "--template",
                     str(template), "-o", str(board_files["dir"] / "top.bmp"))
    assert "must end in .png" in error


# ─────────────────────────── screen and pixel ──────────────────────────────

def test_the_template_fixes_the_screen(capsys, template, board_files):
    """`--screen-px` next to `--template` is a refusal, not a silent override."""
    error = _refused(capsys, "board", str(board_files["copper"]), "--template",
                     str(template), "--screen-px", "100x100",
                     "-o", str(board_files["dir"] / "top.png"))
    assert "the template fixes the screen" in error


def test_the_pixel_comes_from_the_header_unless_it_is_measured(capsys, template, board_files):
    """The report names the source of the pixel, in the words the operator asked for."""
    plain = board_files["dir"] / "plain.px6s"
    out = _run(capsys, "board", str(board_files["copper"]), "--outline",
               str(board_files["outline"]), "--template", str(template),
               "--exposure-s", "25", "-o", str(plain))
    assert "pixel: 34.00 x 34.00 um (template header)" in out

    measured = board_files["dir"] / "measured.px6s"
    out = _run(capsys, "board", str(board_files["copper"]), "--outline",
               str(board_files["outline"]), "--template", str(template), "--pixel-um",
               "34x30", "--exposure-s", "25", "-o", str(measured))
    assert ("pixel: 34.00 x 30.00 um (measured, --pixel-um; the file header keeps 34.00)"
            in out)


def test_a_measured_pixel_changes_the_height_but_not_the_file_header(capsys, template,
                                                                    board_files):
    """The 2 x 1 mm board: 59 x 29 px from the header, 59 x 33 px measured at 34 x 30 um.

    The file header is a MACHINE field: both .px6s keep 34.00 um, and every block that is
    not the picture (header, machine, software, extra) is byte for byte the same. Only the
    layer image differs, because only the geometry differs.
    """
    plain = board_files["dir"] / "plain.px6s"
    out = _run(capsys, "board", str(board_files["copper"]), "--outline",
               str(board_files["outline"]), "--template", str(template),
               "--exposure-s", "25", "-o", str(plain))
    assert "= 59 x 29 px" in out

    measured = board_files["dir"] / "measured.px6s"
    out = _run(capsys, "board", str(board_files["copper"]), "--outline",
               str(board_files["outline"]), "--template", str(template), "--pixel-um",
               "34x30", "--exposure-s", "25", "-o", str(measured))
    assert "= 59 x 33 px" in out

    assert read_file(measured).header.pixel_size_um == pytest.approx(34.0)
    plain_blocks, measured_blocks = _blocks(plain), _blocks(measured)
    for name in ("header", "machine", "software", "extra"):
        assert plain_blocks[name] == measured_blocks[name], f"the {name} block moved"
    assert plain_blocks["layer_image"] != measured_blocks["layer_image"], \
        "the geometry differs, so the picture must differ"


def test_without_a_template_the_screen_and_the_pixel_are_mandatory(capsys, board_files):
    """As in `masks`: no invented numbers. The screen without the pixel is a refusal too."""
    cases = [
        (["--screen-px", "5760x3600"], "screen and the pixel are mandatory"),
        (["--pixel-um", "34x34"], "screen and the pixel are mandatory"),
        ([], "screen and the pixel are mandatory"),
    ]
    for extra, match in cases:
        error = _refused(capsys, "board", str(board_files["copper"]), *extra,
                         "-o", str(board_files["dir"] / "top.png"))
        assert match in error


# ───────────────────────────── round trip ──────────────────────────────────

def test_the_printer_file_keeps_the_picture_of_the_mask(capsys, template, board_files):
    """board → .px6s → dump -o gives the same PNG as board → .png: one picture, two paths."""
    mask = board_files["dir"] / "same.png"
    _run(capsys, "board", str(board_files["copper"]), "--outline",
         str(board_files["outline"]), "--drill", str(board_files["drill"]),
         "--template", str(template), "-o", str(mask))

    layer = board_files["dir"] / "same.px6s"
    _run(capsys, "board", str(board_files["copper"]), "--outline",
         str(board_files["outline"]), "--drill", str(board_files["drill"]),
         "--template", str(template), "--exposure-s", "25", "-o", str(layer))

    dumped = board_files["dir"] / "dumped.png"
    _run(capsys, "dump", str(layer), "-o", str(dumped))
    assert np.array_equal(_pixels(mask), _pixels(dumped))


# ───────────────────────────── refusals ────────────────────────────────────

@pytest.fixture
def refusal_cases(tmp_path) -> dict[str, list[str]]:
    """Three inputs that cannot be drawn, each its OWN defect and its own message."""
    big = tmp_path / "big.gbr"
    big.write_text(_layer(_region([(0.0, 0.0), (3.0, 0.0), (3.0, 3.0), (0.0, 3.0)])))
    note = tmp_path / "note.gbr"
    note.write_text("this is not a gerber at all\n")
    copper = tmp_path / "ok.gbr"
    copper.write_text(_layer(_region([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])))
    broken_drill = tmp_path / "holes.drl"
    broken_drill.write_text("M48\nnot an excellon at all\n")
    return {
        "screen": ["board", str(big), "--screen-px", "10x10", "--pixel-um", "100x100",
                   "-o", str(tmp_path / "top.png")],
        "gerber": ["board", str(note), "--screen-px", "100x100", "--pixel-um", "100x100",
                   "-o", str(tmp_path / "top.png")],
        "excellon": ["board", str(copper), "--drill", str(broken_drill), "--screen-px",
                     "100x100", "--pixel-um", "100x100", "-o", str(tmp_path / "top.png")],
    }


@pytest.mark.parametrize("case, match", [
    ("screen", "does not fit the 10 x 10 px screen"),
    ("gerber", "Cannot read Gerber file"),
    ("excellon", "Cannot read drill file"),
], ids=["a board bigger than the screen", "not a gerber", "a drill that is not excellon"])
def test_a_board_that_cannot_be_drawn_is_one_line_and_code_two(capsys, refusal_cases,
                                                               case, match):
    """Through the command line the refusal is one line and code 2, with no traceback."""
    error = _refused(capsys, *refusal_cases[case])
    assert match in error


@pytest.mark.parametrize("extra, match", [
    ([], "a .px6s needs --template"),
    (["--template", "{template}"], "a .px6s needs --exposure-s"),
], ids=["no template", "no exposure time"])
def test_a_printer_file_needs_its_template_and_its_time(capsys, template, board_files,
                                                        extra, match):
    """Two machine facts come from outside: the printer's blocks and the exposure."""
    args = ["board", str(board_files["copper"])]
    for item in extra:
        args.append(str(template) if item == "{template}" else item)
    error = _refused(capsys, *args, "-o", str(board_files["dir"] / "top.px6s"))
    assert match in error
