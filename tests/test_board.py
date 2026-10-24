"""Gerber geometry → screen pixels (plan Г1, `board.py`).

Cells closed here — the table of the ONE transformation the module owns:

    выборка по центру      регион 1x1 мм на пикселе 100 мкм → ровно 10x10 px
    своя ось у пикселя     неквадратный пиксель: n по КАЖДОЙ оси
    круглая апертура       вспышка d=0.5 мм → 21 px из 25 известных
    дорожка                середина во всю ширину, закруглённые концы уже, концы равны
    полярность             `%LPC*%` вырезает нарисованное ДО него
    переворот Y (один)     несимметричная «Г» лежит как в Gerber, видом СВЕРХУ
    зеркало                `--mirror` = fliplr ВСЕЙ картинки, один раз (masks.compose)
    отверстия              чёрный круг ВНУТРИ площадки; без --drill площадка сплошная
    рамка по контуру       медь, не касающаяся края контура, встаёт со своим отступом
    отчёт                  сказано, откуда рамка, и есть предупреждение без --outline
    отказы                 больше экрана; не Gerber; не Excellon; пустой слой; пустой контур

Empty cells and why: the `.px6s` round trip (board → write → dump → та же PNG) needs
the command line and belongs to `tests/test_cli_board.py` (Г2); `--invert` and the
marker are `masks.compose`/`masks.add_marker`, whose cells already exist.

Coordinates are written as `%FSLAX46Y46*%` integers of 1e-6 mm: the file states its own
format, so a cell never depends on gerbonara guessing one.
"""
import numpy as np
import pytest

