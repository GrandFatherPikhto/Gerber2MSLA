"""`gerber2msla/dose.py`: the ladder of times and the files it makes (П5в).

Two forms of the ladder, never both: an explicit list and a geometric series
``ratio = (stop/start) ** (1/(count - 1))`` — dose acts by multiplication, so equal steps in
TIME are not equal steps in dose. The same template as everywhere else,
`tests/data/01_test02.px6s`, is the oracle for the written files: every file must carry its
OWN time in both fields and the SAME layer as the mask.
"""
from pathlib import Path

import numpy as np
import pytest

from gerber2msla.dose import (check_names, report, series_file, times_from_list,
                              times_from_series, times_from_series_args, write_series)
from gerber2msla.masks import Refusal
from gerber2msla.px6s import read_file

DATA = Path(__file__).resolve().parents[1] / "tests" / "data"
TEMPLATE = DATA / "01_test02.px6s"


def _template():
    """The template is IN GIT: its absence is a break, not a reason to skip a guard."""
    if not TEMPLATE.is_file():
        pytest.fail(f"no {TEMPLATE}: the real template is committed, so a missing file "
                    f"breaks every cell that reads it")
    return TEMPLATE


def test_a_geometric_series_has_both_ends_and_a_constant_ratio():
    """15 ... 35 in five levels: both ends exactly, and one ratio between neighbours."""
    times = times_from_series(15.0, 35.0, 5)
    assert len(times) == 5
    assert times[0] == pytest.approx(15.0)
    assert times[-1] == pytest.approx(35.0)
    ratios = [upper / lower for lower, upper in zip(times, times[1:])]
    assert max(ratios) - min(ratios) == pytest.approx(0.0, abs=1e-9)
    assert ratios[0] == pytest.approx((35.0 / 15.0) ** (1.0 / 4.0))


SERIES_REFUSALS = (
    (15.0, 35.0, 1, "at least two levels"),
    (25.0, 25.0, 3, "rises"),
    (35.0, 15.0, 3, "rises"),
    (0.0, 35.0, 3, "finite positive"),
    (-1.0, 35.0, 3, "finite positive"),
)
"""A flat series is the same file under different names — it cannot be a ladder."""


@pytest.mark.parametrize("start, stop, count, expected", SERIES_REFUSALS)
def test_a_series_needs_two_levels_and_a_rising_pair(start, stop, count, expected):
    with pytest.raises(Refusal) as exc:
        times_from_series(start, stop, count)
    assert expected in str(exc.value)


def test_the_series_arguments_are_three_words():
    """`--series START STOP COUNT` as typed: a non-number or a zero count is a refusal."""
    assert times_from_series_args(("15", "35", "5")) == pytest.approx(
        times_from_series(15.0, 35.0, 5))
    for words in (("15", "35", "many"), ("15", "35"), ("a", "b", "c")):
        with pytest.raises(Refusal) as exc:
            times_from_series_args(words)
        assert "START STOP COUNT" in str(exc.value)


LIST_REFUSALS = (
    ("15,15", "repeated time"),
    ("15,,20", "comma separated"),
    ("", "comma separated"),
    ("15,x", "numbers of seconds"),
    ("15,0", "finite and positive"),
    ("15,-5", "finite and positive"),
)


@pytest.mark.parametrize("text, expected", LIST_REFUSALS)
def test_a_list_of_times_refuses_what_is_not_a_ladder(text, expected):
    """One time is one file: a repeated time would overwrite, and a comma may not be empty."""
    with pytest.raises(Refusal) as exc:
        times_from_list(text)
    assert expected in str(exc.value)


def test_the_list_of_times_is_parsed_with_spaces():
    assert times_from_list("15, 20,25") == (15.0, 20.0, 25.0)


def test_the_file_name_carries_the_time():
    """One decimal: the name says what time the file holds, and the operator reads it."""
    assert series_file("out/dose", 25.0) == Path("out/dose_25.0s.px6s")
    assert series_file("/tmp/run", 12.5).name == "run_12.5s.px6s"


def test_two_times_that_round_to_one_name_are_refused():
    """15.04 and 15.03 s both print as one name: one file would silently overwrite the other."""
    with pytest.raises(Refusal) as exc:
        check_names("out/dose", (15.04, 15.03))
    assert "one file name" in str(exc.value)


def test_a_series_of_times_writes_a_file_each_with_its_own_time(tmp_path):
    template = _template()
    mask = read_file(template).layer_image(0)
    files = write_series(template, mask, tmp_path / "dose", (15.0, 20.0, 25.0))
    assert [path.name for path in files] == ["dose_15.0s.px6s", "dose_20.0s.px6s",
                                            "dose_25.0s.px6s"]
    for path, seconds in zip(files, (15.0, 20.0, 25.0), strict=True):
        header = read_file(path).header
        assert header.exposure_s == pytest.approx(seconds)
        assert header.bottom_exposure_s == pytest.approx(seconds)


def test_every_file_of_a_series_carries_the_same_layer(tmp_path):
    template = _template()
    mask = read_file(template).layer_image(0)
    files = write_series(template, mask, tmp_path / "dose", (15.0, 25.0))
    layers = [read_file(path).layer_image(0) for path in files]
    assert np.array_equal(layers[0], mask)
    assert np.array_equal(layers[1], layers[0]), "one mask, one layer, any time"


def test_the_report_reads_the_times_back_from_the_files(tmp_path):
    """The table is the files' own numbers, not the numbers the command was given."""
    template = _template()
    mask = read_file(template).layer_image(0)
    files = write_series(template, mask, tmp_path / "dose", (15.0, 25.0))
    lines = report(files)
    assert lines[0].split() == ["file", "normal", "bottom"]
    for line, path, seconds in zip(lines[1:], files, (15.0, 25.0), strict=True):
        assert line.startswith(str(path))
        assert line.split()[1:] == [f"{seconds:.3f}", "s", f"{seconds:.3f}", "s"]
