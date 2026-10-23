# gerber2msla/dose.py
"""The dose series: ONE mask, one printer file per exposure time.

A layer has ONE exposure time for the whole picture, so a ladder "tile = its own dose" on a
single plate is impossible on this printer: the series is a set of FILES, each carrying the
same mask and its own time. Every file goes through `px6s_write.write_file` — there is no
second writing path, and this module adds no byte-level knowledge about the format.

Two forms of the ladder, never both:

  * an explicit list — ``--exposure-s 15,20,25,30,35``;
  * a geometric series — ``--series 15 35 5``, ``ratio = (stop/start) ** (1/(count - 1))``,
    the same arithmetic as Gerber2LDI ``dose.py:_series``: dose acts by multiplication, so
    equal steps in TIME are not equal steps in dose.

Both times in every file are that file's own number: layer 0 of a one-layer file IS the
bottom layer, and the printer exposes it with the bottom time (the trap of П2).

A file is named ``{prefix}_{seconds:.1f}s.px6s``. Two times that ROUND to the same name are
refused — otherwise one exposure would silently overwrite another, and the plate would be
short one level.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Sequence

import numpy as np

from .masks import Refusal
from .px6s import read_file
from .px6s_write import write_file


# ────────────────────────────── the ladder ─────────────────────────────────

def times_from_list(text: str) -> tuple[float, ...]:
    """``15,20,25`` -> the times. A repeated value is refused: one name, one file."""
    parts = [part.strip() for part in text.split(",")]
    if not parts or not all(parts):
        raise Refusal(f"exposures are a comma separated list of seconds, got {text!r}")
    try:
        times = tuple(float(part) for part in parts)
    except ValueError:
        raise Refusal(f"exposures must be numbers of seconds, got {text!r}") from None
    if any(not math.isfinite(value) or value <= 0.0 for value in times):
        raise Refusal(f"exposures must be finite and positive, got {times!r}")
    if len(set(times)) != len(times):
        raise Refusal(f"each exposure is one file: a repeated time would overwrite it, "
                      f"got {times!r}")
    return times


def times_from_series(start: float, stop: float, count: int) -> tuple[float, ...]:
    """A geometric series of ``count`` times from ``start`` to ``stop``, both included."""
    if count < 2:
        raise Refusal(f"a series needs at least two levels, got {count}")
    if not all(math.isfinite(value) and value > 0.0 for value in (start, stop)):
        raise Refusal(f"a series runs between finite positive times, "
                      f"got {start!r} ... {stop!r}")
    if start >= stop:
        raise Refusal(f"a series rises from its first time to its last, "
                      f"got {start!r} ... {stop!r}")
    ratio = (stop / start) ** (1.0 / (count - 1))
    return tuple(start * ratio ** index for index in range(count))


def times_from_series_args(values: Sequence[str]) -> tuple[float, ...]:
    """``--series START STOP COUNT`` as typed: three words, then the rules above."""
    try:
        start_text, stop_text, count_text = values
        start, stop, count = float(start_text), float(stop_text), int(count_text)
    except (ValueError, TypeError):
        raise Refusal(f"a series is START STOP COUNT, got {' '.join(values)!r}") from None
    return times_from_series(start, stop, count)


# ────────────────────────────── the files ──────────────────────────────────

def series_file(prefix: str | Path, seconds: float) -> Path:
    """``out/dose`` and 25 -> ``out/dose_25.0s.px6s``."""
    prefix = Path(prefix)
    return prefix.with_name(f"{prefix.name}_{seconds:.1f}s.px6s")


def check_names(prefix: str | Path, times: Sequence[float]) -> None:
    """Two times that print the same name would overwrite each other — refuse instead."""
    seen: dict[str, float] = {}
    for seconds in times:
        name = series_file(prefix, seconds).name
        if name in seen:
            raise Refusal(f"two times round to one file name {name}: "
                          f"{seen[name]:g} and {seconds:g} s")
        seen[name] = seconds


def write_series(template: str | Path, mask: np.ndarray, prefix: str | Path,
                 times: Sequence[float]) -> tuple[Path, ...]:
    """One file per time, written by the same writer; the NAME carries the time."""
    check_names(prefix, times)
    written = []
    for index in range(len(times)):
        # the name and the content come from the SAME slot of the ladder
        target = series_file(prefix, times[index])
        write_file(template, mask, target, times[index])
        written.append(target)
    return tuple(written)


def report(files: Sequence[Path]) -> tuple[str, ...]:
    """The table «file -> normal and bottom time», read back FROM the files, not from intent."""
    lines = [f"{'file':<40} {'normal':>10} {'bottom':>10}"]
    for path in files:
        header = read_file(path).header
        lines.append(f"{str(path):<40} {header.exposure_s:8.3f} s "
                     f"{header.bottom_exposure_s:8.3f} s")
    return tuple(lines)


__all__ = ["check_names", "report", "series_file", "times_from_list", "times_from_series",
           "times_from_series_args", "write_series"]
