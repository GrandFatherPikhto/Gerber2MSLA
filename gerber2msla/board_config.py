# gerber2msla/board_config.py
"""The board config: what a WHOLE board is made of, read strictly (plan Б1).

    # board.toml — every path is relative to THIS file, not to the working directory
    [board]
    template = "../tests/data/01_test02.px6s"
    outline  = "gerber/ControllerSTM32F103C8T6-Edge_Cuts.gbr"   # one frame for every file
    drills   = ["gerber/ControllerSTM32F103C8T6-PTH.drl"]        # may be empty: no holes
    # pixel_um = [34.0, 34.0]      # optional: a MEASUREMENT, not a default

    [[side]]
    name = "top"                 # -> top.px6s and top_align.px6s
    copper = "gerber/ControllerSTM32F103C8T6-F_Cu.gbr"
    mirror = false
    holes = false                # true = the drills are subtracted from the exposure too
    exposure_s = 25
    align_s = 1                  # optional: top_align.px6s, always WITH the holes

A board is not four long `board` commands typed by hand: it is one file that says which
copper belongs to which side, where the common frame is, and what each file is exposed
for. Four commands are easy to mix up; a file that names its sides is not.

STRICT, and with the SAME helpers as the plate config (`config_strict.py`) — the same
refusal for an unknown key, a missing key, a wrong type and a broken TOML line. What is
particular to a board:

  * `outline` is REQUIRED. Without one common frame the two sides do not line up, and on
    the command line that is only a warning — here it is a refusal (plan Б1);
  * `align_s` with no `drills` is a refusal: the alignment exposure is read by the holes,
    and there is nothing to read;
  * `holes = true` with no `drills` is a refusal for the same reason;
  * a side's `name` is a FILE name (`<name>.px6s`), so it is `[a-z0-9_-]` and unique:
    two sides with one name would overwrite each other's exposure;
  * paths are relative to the config FILE. That is the whole point of the file: it can
    be moved next to the Gerbers it talks about, and a `cd` cannot break it.

NOT HERE: pixels, frames and files. This module reads the text and resolves the paths;
the figures are `board.build_board`, the placement and the mirror are `masks.compose`,
the printer file is the П2 writer — all of them are called in `board_files.py`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config_strict import (_flag, _keys, _loads, _number, _pair, _read_text, _required,
                            _table, _text, _what)
from .masks import Refusal

ROOT_KEYS = ("board", "side")
BOARD_KEYS = ("drills", "outline", "pixel_um", "template")
SIDE_KEYS = ("align_s", "copper", "exposure_s", "holes", "mirror", "name")
SIDE_NAME = re.compile(r"[a-z0-9_-]+\Z")
"""A side's name is a FILE name: `<name>.px6s` and `<name>_align.px6s` are written from it."""


@dataclass(frozen=True, slots=True)
class SideSpec:
    """One side of the board: its copper, its mirror, its time, its optional alignment."""

    name: str
    copper: Path
    mirror: bool
    holes: bool
    exposure_s: float
    align_s: float | None = None

    @property
    def exposure_file(self) -> str:
        return f"{self.name}.px6s"

    @property
    def align_file(self) -> str | None:
        return None if self.align_s is None else f"{self.name}_align.px6s"


@dataclass(frozen=True, slots=True)
class BoardConfig:
    """A board config read and checked: paths resolved, no pixels yet."""

    template: Path
    outline: Path
    drills: tuple[Path, ...]
    pixel_um: tuple[float, float] | None
    sides: tuple[SideSpec, ...]
    text: str
    """The file as it was read: it goes into `board_report.txt` whole, UTF-8."""
    path: Path | None = None

    @property
    def label(self) -> str:
        return "<config>" if self.path is None else str(self.path)


# ──────────────────────────────── reading ──────────────────────────────────

def _resolve(value: str, base: Path | None) -> Path:
    """A path from the config: relative ones count from the CONFIG's own directory."""
    target = Path(value)
    if target.is_absolute() or base is None:
        return target
    return base / target


def _path(table: dict, key: str, where: str, source: str, base: Path | None) -> Path:
    return _resolve(_text(_required(table, key, where, source), key, where, source), base)


def _paths(value: object, key: str, where: str, source: str,
           base: Path | None) -> tuple[Path, ...]:
    """An array of paths; EMPTY is legal — a board with no holes exists."""
    if type(value) is not list:
        raise Refusal(f"{source}: {where}: '{key}' must be an array of paths (it may be "
                      f"empty), got {_what(value)}")
    return tuple(_resolve(_text(item, f"{key}[{index}]", where, source), base)
                 for index, item in enumerate(value))


