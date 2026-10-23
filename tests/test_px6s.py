"""`gerber2msla/px6s.py`: reading the Anycubic file (plan `png2px6s`, П1/П1а).

The reader is tested two ways:

  * SYNTHETIC files built here, in `tmp_path`, byte by byte from the description in
    `docs/format_px6s.md` — the file mark, a HEADER, one LAYERDEF record and one layer of
    `pw0Img` runs. This is the evidence for the run-length decoder and for the offsets;
  * the REAL printer files of `techdocs/px6s_examples/` — those cells are skipped until
    Denis allows them into `tests/data/`; the same numbers are printed by the probe
    `diagnostics/probe_px6s_examples_2026_10_23.py`, which is where the format table in
    the document was measured.

Cells:

    длины серий            код 0 и 0xF — два байта (до 4095), прочие — 4 бита (до 15)
    заполнение             строка за строкой, форма (высота, ширина)
    синтетический файл      адреса блоков, HEADER, LAYERDEF, слой декодируется
    отказы                 не px6s; неизвестная версия; данные короче/длиннее картинки
    настоящие файлы         skip: нет tests/data
"""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest

from gerber2msla.px6s import (ADDRESS_COUNT, MARK, Px6sError, decode_pw0, read_file)

WIDTH_PX = 4
HEIGHT_PX = 2
EXPOSURE_S = 12.5
BOTTOM_EXPOSURE_S = 20.0
LAYER_HEIGHT_MM = 0.05


def _runs(pixels: list[int]) -> list[tuple[int, int]]:
    """(value, length) runs of the pixel list, in order."""
    runs: list[list[int]] = []
    for value in pixels:
        if runs and runs[-1][0] == value:
            runs[-1][1] += 1
        else:
            runs.append([value, 1])
    return [(value, length) for value, length in runs]


def _encode_pw0(pixels: list[int]) -> bytes:
    """The pw0Img rules of the description, written out for the synthetic files."""
    encoded = bytearray()
    for value, length in _runs(pixels):
        if value in (0, 255):
            code = 0x0 if value == 0 else 0xF
            while length:
                chunk = min(length, 4095)
                encoded += bytes([(code << 4) | (chunk >> 8), chunk & 0xFF])
                length -= chunk
        else:
            assert value % 17 == 0, "a decoded layer only holds multiples of 17"
            code = value >> 4
            while length:
                chunk = min(length, 15)
                encoded.append((code << 4) | chunk)
                length -= chunk
    return bytes(encoded)


def _px6s_bytes(pixels: list[int], width: int, height: int, *, version: int = 517) -> bytes:
    """A minimal v517 file: mark, HEADER, one LAYERDEF record, one layer of runs."""
    layer = _encode_pw0(pixels)
    header_payload = struct.pack(
        "<10f I I I f f 4s I I I I I H H I",
        34.0, LAYER_HEIGHT_MM, EXPOSURE_S, 1.0, BOTTOM_EXPOSURE_S, 1.0,
        8.0, 2.0, 6.0, 0.0,                    # lift height, lift speed, retract, volume
        1, width, height,                      # anti-aliasing, resolution X, Y
        0.0, 0.0, b"$\x00\x00\x00",            # weight, price, currency
        1, 0, 0, 0,                            # per-layer settings, print time, transitions
        0, 0, 0, 0,                            # advanced mode, grey, blur, resin type
    )
    header = b"HEADER".ljust(12, b"\x00") + struct.pack("<I", len(header_payload)) + header_payload

    # The layer table is fixed: name+length, the count and ONE 32-byte record.
    layerdef_size = 16 + 4 + 32
    mark_size = 20 + 4 * ADDRESS_COUNT[version]
    header_address = mark_size
    layerdef_address = header_address + len(header)
    data_address = layerdef_address + layerdef_size
    layer_record = struct.pack(
        "<I I f f f f I I",
        data_address, len(layer), 8.0, 2.0, EXPOSURE_S, LAYER_HEIGHT_MM,
        sum(1 for p in pixels if p), 0)
    layerdef = (b"LAYERDEF".ljust(12, b"\x00") + struct.pack("<I", 4 + len(layer_record))
                + struct.pack("<I", 1) + layer_record)

    addresses = [0] * ADDRESS_COUNT[version]
    addresses[0] = header_address
    addresses[4] = layerdef_address
    addresses[7] = data_address
    mark = (MARK.ljust(12, b"\x00") + struct.pack("<I", version)
            + struct.pack("<I", len(addresses)) + b"".join(struct.pack("<I", a) for a in addresses))
    return mark + header + layerdef + layer


RUN_CELLS = [
    ("one grey pixel", bytes([0x11]), 1, 1, [17]),
    ("a two-byte black run", bytes([0x00, 0x0A]), 10, 1, [0] * 10),
    ("a two-byte white run", bytes([0xF0, 0x10]), 16, 1, [255] * 16),
    ("short runs of greys", bytes([0x13, 0x22, 0x31]), 6, 1, [17, 17, 17, 34, 34, 51]),
    ("the last byte fills the rest", bytes([0x00]), 5, 1, [0] * 5),
    ("the longest two-byte run", bytes([0xFF, 0xFF]), 4095, 1, [255] * 4095),
]


