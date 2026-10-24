"""The `board` command (plan Г2, rules of 24.10 about the screen and the pixel; plan Б2).

Cells closed here — the table of what the command line decides:

    формат выхода         `-o *.png` — маска, `-o *.px6s` — файл принтера; иное — отказ
    экран                 ВСЕГДА из шаблона; `--screen-px` с `--template` — отказ одной строкой
    пиксель               без `--pixel-um` — из заголовка; с ним — замер, ЗАГОЛОВОК НЕ МЕНЯЕТСЯ
    высота платы          замер 34x30 и заголовок 34.00 дают РАЗНУЮ высоту в px
    заголовок файла       у этих двух файлов блоки header/machine/software/extra байт в байт
    круг                  board → .px6s → dump -o → та же PNG, что board → .png
    отказы                больше экрана; не Gerber; не Excellon; `.px6s` без шаблона и без времени;
                          без шаблона и без экрана/пикселя; неизвестное расширение

План Б2 (`board --config`) — таблица решений конфига:

    выход                 `[output] dir` (а не `-o`), `png = true|false`; перезапись — `overwrote`
    рамка                 ОДНА строка на всю плату: контур общий, и вторая копия лишь разошлась бы
    стороны               своя медь, своё зеркало; `bottom` — зеркальные столбцы `top`
    отверстия             `holes = false` — тент; `_align` — ВСЕГДА с отверстиями и своим временем
    картинка              .png и .px6s одного файла — из ОДНОГО `compose`
    пути                  от файла конфига: другой текущий каталог ничего не сдвигает
    отказы                двенадцать флагов рядом с `--config` — по имени; без меди; без `-o`

Empty cells and why: no cell for `--at`, `--mirror`, `--invert` and `--marker` — they are
`masks`' own flags, their cells are in `test_masks.py`, and this command hands the figure to
the same `compose`; no cell for an unreadable template — `tests/test_cli_px6s.py` covers the
reader's refusals. The config's own refusals (unknown key, bad type, `align_s` without
`drills`) are in `tests/test_board_config.py`.

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
    """A 2 x 1 mm board: copper pad, its outline and one 0.6 mm hole in the middle.

    `copper_b` is the RIGHT HALF of the same board: two sides of one config must give two
    different pictures, or a second side could quietly reuse the first one's copper.
    """
    copper = tmp_path / "F_Cu.gbr"
    copper.write_text(_layer("%ADD10R,2.0X1.0*%\n%LPD*%\nG01*\nD10*\n"
                             f"X{_coord(1.0)}Y{_coord(0.5)}D03*\n"))
    copper_b = tmp_path / "B_Cu.gbr"
    copper_b.write_text(_layer(_region([(1.0, 0.0), (2.0, 0.0), (2.0, 1.0), (1.0, 1.0)])))
    outline = tmp_path / "Edge_Cuts.gbr"
    outline.write_text(_layer(_region([(0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0)])))
    drill = tmp_path / "PTH.drl"
    drill.write_text(EXCELLON)
    return {"copper": copper, "copper_b": copper_b, "outline": outline, "drill": drill,
            "dir": tmp_path}


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


def test_the_mask_carries_the_pixel_provenance_in_its_chunk(capsys, template, board_files):
    """`write_mask` is untouched, but the provenance travels INSIDE the figure's report.

    So a mask file found on the printer's stick still says which pixel drew it — the
    measured one, with the value the file header keeps.
    """
    mask = board_files["dir"] / "chunk.png"
    out = _run(capsys, "board", str(board_files["copper"]), "--outline",
               str(board_files["outline"]), "--template", str(template),
               "--pixel-um", "34x30", "-o", str(mask))
    line = "pixel: 34.00 x 30.00 um (measured, --pixel-um; the file header keeps 34.00)"
    assert line in out
    chunk = Image.open(mask).text.get("msla_tests", "")
    assert line in chunk, "the provenance must travel with the mask, not only in stdout"


def test_the_polarity_line_speaks_about_the_copper(capsys, template, board_files):
    """A board lights the copper, a test mask lights lines: each report uses its own word."""
    mask = board_files["dir"] / "polarity.png"
    out = _run(capsys, "board", str(board_files["copper"]), "--outline",
               str(board_files["outline"]), "--template", str(template), "-o", str(mask))
    assert "polarity: white = the copper (a negative resist keeps what was lit)" in out

    mask_out = board_files["dir"] / "lines.png"
    out = _run(capsys, "masks", "bars", "--screen-px", "5760x3600", "--pixel-um", "34x34",
               "-o", str(mask_out))
    assert "polarity: white = the lines (a negative resist keeps what was lit)" in out, \
        "the masks' own line must stay exactly as it was"


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


# ─────────────────────────── a board from a config ─────────────────────────
#
# The config lives in `tmp_path/cfg`, its own paths are relative to ITSELF
# ("../F_Cu.gbr", "../made"), and the template is given by absolute path: a cell that
# changes the working directory then proves which of the two a path counts from.

def _side(name: str, copper: str, *, mirror: bool = False, holes: bool = False,
          exposure: float = 25, align: float | None = None) -> str:
    """One `[[side]]` block, written the way an operator writes it."""
    lines = ["[[side]]", f'name = "{name}"', f'copper = "{copper}"',
             f"mirror = {'true' if mirror else 'false'}",
             f"holes = {'true' if holes else 'false'}",
             f"exposure_s = {exposure:g}"]
    if align is not None:
        lines.append(f"align_s = {align:g}")
    return "\n".join(lines) + "\n"


def _toml(where: Path, template: Path, *sides: str, png: bool = False,
          pixel_um: str | None = None, name: str = "board.toml") -> Path:
    """A board config in `where/cfg`: the frame and the drills are the fixture's."""
    parts = [
        "[output]",
        f'template = "{template}"',
        'dir = "../made"',
        f"png = {'true' if png else 'false'}",
    ]
    if pixel_um is not None:
        parts.append(f"pixel_um = {pixel_um}")
    parts += ["", "[board]", 'outline = "../Edge_Cuts.gbr"', 'drills = ["../PTH.drl"]', ""]
    parts.append("\n".join(sides))
    folder = where / "cfg"
    folder.mkdir(exist_ok=True)
    path = folder / name
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return path