from gerber2msla.board import build_board
from gerber2msla.masks import Refusal, Screen, compose, place_figure

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
X1.0Y1.0
M30
"""

EXCELLON_WITHOUT_HOLES = """M48
FMAT,2
METRIC
T1C0.600
%
G90
G05
T1
M30
"""


def _coord(value: float) -> str:
    return f"{int(round(value * 1e6))}"


def _region(points) -> str:
    """A G36/G37 filled region through the given corners, in millimetres."""
    first_x, first_y = points[0]
    lines = [f"X{_coord(first_x)}Y{_coord(first_y)}D02*", "G36*"]
    for x, y in points[1:]:
        lines.append(f"X{_coord(x)}Y{_coord(y)}D01*")
    lines.append(f"X{_coord(first_x)}Y{_coord(first_y)}D01*")
    lines.append("G37*")
    return "\n".join(lines) + "\n"


def _flash(aperture: str, x_mm: float, y_mm: float, *, dcode: int = 10,
           dark: bool = True) -> str:
    """One flash of ``aperture`` (``C,0.5`` etc.) with its own D-code."""
    return (f"%ADD{dcode}{aperture}*%\n" + ("%LPD*%\n" if dark else "%LPC*%\n")
            + f"G01*\nD{dcode}*\nX{_coord(x_mm)}Y{_coord(y_mm)}D03*\n")


def _layer(*bodies: str) -> str:
    return HEADER + "".join(bodies) + FOOTER


def _screen(width_px: int = 40, height_px: int = 40, pixel_x_um: float = 100.0,
            pixel_y_um: float | None = None) -> Screen:
    return Screen(width_px=width_px, height_px=height_px, pixel_x_um=pixel_x_um,
                  pixel_y_um=pixel_x_um if pixel_y_um is None else pixel_y_um)


def _board(tmp_path, text: str, *, drills=(), outline=None, screen=None, name="board.gbr"):
    path = tmp_path / name
    path.write_text(text)
    return build_board(screen or _screen(), path, drills=drills, outline=outline)


# ───────────────────────── sampling: whole pixels, centre ──────────────────

def test_a_one_millimetre_region_is_ten_pixels_square(tmp_path):
    """1x1 mm on a 100 um pixel is 10x10 px, ALL lit: every centre is inside."""
    figure = _board(tmp_path, _layer(_region([(0.0, 0.0), (1.0, 0.0),
                                              (1.0, 1.0), (0.0, 1.0)])))
    assert figure.pixels.shape == (10, 10)
    assert int(np.count_nonzero(figure.pixels)) == 100


@pytest.mark.parametrize("pixel_x_um, pixel_y_um, shape",
                         [(100.0, 200.0, (5, 10)), (200.0, 100.0, (10, 5)),
                          (100.0, 300.0, (3, 10))],
                         ids=["tall pixel", "wide pixel", "very tall pixel"])
def test_a_pixel_that_is_not_square_counts_pixels_of_its_own_axis(tmp_path, pixel_x_um,
                                                                  pixel_y_um, shape):
    """The same 1x1 mm board: the height follows pixel_y, the width pixel_x."""
    figure = _board(tmp_path, _layer(_region([(0.0, 0.0), (1.0, 0.0),
                                              (1.0, 1.0), (0.0, 1.0)])),
                    screen=_screen(40, 40, pixel_x_um, pixel_y_um))
    assert figure.pixels.shape == shape


def test_a_round_flash_lights_the_pixels_whose_centres_are_inside(tmp_path):
    """d = 0.5 mm on a 100 um pixel: 5x5 frame, 21 px lit, 4 corners outside.

    The frame is the flash's own 0.5 mm box, so the centres sit at 0.8 … 1.2 mm from
    the centre of the pad: the middle row and column are inside, the four corners are
    0.28 mm away and must stay black.
    """
    figure = _board(tmp_path, _layer(_flash("C,0.5", 1.0, 1.0)))
    assert figure.pixels.shape == (5, 5)
    assert int(np.count_nonzero(figure.pixels)) == 21
    assert figure.pixels[2, 2] == 255
    assert figure.pixels[0, 0] == 0 and figure.pixels[4, 4] == 0


def test_a_track_is_wide_in_the_middle_and_narrower_at_its_round_ends(tmp_path):
    """A 2 mm stroke with a 0.5 mm round pen: 0.5 x 2.5 mm frame, 5 x 25 px.

    The middle row carries the whole stroke; the end rows are narrower by the round
    cap, and the two ends are the same width — an asymmetric board would not be.
    """
    body = ("%ADD10C,0.5*%\n%LPD*%\nG01*\nD10*\n"
            f"X{_coord(0.0)}Y{_coord(0.5)}D02*\nX{_coord(2.0)}Y{_coord(0.5)}D01*\n")
    figure = _board(tmp_path, _layer(body))
    assert figure.pixels.shape == (5, 25)
    ink = [int(np.count_nonzero(figure.pixels[row])) for row in range(5)]
    assert ink[2] == 25
    assert ink[0] < ink[2] and ink[4] < ink[2]
    assert ink[0] == ink[4]


def test_a_sliver_off_the_grid_lights_the_pixel_its_centre_falls_into(tmp_path):
    """A 0.1 mm sliver at x 0.25 … 0.35 on a 100 um pixel: column 2, not column 3.

    Centre sampling asks where the CENTRE of a pixel is: the centre at 0.25 mm is inside
    the sliver and the one at 0.35 is not, so column 2 lights. Sampling by the pixel's
    EDGE instead would take `ceil(x/pitch)` and light column 3 — the cell that separates
    "nearest integer" from "nearest edge", which looks identical on a grid-aligned pad.
    """
    copper = tmp_path / "sliver.gbr"
    copper.write_text(_layer(_region([(0.25, 0.0), (0.35, 0.0), (0.35, 1.0), (0.25, 1.0)])))
    outline = tmp_path / "edge.gbr"
    outline.write_text(_layer(_region([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])))
    figure = build_board(_screen(20, 20), copper, outline=outline)
    assert figure.pixels.shape == (10, 10)
    columns = np.flatnonzero(figure.pixels.any(axis=0))
    assert columns.tolist() == [2], "the sliver's centre falls into column 2"


def test_a_clear_object_cuts_the_copper_drawn_before_it(tmp_path):
    """`%LPC*%` is a sequence: the 1x1 mm clear region punches a 2x2 mm region."""
    dark = _region([(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)])
    clear = "%LPC*%\n" + _region([(0.5, 0.5), (1.5, 0.5), (1.5, 1.5), (0.5, 1.5)])
    figure = _board(tmp_path, _layer(dark, clear))
    assert figure.pixels.shape == (20, 20)
    assert figure.pixels[10, 10] == 0, "the middle of the hole must be black"
    assert figure.pixels[0, 0] == 255, "the corner keeps its copper"
    assert int(np.count_nonzero(figure.pixels)) == 400 - 100


# ─────────────────────── the ONE Y flip, and the mirror ────────────────────

def _letter_g(tmp_path):
    """An L: a tall bar on the left (y 1…2) and a foot across the bottom (y 0…1)."""
    return _board(tmp_path, _layer(_region([(0.0, 0.0), (2.0, 0.0), (2.0, 1.0),
                                            (1.0, 1.0), (1.0, 2.0), (0.0, 2.0)])))


def test_the_letter_g_is_read_as_seen_from_above_after_the_one_y_flip(tmp_path):
    """Gerber's Y points up, image rows go down: the tall bar must be TOP-LEFT.

    Swapping the flip — or forgetting it — puts the bar at the bottom, which is the
    defect this cell exists for.
    """
    figure = _letter_g(tmp_path)
    assert figure.pixels.shape == (20, 20)
    top, bottom = figure.pixels[:10], figure.pixels[10:]
    assert np.all(top[:, :10] == 255), "the tall bar (high y in the file) is top-left"
    assert np.all(top[:, 10:] == 0)
    assert np.all(bottom == 255), "the foot (low y) runs the whole width at the bottom"


def test_the_mirror_reflects_the_whole_picture_once(tmp_path):
    """`--mirror` is `masks.compose`'s job: one fliplr of the finished picture."""
    figure = _letter_g(tmp_path)
    screen = _screen(20, 20)
    image, lines = compose(screen, [place_figure(screen, figure, None)],
                           mirror=True, invert=False)
    assert np.array_equal(image, np.fliplr(figure.pixels))
    assert not np.array_equal(image, figure.pixels), "an L must not be mirror-symmetric"
    assert any(line.startswith("mirror: on") for line in lines)