@pytest.mark.parametrize("encoded, width, height, expected", [cell[1:] for cell in RUN_CELLS],
                         ids=[cell[0] for cell in RUN_CELLS])
def test_the_pw0_runs_decode_to_the_pixels_they_name(encoded, width, height, expected):
    """Code 0 and 0xF take the NEXT byte as the high part of the run; the rest are nibbles."""
    image = decode_pw0(encoded, width, height)
    assert image.shape == (height, width)
    assert np.array_equal(image.ravel(), np.array(expected, dtype=np.uint8))


def test_the_layer_is_filled_row_by_row():
    """The runs fill row 0 first: the picture's first row is the first bytes of the data."""
    pixels = [255, 0, 0, 0, 255, 0]
    image = decode_pw0(_encode_pw0(pixels), 3, 2)
    assert np.array_equal(image[0], np.array([255, 0, 0], dtype=np.uint8))
    assert np.array_equal(image[1], np.array([0, 255, 0], dtype=np.uint8))


def test_the_reader_takes_the_blocks_by_their_addresses(tmp_path):
    """A synthetic v517 file: mark, HEADER, one LAYERDEF record and one decoded layer."""
    pixels = [255, 0, 255, 255, 0, 0, 0, 255]
    path = tmp_path / "tiny.px6s"
    path.write_bytes(_px6s_bytes(pixels, WIDTH_PX, HEIGHT_PX))

    printer = read_file(path)
    assert printer.mark.version == 517
    assert printer.header.resolution_x == WIDTH_PX
    assert printer.header.resolution_y == HEIGHT_PX
    assert printer.header.pixel_size_um == 34.0
    assert printer.header.layer_height_mm == pytest.approx(LAYER_HEIGHT_MM)
    assert printer.header.exposure_s == pytest.approx(EXPOSURE_S)
    assert printer.header.bottom_exposure_s == pytest.approx(BOTTOM_EXPOSURE_S)
    assert printer.header.bottom_layers == 1.0
    assert printer.layer_count == 1
    assert printer.layers[0].exposure_s == pytest.approx(EXPOSURE_S)
    assert printer.layers[0].non_zero_pixels == sum(1 for p in pixels if p)
    assert np.array_equal(printer.layer_image(0),
                          np.array(pixels, dtype=np.uint8).reshape(HEIGHT_PX, WIDTH_PX))


def test_a_file_that_is_not_px6s_is_refused(tmp_path):
    path = tmp_path / "something.bin"
    path.write_bytes(b"NOTAPX6S" + b"\x00" * 64)
    with pytest.raises(Px6sError) as exc:
        read_file(path)
    assert "not a px6s" in str(exc.value)


def test_an_unknown_version_is_named(tmp_path):
    path = tmp_path / "future.px6s"
    data = bytearray(_px6s_bytes([0] * (WIDTH_PX * HEIGHT_PX), WIDTH_PX, HEIGHT_PX))
    struct.pack_into("<I", data, 12, 999)
    path.write_bytes(bytes(data))
    with pytest.raises(Px6sError) as exc:
        read_file(path)
    assert "999" in str(exc.value)


def test_run_length_data_that_ends_short_is_refused():
    with pytest.raises(Px6sError) as exc:
        decode_pw0(bytes([0x11]), 2, 1)
    assert "ends short" in str(exc.value)


def test_run_length_data_that_runs_off_the_end_is_refused():
    with pytest.raises(Px6sError) as exc:
        decode_pw0(bytes([0x1F]), 2, 1)
    assert "runs off the end" in str(exc.value)


DATA = Path(__file__).resolve().parents[1] / "tests" / "data"


def test_the_real_printer_template_decodes():
    """The template allowed into the repository: 01_test02.px6s, numbers in §9 of the doc."""
    path = DATA / "01_test02.px6s"
    if not path.is_file():
        pytest.fail(f"no {path}: the real template is committed, so a missing file breaks "
                    f"the reader's only test on real bytes")
    printer = read_file(path)
    assert printer.mark.version == 517
    assert printer.layer_count == 1
    assert printer.header.resolution_x == 5760
    assert printer.header.resolution_y == 3600
    assert printer.header.pixel_size_um == pytest.approx(34.0)
    assert printer.header.exposure_s == pytest.approx(25.0)
    assert printer.header.bottom_exposure_s == pytest.approx(25.0)
    assert printer.header.bottom_layers == 1.0
    image = printer.layer_image(0)
    assert image.shape == (3600, 5760)
    assert set(np.unique(image).tolist()) == {0, 255}
    assert int((image > 0).sum()) == printer.layers[0].non_zero_pixels == 3_805_630


@pytest.mark.skip(reason="01_test01.px6s is 2.4 MB: it stays a probe in techdocs/px6s_examples/")
def test_the_big_real_file_stays_a_probe():
    """Same cell, different file: printed by diagnostics/probe_px6s_examples_2026_10_23.py."""