def _file_pixels(path: Path) -> np.ndarray:
    """The picture the printer will light: the layer of the file itself."""
    return read_file(path).layer_image(0)


def _white_box(pixels: np.ndarray) -> tuple[int, int, int, int]:
    """The box of the white: left and upper INCLUSIVE, right and lower EXCLUSIVE."""
    rows, cols = np.nonzero(pixels)
    return int(cols.min()), int(rows.min()), int(cols.max()) + 1, int(rows.max()) + 1


def test_a_config_writes_the_folder_and_the_report(capsys, template, board_files):
    """The folder comes from `[output] dir` — it need not exist — and keeps the report."""
    config = _toml(board_files["dir"], template, _side("top", "../F_Cu.gbr", align=1))
    out = _run(capsys, "board", "--config", str(config))

    made = board_files["dir"] / "made"
    assert (made / "top.px6s").is_file()
    assert (made / "top_align.px6s").is_file()
    assert "Wrote" in out and "px layer" in out
    assert read_file(made / "top.px6s").header.exposure_s == pytest.approx(25.0)
    assert read_file(made / "top_align.px6s").header.exposure_s == pytest.approx(1.0)

    report = (made / "board_report.txt").read_text(encoding="utf-8")
    assert "config, whole, as read from" in report
    for line in config.read_text(encoding="utf-8").splitlines():
        if line.strip():
            assert line in report, f"the report lost the config's own line {line!r}"