def _side(value: object, index: int, source: str, base: Path | None,
          seen: set[str]) -> SideSpec:
    """One ``[[side]]``; after the name is known the refusals speak about that name."""
    where = f"side #{index}"
    table = _table(value, where, source)
    _keys(table, SIDE_KEYS, where, source)
    name = _text(_required(table, "name", where, source), "name", where, source)
    if not SIDE_NAME.match(name):
        raise Refusal(f"{source}: {where}: 'name' {name!r} is not a file name: use a-z, "
                      f"0-9, '-' and '_' only (it becomes {name}.px6s)")
    if name in seen:
        raise Refusal(f"{source}: {where}: the name {name!r} is used twice: the two "
                      f"sides would write one file over the other")
    seen.add(name)
    where = f"side '{name}'"
    return SideSpec(
        name=name,
        copper=_path(table, "copper", where, source, base),
        mirror=_flag(_required(table, "mirror", where, source), "mirror", where, source),
        holes=_flag(_required(table, "holes", where, source), "holes", where, source),
        exposure_s=_number(_required(table, "exposure_s", where, source), "exposure_s",
                           where, source),
        align_s=(_number(table["align_s"], "align_s", where, source)
                 if "align_s" in table else None),
    )


def parse_board_config(text: str, *, source: str = "<config>",
                       base: Path | None = None,
                       path: Path | None = None) -> BoardConfig:
    """Read the config text into specs; every refusal is one line that names the place.

    ``base`` is the directory relative paths count from — the config file's own, when the
    text came from a file. With ``base=None`` the paths stay as written, which is what a
    cell about the FORMAT needs.
    """
    data = _loads(text, source)
    _keys(data, ROOT_KEYS, "the top level", source)

    board = _table(_required(data, "board", "the top level", source), "the [board] table",
                   source)
    _keys(board, BOARD_KEYS, "[board]", source)
    template = _path(board, "template", "[board]", source, base)
    outline = _path(board, "outline", "[board]", source, base)
    drills = _paths(_required(board, "drills", "[board]", source), "drills", "[board]",
                    source, base)
    pixel_um = None
    if "pixel_um" in board:
        pixel_um = _pair(board["pixel_um"], "pixel_um", "[board]", source)

    # A board with no sides is not a board: the missing table and the empty array are ONE
    # refusal, worded for the operator, not for the parser.
    if "side" not in data or data["side"] == []:
        raise Refusal(f"{source}: no [[side]]: a board needs at least one side")
    raw = data["side"]
    if type(raw) is not list:
        raise Refusal(f"{source}: 'side' must be one or more [[side]] tables, "
                      f"got {_what(raw)}")
    seen: set[str] = set()
    sides = tuple(_side(value, index, source, base, seen)
                  for index, value in enumerate(raw, start=1))

    for side in sides:
        if not drills and side.align_s is not None:
            raise Refusal(f"{source}: side '{side.name}': 'align_s' needs 'drills': the "
                          f"alignment exposure is read by the holes, and there are none")
        if not drills and side.holes:
            raise Refusal(f"{source}: side '{side.name}': 'holes = true' needs 'drills': "
                          f"there is nothing to subtract")
    return BoardConfig(template=template, outline=outline, drills=drills,
                       pixel_um=pixel_um, sides=sides, text=text, path=path)


def _must_exist(target: Path, key: str, where: str, source: str) -> None:
    """A missing input file is refused with the KEY that points at it and the path."""
    if not target.exists():
        raise Refusal(f"{source}: {where}: '{key}' points to {target}, and no such file "
                      f"exists (paths count from the config's own directory)")


def load_board_config(path: str | Path) -> BoardConfig:
    """Read the file as UTF-8, resolve the paths against ITS directory, check they exist."""
    target = Path(path)
    text = _read_text(target, "the board config")
    config = parse_board_config(text, source=str(target), base=target.parent, path=target)
    _must_exist(config.template, "template", "[board]", str(target))
    _must_exist(config.outline, "outline", "[board]", str(target))
    for index, drill in enumerate(config.drills):
        _must_exist(drill, f"drills[{index}]", "[board]", str(target))
    for side in config.sides:
        _must_exist(side.copper, "copper", f"side '{side.name}'", str(target))
    return config


__all__ = ["BOARD_KEYS", "BoardConfig", "ROOT_KEYS", "SIDE_KEYS", "SIDE_NAME", "SideSpec",
           "load_board_config", "parse_board_config"]
