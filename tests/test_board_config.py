"""`gerber2msla/board_config.py`: a whole board read strictly out of one TOML file.

Plan `plan_2026_10_24_board_config`, Б1. The strict helpers are the plate's own
(`config_strict.py`), so the cells here check what is PARTICULAR to a board, and that the
shared rules really are shared — one unknown-key row and one syntax row are enough to
show the same refusal comes out of the same code.

    sides             two sides, their own mirror/holes/time, the optional align
    paths             relative paths count from the CONFIG's directory, not the cwd
    key strictness    an unknown key in [board] and in [[side]] refused BY NAME; a missing
                      key refused the same way — no defaults anywhere
    type strictness   `mirror = "no"` and `holes = 1` are not booleans; `exposure_s = true`
                      is not a number; `drills` must be an array; `pixel_um` is a positive
                      pair; `name` is a string
    syntax            a broken TOML names the LINE of the file
    outline           a config without it is refused (on the command line it is only a
                      warning; two sides cannot be lined up without one frame)
    align             `align_s` without `drills` is refused — there is nothing to read the
                      alignment by; `holes = true` without `drills` likewise
    names             a name is a FILE name: `[a-z0-9_-]` only, and unique
    no sides          a board with no [[side]] is refused, and so is `side = []`
    input files       a missing template/copper/drill is refused with the KEY and the path

Empty cells, named: `pixel_um` reaching the GEOMETRY is not here — Б1 only reads the
config, and the pixel is applied by `screen_for` (the Г2 rule, already covered there);
`load_board_config` on a non-UTF-8 file is the same helper as the plate's, covered by
`test_a_config_file_that_cannot_be_read_is_refused` in `tests/test_plate_config.py`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from gerber2msla.board_config import load_board_config, parse_board_config
from gerber2msla.masks import Refusal

BASE = """
[output]
template = "t.px6s"
dir = "out"
png = false

[board]
outline = "edge.gbr"
drills = ["pth.drl"]

[[side]]
name = "top"
copper = "f_cu.gbr"
mirror = false
holes = false
exposure_s = 25