def test_one_frame_is_printed_for_the_whole_board(capsys, template, board_files):
    """Two sides, one outline: the frame is stated once, and a side without `align_s` says so."""
    config = _toml(board_files["dir"], template,
                   _side("top", "../F_Cu.gbr"), _side("bottom", "../B_Cu.gbr"))
    out = _run(capsys, "board", "--config", str(config))
    assert out.count("frame: ") == 1, f"the frame is one line for the whole board: {out}"
    assert "side top:" in out and "side bottom:" in out
    assert "align: none — the side has no 'align_s'" in out


def test_each_side_takes_its_own_copper(capsys, template, board_files):
    """`B_Cu` is the right half of the board: the second side must not reuse the first's."""
    config = _toml(board_files["dir"], template,
                   _side("top", "../F_Cu.gbr"), _side("bottom", "../B_Cu.gbr"))
    _run(capsys, "board", "--config", str(config))
    made = board_files["dir"] / "made"
    top, bottom = _file_pixels(made / "top.px6s"), _file_pixels(made / "bottom.px6s")
    assert _white_box(bottom)[0] > _white_box(top)[0], "the bottom is its own copper"
    assert np.count_nonzero(bottom) < np.count_nonzero(top)


def test_a_side_is_mirrored_and_the_other_is_not(capsys, template, board_files):
    """The mirror is the side's own: one file keeps its columns, the other is reflected."""
    config = _toml(board_files["dir"], template,
                   _side("top", "../F_Cu.gbr"),
                   _side("bottom", "../F_Cu.gbr", mirror=True))
    out = _run(capsys, "board", "--config", str(config))
    made = board_files["dir"] / "made"
    top, bottom = _file_pixels(made / "top.px6s"), _file_pixels(made / "bottom.px6s")
    left, _, right, _ = _white_box(top)
    mirror_left, _, mirror_right, _ = _white_box(bottom)
    width = top.shape[1]
    assert (mirror_left, mirror_right) == (width - right, width - left)
    assert "side bottom: F_Cu.gbr, mirror on" in out
    assert "side top: F_Cu.gbr, mirror off" in out


def test_the_align_file_always_has_the_holes_and_its_own_time(capsys, template, board_files):
    """`holes = false` keeps a tenting working mask; the alignment file has the holes anyway."""
    config = _toml(board_files["dir"], template, _side("top", "../F_Cu.gbr", align=1))
    out = _run(capsys, "board", "--config", str(config))
    made = board_files["dir"] / "made"
    tent, align = _file_pixels(made / "top.px6s"), _file_pixels(made / "top_align.px6s")
    assert np.count_nonzero(tent) > np.count_nonzero(align)
    assert np.array_equal(np.maximum(tent, align), tent), "the align file invents no white"
    assert _white_box(tent) == _white_box(align), "the frame did not move for the holes"
    assert read_file(made / "top_align.px6s").header.exposure_s == pytest.approx(1.0)
    assert "holes ALWAYS subtracted" in out


def test_holes_true_pours_the_holes_in_the_working_file(capsys, template, board_files):
    """`holes = true` subtracts the drills in the exposure file too — and only subtracts."""
    config = _toml(board_files["dir"], template,
                   _side("tent", "../F_Cu.gbr"), _side("pour", "../F_Cu.gbr", holes=True))
    _run(capsys, "board", "--config", str(config))
    made = board_files["dir"] / "made"
    tent, pour = _file_pixels(made / "tent.px6s"), _file_pixels(made / "pour.px6s")
    assert np.count_nonzero(pour) < np.count_nonzero(tent)
    assert not ((pour > 0) & (tent == 0)).any(), "pouring removes white, it never adds any"


def test_png_pairs_come_from_the_same_picture(capsys, template, board_files):
    """`png = true` adds a PNG of the very layer: one compose, two files, no third drawing."""
    config = _toml(board_files["dir"], template, _side("top", "../F_Cu.gbr", align=1),
                   png=True)
    _run(capsys, "board", "--config", str(config))
    made = board_files["dir"] / "made"
    for stem in ("top", "top_align"):
        assert np.array_equal(_pixels(made / f"{stem}.png"), _file_pixels(made / f"{stem}.px6s")), \
            f"{stem}.png and {stem}.px6s are one picture"


