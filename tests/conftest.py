"""Suite-wide fixtures and helpers for the mask cells.

The mask cells all draw on one SMALL screen — 240 x 120 px at 34.4 um, 8.26 x 4.13 mm —
enough for the small bars AND for the 2 mm marker that is on by default. It came here
from Gerber2LDI `tests/test_tools_msla.py` (364fd28) unchanged: the cells still assert
`image.size == (240, 120)` in their own bodies, and a bigger screen would only slow the
run down.

`sixks_screen` is the real printer screen: 5760 x 3600 px at 34 um — from the UVtools /
PrusaSlicer profile, not a verified spec sheet. No cell uses it yet; it is for the px6s
cells of the plan `png2px6s` (П2, П3), which read a real template.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from gerber2msla.cli import main
from gerber2msla.masks import Screen

SMALL_SCREEN_PX = (240, 120)
SMALL_PIXEL_UM = (34.4, 34.4)
RECT_PIXEL_UM = (34.4, 30.0)
"""34.4 um across and 30.0 um down: the same width is 6 px along X and 7 px along Y."""


@pytest.fixture
def screen_args() -> tuple[str, ...]:
    """`--screen-px` of the small screen every mask cell draws on."""
    return ("--screen-px", f"{SMALL_SCREEN_PX[0]}x{SMALL_SCREEN_PX[1]}")


@pytest.fixture
def screen_width_px() -> int:
    return SMALL_SCREEN_PX[0]


@pytest.fixture
def square_pixel_args() -> tuple[str, ...]:
    return ("--pixel-um", f"{SMALL_PIXEL_UM[0]}x{SMALL_PIXEL_UM[1]}")


@pytest.fixture
def rect_pixel_args() -> tuple[str, ...]:
    return ("--pixel-um", f"{RECT_PIXEL_UM[0]}x{RECT_PIXEL_UM[1]}")


@pytest.fixture
def sixks_screen() -> Screen:
    """The printer's own screen, for cells that need real geometry rather than a toy."""
    return Screen(width_px=5760, height_px=3600, pixel_x_um=34.0, pixel_y_um=34.0)


def run_mask(tmp_path: Path, *args: str, name: str = "mask.png") -> Path:
    """Run `gerber2msla masks ...`; a zero exit code is part of the call."""
    target = tmp_path / name
    code = main(["masks", *args, "-o", str(target)])
    assert code == 0, f"the tool refused: {code}"
    return target


def pixels(path: Path) -> np.ndarray:
    """The finished PNG as an array: the picture is the evidence, not the report alone."""
    return np.array(Image.open(path))


def runs(values) -> list[tuple[int, int]]:
    """(value, length) runs of one row or column, in order."""
    collected: list[list[int]] = []
    for value in values:
        value = int(value)
        if collected and collected[-1][0] == value:
            collected[-1][1] += 1
        else:
            collected.append([value, 1])
    return [(value, length) for value, length in collected]


def runs_of_figure(values) -> list[tuple[int, int]]:
    """Runs up to the LAST white pixel: the black margin of the screen is not the mask."""
    values = [int(value) for value in values]
    last = max(index for index, value in enumerate(values) if value)
    return runs(values[:last + 1])