[[side]]
name = "bottom"
copper = "b_cu.gbr"
mirror = true
holes = true
exposure_s = 30
align_s = 1
"""

NO_DRILLS = BASE.replace('drills = ["pth.drl"]', "drills = []")


def _read(text: str, base: Path | None = None):
    return parse_board_config(text, source="board.toml", base=base)


def _message(text: str, base: Path | None = None) -> str:
    """The one line the operator gets; a refusal that is not one line is a defect."""
    with pytest.raises(Refusal) as caught:
        _read(text, base)
    message = str(caught.value)
    assert "\n" not in message, "a refusal is ONE line"
    return message


def _with_line(text: str, prefix: str, replacement: str) -> str:
    """Replace the one line starting with ``prefix`` — the configs differ by one key."""
    return "\n".join(replacement if line.startswith(prefix) else line
                     for line in text.splitlines())


# ─────────────────────────────── reading ───────────────────────────────────

def test_a_board_config_is_read_into_sides():
    """Two sides, each with its own mirror, holes and time; the align file is derived."""
    config = _read(BASE)
    assert config.output.template == Path("t.px6s")
    assert config.output.dir == Path("out")
    assert config.output.png is False, "a required boolean, not a default"
    assert config.outline == Path("edge.gbr")
    assert config.drills == (Path("pth.drl"),)
    assert config.pixel_um is None, "no [output] pixel_um: the template header decides"
    assert [side.name for side in config.sides] == ["top", "bottom"]
    top, bottom = config.sides
    assert (top.mirror, top.holes, top.exposure_s, top.align_s) == (False, False, 25.0, None)
    assert (bottom.mirror, bottom.holes, bottom.exposure_s, bottom.align_s) == \
        (True, True, 30.0, 1.0)
    assert top.exposure_file == "top.px6s" and top.align_file is None
    assert bottom.exposure_file == "bottom.px6s"
    assert bottom.align_file == "bottom_align.px6s", "the align name comes from the side's"
    assert config.text == BASE, "the report carries the file as it was read"


def test_paths_count_from_the_config_directory_not_the_working_directory(tmp_path,
                                                                        monkeypatch):
    """The whole point of a config: `cd` somewhere else cannot break the paths.

    Real (empty) files are created: `load_board_config` checks that every input exists,
    and the check is about the KEY and the path, not about the contents.
    """
    gerber = tmp_path / "gerber"
    gerber.mkdir()
    for name in ("t.px6s", "edge.gbr", "pth.drl", "f_cu.gbr", "b_cu.gbr"):
        (gerber / name).write_text("")
    config_file = tmp_path / "board.toml"
    config_file.write_text(
        BASE.replace('"t.px6s"', '"gerber/t.px6s"')
            .replace('"edge.gbr"', '"gerber/edge.gbr"')
            .replace('"pth.drl"', '"gerber/pth.drl"')
            .replace('"f_cu.gbr"', '"gerber/f_cu.gbr"')
            .replace('"b_cu.gbr"', '"gerber/b_cu.gbr"'))

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    config = load_board_config(config_file)
    assert config.output.template == gerber / "t.px6s"
    assert config.sides[0].copper == gerber / "f_cu.gbr", \
        "the copper of the FIRST side, resolved against the config's directory"


def test_an_absolute_path_is_taken_as_it_is(tmp_path):
    absolute = tmp_path / "somewhere" / "cu.gbr"
    config = _read(_with_line(BASE, "copper", f'copper = "{absolute}"'), base=tmp_path)
    assert config.sides[0].copper == absolute


UNKNOWN_KEY_CELLS = [
    ("board", BASE.replace('outline = "edge.gbr"', 'outline = "edge.gbr"\npixel = [1, 1]'),
     "'pixel'", "the known keys are drills, outline"),
    ("output", BASE.replace('dir = "out"', 'dir = "out"\nfolder = "x"'),
     "'folder'", "the known keys are dir, pixel_um, png, template"),
    ("side", _with_line(BASE, "holes", "holes = false\nalign = 1"),
     "'align'", "the known keys are align_s, copper, exposure_s, holes, mirror, name"),
]


@pytest.mark.parametrize("level, text, named, known", UNKNOWN_KEY_CELLS,
                         ids=[cell[0] for cell in UNKNOWN_KEY_CELLS])
def test_an_unknown_key_is_refused_with_its_name(level, text, named, known):
    """A typo is never a silent default — the same rule as the plate, the same code."""
    message = _message(text)
    assert named in message and "unknown key" in message
    assert known in message, f"the operator is told which keys belong in {level}"


MISSING_KEY_CELLS = [
    ("template", _with_line(BASE, "template", "")),
    ("dir", _with_line(BASE, "dir", "")),
    ("png", _with_line(BASE, "png", "")),
    ("outline", _with_line(BASE, "outline", "")),
    ("drills", _with_line(BASE, "drills", "")),
    ("name", _with_line(BASE, "name", "")),
    ("copper", _with_line(BASE, "copper", "")),
    ("mirror", _with_line(BASE, "mirror", "")),
    ("holes", _with_line(BASE, "holes", "")),
    ("exposure_s", _with_line(BASE, "exposure_s", "")),
]


@pytest.mark.parametrize("key, text", MISSING_KEY_CELLS,
                         ids=[cell[0] for cell in MISSING_KEY_CELLS])
def test_a_missing_key_is_refused_with_its_name(key, text):
    """The other half of "no defaults": nothing is filled in, the key is asked for."""
    message = _message(text)
    assert f"'{key}'" in message
    assert "no defaults" in message, "the refusal says WHY it does not fill the gap"


TYPE_CELLS = [
    ("mirror is not a boolean", "mirror = false", 'mirror = "no"', "mirror",
     "must be true or false"),
    ("holes is a number", "holes = false", "holes = 1", "holes",
     "must be true or false"),
    ("the time is a boolean", "exposure_s = 25", "exposure_s = true", "exposure_s",
     "must be a number"),
    ("drills is a string", 'drills = ["pth.drl"]', 'drills = "pth.drl"', "drills",
     "must be an array of paths"),
    ("png is not a boolean", "png = false", 'png = "yes"', "png", "must be true or false"),
    ("pixel_um is not a pair", "png = false", "png = false\npixel_um = [34]", "pixel_um",
     "exactly two numbers"),
    ("name is a number", 'name = "top"', "name = 5", "name", "must be a string"),
]


@pytest.mark.parametrize("label, old, new, named, expected", TYPE_CELLS,
                         ids=[cell[0] for cell in TYPE_CELLS])
def test_a_value_of_the_wrong_type_is_refused_with_its_key(label, old, new, named,
                                                           expected):
    """`1` is not `true` and `true` is not a number: TOML has both, and so do we."""
    text = BASE.replace(old, new)
    assert old in BASE, "the cell must replace something that is really there"
    message = _message(text)
    assert named in message and expected in message


def test_a_syntax_error_names_the_line_of_the_file():
    """A broken file is refused with the LINE, not with a Python traceback."""
    broken = '[board]\ntemplate = "t.px6s"\noutline = = "edge.gbr"\n'
    message = _message(broken)
    assert message.startswith("board.toml: line 3:"), message


# ────────────────────────── what a board demands ───────────────────────────

def test_a_config_without_outline_is_refused():
    """On the command line a missing `--outline` is a warning; here it is a refusal.

    Two sides of one board cannot be lined up without one common frame, and the config is
    the place where that is decided once for every file.
    """
    message = _message(_with_line(BASE, "outline", ""))
    assert "'outline'" in message and "no defaults" in message


def test_align_without_drills_is_refused():
    """The alignment exposure is read BY the holes: no drills, nothing to read."""
    message = _message(NO_DRILLS)
    assert "side 'bottom'" in message and "'align_s'" in message and "'drills'" in message


def test_holes_without_drills_is_refused():
    """`holes = true` with an empty drill list is a promise the file cannot keep."""
    text = _with_line(NO_DRILLS, "align_s", "")
    message = _message(text)
    assert "side 'bottom'" in message and "'holes = true'" in message


TENTED = """
[output]
template = "t.px6s"
dir = "out"
png = true