def test_the_paths_count_from_the_config_file(capsys, template, board_files, monkeypatch):
    """A different working directory must not move a single file of the board.

    The working directory is TWO levels below the board, so a path counted from it cannot
    accidentally land where the config meant: `../made` would be another folder, and the
    cell says which one is right.
    """
    config = _toml(board_files["dir"], template, _side("top", "../F_Cu.gbr"))
    elsewhere = board_files["dir"] / "run" / "deep"
    elsewhere.mkdir(parents=True)
    monkeypatch.chdir(elsewhere)
    _run(capsys, "board", "--config", str(config))
    assert (board_files["dir"] / "made" / "top.px6s").is_file()
    assert not (board_files["dir"] / "run" / "made").exists()
    assert not (elsewhere / "top.px6s").exists()


def test_a_second_run_says_overwrote(capsys, template, board_files):
    """No overwrite protection (plan Б0): the file is made again and the report says so."""
    config = _toml(board_files["dir"], template, _side("top", "../F_Cu.gbr"))
    _run(capsys, "board", "--config", str(config))
    out = _run(capsys, "board", "--config", str(config))
    assert "overwrote" in out and "Wrote" not in out


def test_pixel_um_in_the_output_changes_the_geometry_only(capsys, template, board_files):
    """The board's `[output]` is the plate's: a measured pixel, a header left byte for byte."""
    config = _toml(board_files["dir"], template, _side("top", "../F_Cu.gbr"))
    out = _run(capsys, "board", "--config", str(config))
    assert "= 59 x 29 px" in out
    made = board_files["dir"] / "made"
    plain_blocks = _blocks(made / "top.px6s")

    config = _toml(board_files["dir"], template, _side("top", "../F_Cu.gbr"),
                   pixel_um="[34.0, 30.0]")
    out = _run(capsys, "board", "--config", str(config))
    assert "= 59 x 33 px" in out
    assert read_file(made / "top.px6s").header.pixel_size_um == pytest.approx(34.0)
    measured_blocks = _blocks(made / "top.px6s")
    for name in ("header", "machine", "software", "extra"):
        assert plain_blocks[name] == measured_blocks[name], f"the {name} block moved"
    assert plain_blocks["layer_image"] != measured_blocks["layer_image"]


@pytest.mark.parametrize("extra, name", [
    (["../F_Cu.gbr"], "the copper argument"),
    (["-o", "x.px6s"], "-o/--output"),
    (["--drill", "PTH.drl"], "--drill"),
    (["--outline", "Edge_Cuts.gbr"], "--outline"),
    (["--template", "t.px6s"], "--template"),
    (["--screen-px", "5760x3600"], "--screen-px"),
    (["--pixel-um", "34x34"], "--pixel-um"),
    (["--exposure-s", "25"], "--exposure-s"),
    (["--at", "0,0"], "--at"),
    (["--mirror"], "--mirror"),
    (["--invert"], "--invert"),
    (["--marker"], "--marker"),
], ids=["copper", "-o", "--drill", "--outline", "--template", "--screen-px", "--pixel-um",
        "--exposure-s", "--at", "--mirror", "--invert", "--marker"])
def test_a_flag_next_to_the_config_is_refused_by_name(capsys, template, board_files,
                                                      extra, name):
    """Twelve ways to say one thing twice: every one is a refusal that names itself."""
    config = _toml(board_files["dir"], template, _side("top", "../F_Cu.gbr"))
    error = _refused(capsys, "board", "--config", str(config), *extra)
    assert name in error
    assert "--config" in error


def test_without_a_config_the_copper_and_the_output_stay_mandatory(capsys, board_files):
    """The two positional facts are checked by name, each with its own one line."""
    error = _refused(capsys, "board", "-o", str(board_files["dir"] / "top.png"))
    assert "the copper layer is mandatory" in error
    error = _refused(capsys, "board", str(board_files["copper"]))
    assert "an output path is mandatory" in error
