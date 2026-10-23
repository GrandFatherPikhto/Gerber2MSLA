"""The printer-file command line: `write` and `dump`.

The `write` cell moved here from `tests/test_cli.py` in the П2 fix, unchanged: a module's
cells live in the file of that module (`gerber2msla/cli_px6s.py`). The `dump` cells (П3)
check the COMMAND LINE and the numbers it prints — the format itself is held by
`tests/test_px6s_write.py` and `tests/test_px6s.py`.

The template `tests/data/01_test02.px6s` is the oracle: its numbers were confirmed by
UVtoolsCmd, so the dump must print them back.
"""
import struct
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from gerber2msla.cli import main
from gerber2msla.px6s import read_file

DATA = Path(__file__).resolve().parents[1] / "tests" / "data"
TEMPLATE = DATA / "01_test02.px6s"
SCREEN_ARGS = ("--screen-px", "5760x3600", "--pixel-um", "34x34")


def _template() -> Path:
    """The template is IN GIT: its absence is a break, not a reason to skip a guard."""
    if not TEMPLATE.is_file():
        pytest.fail(f"no {TEMPLATE}: the real template is committed, so a missing file "
                    f"breaks every cell that reads it")
    return TEMPLATE


def test_write_refuses_a_mask_that_is_not_mode_l(tmp_path, capsys):
    """A colour PNG is not a mask: one line, code 2, and no file left behind."""
    template = _template()
    mask = tmp_path / "rgb.png"
    Image.fromarray(np.zeros((8, 8, 3), dtype=np.uint8), mode="RGB").save(mask)
    target = tmp_path / "out.px6s"
    assert main(["write", str(mask), "--template", str(template), "-o", str(target),
                 "--exposure-s", "25"]) == 2
    err = capsys.readouterr().err
    assert "mode L" in err and "RGB" in err
    assert not target.exists()


def test_dump_prints_the_numbers_uvtools_confirmed(capsys):
    """Every field Denis asked for, with the numbers UVtoolsCmd printed for this file."""
    template = _template()
    assert main(["dump", str(template)]) == 0
    out = capsys.readouterr().out
    assert f"file: {template}" in out
    assert "version: 517; blocks: 9" in out
    assert "machine: Anycubic Photon Mono X 6Ks (pw0Img)" in out
    assert "resolution: 5760 x 3600 px; pixel 34.00 um" in out
    assert "exposure: normal 25.000 s, bottom 25.000 s, bottom layers 1, layers 1" in out
    assert "lift: height 8.000 mm at 2.000 mm/s; retract 3.000 mm/s" in out
    assert "layer 0: @ 75976, 11620 bytes" in out
    assert "nonzero 3805630 px" in out
    for block in ("header@56", "preview@164", "layer_image_color_table@75456",
                  "layer_definition@75484", "extra@75536", "machine@75608",
                  "software@75764", "model@75928", "layer_image@75976"):
        assert block in out, f"the block address {block} must be printed"


def test_dump_tells_the_two_exposure_times_apart(tmp_path, capsys):
    """The template's times are equal; patch the bottom one so a swap cannot hide.

    The HEADER table opens with a 16-byte table header; ``BottomExposureTime`` is the
    float at +32 from the table address (docs/format_px6s.md, §4).
    """
    template = _template()
    data = bytearray(template.read_bytes())
    header = read_file(template).mark.addresses["header"]
    struct.pack_into("<f", data, header + 32, 12.0)
    patched = tmp_path / "two-times.px6s"
    patched.write_bytes(bytes(data))
    assert main(["dump", str(patched)]) == 0
    out = capsys.readouterr().out
    assert "exposure: normal 25.000 s, bottom 12.000 s, bottom layers 1, layers 1" in out


def test_dump_writes_the_layer_as_a_png(tmp_path, capsys):
    """-o saves layer 0, exactly the mask the file carries: 0/255 and the same white count."""
    template = _template()
    layer = tmp_path / "layer.png"
    assert main(["dump", str(template), "-o", str(layer)]) == 0
    assert f"Wrote {layer}: 5760 x 3600 px layer 0" in capsys.readouterr().out
    image = Image.open(layer)
    assert image.mode == "L"
    assert image.size == (5760, 3600)
    pixels = np.array(image)
    assert set(np.unique(pixels).tolist()) == {0, 255}
    assert int((pixels > 0).sum()) == 3_805_630


def test_dump_needs_no_output_to_print(tmp_path, capsys):
    """No -o: the numbers only, and nothing written anywhere."""
    template = _template()
    assert main(["dump", str(template)]) == 0
    out = capsys.readouterr().out
    assert "Wrote " not in out
    assert list(tmp_path.iterdir()) == []


def test_the_written_plate_dumps_back_as_the_same_png(tmp_path, capsys):
    """The round trip: masks plate -> write -> dump -o gives the very same picture."""
    template = _template()
    mask = tmp_path / "plate.png"
    assert main(["masks", "plate", *SCREEN_ARGS, "-o", str(mask)]) == 0
    written = tmp_path / "plate.px6s"
    assert main(["write", str(mask), "--template", str(template), "-o", str(written),
                 "--exposure-s", "25"]) == 0
    capsys.readouterr()
    layer = tmp_path / "layer.png"
    assert main(["dump", str(written), "-o", str(layer)]) == 0
    mask_pixels = np.array(Image.open(mask))
    layer_pixels = np.array(Image.open(layer))
    assert np.array_equal(layer_pixels, mask_pixels), "the layer must be the mask, pixel for pixel"
    assert int((layer_pixels > 0).sum()) == int((mask_pixels > 0).sum())


def test_dump_refuses_a_file_that_is_not_px6s(tmp_path, capsys):
    """A file that cannot be read is one line and code 2, and -o stays unwritten."""
    junk = tmp_path / "not-a.px6s"
    junk.write_bytes(b"NOTAPX6S" + b"\x00" * 64)
    target = tmp_path / "layer.png"
    assert main(["dump", str(junk), "-o", str(target)]) == 2
    err = capsys.readouterr().err
    assert "not a px6s" in err
    assert "Traceback" not in err
    assert not target.exists()