[board]
outline = "edge.gbr"
drills = []

[[side]]
name = "top"
copper = "f_cu.gbr"
mirror = false
holes = false
exposure_s = 25
"""


def test_an_empty_drill_list_with_tenting_sides_is_legal():
    """A board with no holes at all exists: the side tents, and no align is asked."""
    config = _read(TENTED)
    assert config.drills == ()
    assert config.sides[0].holes is False
    assert config.sides[0].align_s is None
    assert config.sides[0].align_file is None


def test_two_sides_with_one_name_are_refused():
    """Two sides with one name would write one file over the other."""
    text = BASE.replace('name = "bottom"', 'name = "top"')
    message = _message(text)
    assert "'top'" in message and "used twice" in message


NAMES = ["top side", "Top", "top/../bottom", "top.px6s"]


@pytest.mark.parametrize("name", NAMES)
def test_a_side_name_that_is_not_a_file_name_is_refused(name):
    """The name becomes `<name>.px6s`: it must survive as a file name, exactly."""
    message = _message(BASE.replace('name = "top"', f'name = "{name}"'))
    assert "is not a file name" in message
    assert "a-z, 0-9" in message


@pytest.mark.parametrize("label, text, expected", [
    ("no sides", BASE.split("\n[[side]]")[0].strip() + "\n", "no [[side]]"),
    ("an empty array", "side = []\n" + BASE.split("\n[[side]]")[0].strip() + "\n",
     "no [[side]]"),
], ids=["no sides", "an empty array"])
def test_a_board_without_sides_is_refused(label, text, expected):
    """A board with nothing on it is not a board."""
    assert expected in _message(text)


def test_a_missing_input_file_is_refused_with_its_key_and_path(tmp_path):
    """The refusal names the KEY and the resolved path — `cd` somewhere else is a hint."""
    (tmp_path / "t.px6s").write_text("")
    (tmp_path / "edge.gbr").write_text("")
    config_file = tmp_path / "board.toml"
    config_file.write_text(BASE)
    with pytest.raises(Refusal) as caught:
        load_board_config(config_file)
    message = str(caught.value)
    assert "'drills[0]'" in message, "the KEY of the missing input, not just a path"
    assert str(tmp_path / "pth.drl") in message, "and the path it was resolved to"
    assert "no such file exists" in message


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_the_board_example_parses_with_the_sides_it_names():
    """`examples/board_heatingtable.toml` is committed, so a typo in it breaks a cell.

    Its input paths are a placeholder (`gerber/` next to the file, plan Б2), so only the
    PARSE runs here; `load` would demand files that belong to Denis's KiCad project, and
    `diagnostics/probe_board_config_2026_10_24.py` is what runs the real board.

    The MIRROR of each side is the measured fact of 25.10 (two plates): a file written
    without `--mirror` reads mirrored on the copper, so `top` is mirrored here and
    `bottom` is not — the opposite of what this cell held before the measurement.
    """
    path = EXAMPLES / "board_heatingtable.toml"
    config = parse_board_config(path.read_text(encoding="utf-8"), source=str(path),
                                base=EXAMPLES)
    assert [side.name for side in config.sides] == ["top", "bottom"]
    assert [side.mirror for side in config.sides] == [True, False], \
        "measured 25.10: an unmirrored file reads mirrored on the copper"
    assert [side.holes for side in config.sides] == [False, False]
    assert [side.align_s for side in config.sides] == [1.0, 1.0]
    assert [side.exposure_s for side in config.sides] == [25.0, 25.0]
    assert config.output.png is True
    assert config.output.dir == EXAMPLES.parent / "out" / "HeatingTable", \
        "the folder counts from the config's own directory"
    assert config.outline.name.endswith("-Edge_Cuts.gbr")
    assert len(config.drills) == 2