# ───────────────────────────────── holes ───────────────────────────────────

def test_a_hole_is_black_inside_the_pad_and_the_pad_is_solid_without_it(tmp_path):
    """A 0.6 mm hole in a 2 mm pad: black, of the file's diameter, AFTER the copper."""
    pad = _flash("C,2.0", 1.0, 1.0)
    drill = tmp_path / "holes.drl"
    drill.write_text(EXCELLON)
    with_hole = _board(tmp_path, _layer(pad), drills=[drill])
    solid = _board(tmp_path, _layer(pad))
    assert with_hole.pixels.shape == solid.pixels.shape == (20, 20)

    cut = np.argwhere((solid.pixels == 255) & (with_hole.pixels == 0))
    assert cut.size > 0, "the hole must remove copper"
    # 0.6 mm across, sampled by centre: six pixels each way
    assert np.ptp(cut[:, 0]) == 5 and np.ptp(cut[:, 1]) == 5
    assert with_hole.pixels[10, 10] == 0
    assert solid.pixels[10, 10] == 255
    assert np.all(solid.pixels[cut[:, 0], cut[:, 1]] == 255), \
        "every pixel the hole takes was copper before it"
    assert any("holes: 1 of 1 subtracted" in line for line in with_hole.report)
    assert any("tenting" in line for line in solid.report)


def test_the_report_announces_a_hole_narrower_than_two_pixels(tmp_path):
    """A 0.15 mm hole on a 100 um pixel is 1.5 px: announced, not silently closed."""
    pad = _flash("C,2.0", 1.0, 1.0)
    drill = tmp_path / "tiny.drl"
    drill.write_text(EXCELLON.replace("T1C0.600", "T1C0.150"))
    figure = _board(tmp_path, _layer(pad), drills=[drill])
    warnings = [line for line in figure.report
                if line.startswith("warning: ") and "under 2 px" in line]
    assert warnings, "a hole below two pixels must be announced, not silently closed"
    assert "0.150 mm" in warnings[0] and "1.5 px" in warnings[0]


def test_every_drill_file_is_named_with_its_own_count(tmp_path):
    """A file with no hits is legal and must be VISIBLE by name: `0 holes (the file has none)`.

    Two lines, not one summary: a silent zero looks exactly like a file that was never read,
    and a plate is drilled from several files at once.
    """
    pad = _flash("C,2.0", 1.0, 1.0)
    pth = tmp_path / "PTH.drl"
    pth.write_text(EXCELLON)
    npth = tmp_path / "NPTH.drl"
    npth.write_text(EXCELLON_WITHOUT_HOLES)
    figure = _board(tmp_path, _layer(pad), drills=[pth, npth])
    assert "PTH.drl: 1 hole" in figure.report
    assert "NPTH.drl: 0 holes (the file has none)" in figure.report
    assert any(line.startswith("holes: 1 of 1 subtracted") for line in figure.report), \
        "the summary still says how many were actually poured"


# ────────────────────────────────── frame ──────────────────────────────────

def test_the_outline_sets_the_frame_so_the_pad_keeps_its_offset(tmp_path):
    """A 1 mm pad at (1, 1) on a 4 mm board: 10x10 px at image rows 25…34, cols 5…14."""
    copper = tmp_path / "copper.gbr"
    copper.write_text(_layer(_flash("R,1.0X1.0", 1.0, 1.0)))
    outline = tmp_path / "edge.gbr"
    outline.write_text(_layer(_region([(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)])))
    figure = build_board(_screen(50, 50), copper, outline=outline)
    assert figure.pixels.shape == (40, 40)
    white = np.argwhere(figure.pixels == 255)
    assert (white[:, 0].min(), white[:, 0].max()) == (25, 34)
    assert (white[:, 1].min(), white[:, 1].max()) == (5, 14)
    assert any("the outline edge.gbr" in line for line in figure.report)


def test_the_report_warns_when_the_frame_comes_from_the_copper(tmp_path):
    """Without --outline the frame is the copper's box, and two layers cannot align."""
    figure = _board(tmp_path, _layer(_flash("R,1.0X1.0", 1.0, 1.0)))
    warnings = [line for line in figure.report if line.startswith("warning: ")]
    assert len(warnings) == 1 and "--outline" in warnings[0]


# ───────────────────────────────── refusals ────────────────────────────────

def _too_big(tmp_path):
    path = tmp_path / "big.gbr"
    path.write_text(_layer(_region([(0.0, 0.0), (3.0, 0.0), (3.0, 3.0), (0.0, 3.0)])))
    return build_board(_screen(10, 10), path)


def _not_a_gerber(tmp_path):
    path = tmp_path / "note.gbr"
    path.write_text("this is not a gerber at all\n")
    return build_board(_screen(), path)


def _not_an_excellon(tmp_path):
    copper = tmp_path / "copper.gbr"
    copper.write_text(_layer(_flash("C,2.0", 1.0, 1.0)))
    broken = tmp_path / "holes.drl"
    broken.write_text("M48\nthis is not an excellon file at all\n")
    return build_board(_screen(), copper, drills=[broken])


def _copper_without_objects(tmp_path):
    path = tmp_path / "empty.gbr"
    path.write_text(_layer())
    return build_board(_screen(), path)


def _outline_without_objects(tmp_path):
    copper = tmp_path / "copper.gbr"
    copper.write_text(_layer(_flash("C,2.0", 1.0, 1.0)))
    outline = tmp_path / "empty_edge.gbr"
    outline.write_text(_layer())
    return build_board(_screen(), copper, outline=outline)


@pytest.mark.parametrize("build, match", [
    (_too_big, "does not fit the 10 x 10 px screen"),
    (_not_a_gerber, "Cannot read Gerber file"),
    (_not_an_excellon, "Cannot read drill file"),
    # An empty Gerber refuses in the READER, for copper and for outline alike: gerbonara
    # opens any text file and yields no objects, so "no objects" cannot be told apart
    # from "garbage", and a file that draws nothing is not a layer — nor a frame.
    (_copper_without_objects, "holds no Gerber objects"),
    (_outline_without_objects, "holds no Gerber objects"),
], ids=["too big for the screen", "not a gerber", "not an excellon",
        "copper with no objects", "outline with no objects"])
def test_a_board_that_cannot_be_drawn_is_refused(tmp_path, build, match):
    """Every refusal is one `Refusal` with the numbers: `cli.main` prints one line."""
    with pytest.raises(Refusal, match=match):
        build(tmp_path)


def test_the_refusal_about_the_screen_names_millimetres_and_pixels(tmp_path):
    """A refusal must let the operator decide: sizes in mm AND px, no "too big"."""
    with pytest.raises(Refusal) as refused:
        _too_big(tmp_path)
    message = str(refused.value)
    assert "30 x 30 px" in message and "3.000 x 3.000 mm" in message
    assert "10 x 10 px screen" in message
