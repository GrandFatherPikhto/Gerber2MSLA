"""`gerber2msla/px6s_write.py`: the writer, checked against the real template (П2).

The template is `tests/data/01_test02.px6s` — the slicer's own one-layer file, copied
byte for byte from `techdocs/px6s_examples/`. The cells read it as the oracle:

    тождество       наш кодировщик воспроизводит байты слоя Photon Workshop; файл,
                     записанный с тем же временем, равен шаблону ВЕЗДЕ, кроме превью
    круг            маска (метка F, пластина) -> write -> read_file -> те же пиксели
    блоки станка    MACHINE, EXTRA, SOFTWARE, MODEL, подъёмы и скорости — те же байты
    отказы          размер, значения, версия шаблона, число слоёв
    зеркало         --mirror-x отражает маску до кодирования
    отчёт           время, LightPWM словами, белые пиксели и мм²

The preview pixels are the ONE place a rewrite cannot be identical: Photon Workshop's own
downscale is not reproducible by us, so the cell states that explicitly instead of hiding
it.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from gerber2msla.cli import main
from gerber2msla.masks import Refusal
from gerber2msla.px6s import ADDRESS_COUNT, ADDRESS_FIELDS, MARK_SIZE, read_file
from gerber2msla.px6s_write import encode_pw0, mark_size, write_from_template

DATA = Path(__file__).resolve().parents[1] / "tests" / "data"
TEMPLATE = DATA / "01_test02.px6s"
PREVIEW_W, PREVIEW_H = 224, 168
PREVIEW_BYTES = PREVIEW_W * PREVIEW_H * 2

SCREEN_ARGS = ("--screen-px", "5760x3600", "--pixel-um", "34x34")


def _template():
    if not TEMPLATE.is_file():
        pytest.skip(f"no {TEMPLATE}: the real template is copied into tests/data")
    return read_file(TEMPLATE)


def _blocks(printer):
    """(name, address, payload) of every addressed block, in file order, plus the layer."""
    data = printer._data
    addressed = sorted(((name, address) for name, address in printer.mark.addresses.items()
                        if address), key=lambda item: item[1])
    blocks = []
    for index, (name, address) in enumerate(addressed):
        if name == "layer_image":
            length = printer.layers[0].data_length
        else:
            length = addressed[index + 1][1] - address
        blocks.append((name, address, data[address:address + length]))
    return blocks


def _preview_range(printer) -> tuple[int, int]:
    start = printer.mark.addresses["preview"] + 28
    return start, start + PREVIEW_BYTES


def test_the_layer_is_encoded_exactly_as_the_slicer_did():
    """Our pw0Img encoder reproduces Photon Workshop's bytes for the same picture."""
    printer = _template()
    layer = printer.layers[0]
    original = printer._data[layer.data_address:layer.data_address + layer.data_length]
    assert encode_pw0(printer.layer_image(0)) == original


def test_writing_the_template_layer_back_gives_the_template_outside_the_preview():
    """Identity: only the preview pixels may differ, and they MUST (they are regenerated)."""
    printer = _template()
    written = write_from_template(printer, printer.layer_image(0), 25.0)
    assert len(written.data) == len(printer._data)

    start, end = _preview_range(printer)
    expected = bytearray(printer._data)
    expected[start:end] = written.data[start:end]
    assert written.data == bytes(expected), "every byte outside the preview is the template"
    assert written.data[start:end] != printer._data[start:end], \
        "the preview is rebuilt from the mask, so it cannot stay the slicer's bytes"


def test_the_machine_blocks_stay_byte_for_byte(tmp_path):
    printer = _template()
    written = write_from_template(printer, printer.layer_image(0), 25.0)
    for name in ("machine", "extra", "software", "model"):
        address = printer.mark.addresses[name]
        length = dict((block_name, len(payload))
                      for block_name, _, payload in _blocks(printer))[name]
        assert written.data[address:address + length] == printer._data[address:address + length], \
            f"the {name} block must not change"
    # the header's lift height and speeds (offset 40 … 56) stay too; only the times move
    header = printer.mark.addresses["header"]
    assert written.data[header + 40:header + 56] == printer._data[header + 40:header + 56]


def _mask_png(tmp_path: Path, *args: str, name: str = "mask.png") -> Path:
    target = tmp_path / name
    assert main(["masks", *args, "-o", str(target)]) == 0
    return target


def _write(tmp_path: Path, mask: Path, *extra: str, name: str = "out.px6s") -> Path:
    target = tmp_path / name
    code = main(["write", str(mask), "--template", str(TEMPLATE), "-o", str(target),
                 "--exposure-s", "25", *extra])
    assert code == 0, f"the writer refused: {code}"
    return target


def test_a_mask_with_the_marker_makes_the_round_trip(tmp_path):
    """PNG -> write -> read_file -> the same pixels, and both times are ours."""
    mask = _mask_png(tmp_path, "bars", *SCREEN_ARGS, "--widths-mm", "0.2", "--lines", "1",
                     "--at", "0,0", name="bars.png")
    target = _write(tmp_path, mask)
    written = read_file(target)
    assert np.array_equal(written.layer_image(0), np.array(Image.open(mask)))
    assert written.header.exposure_s == pytest.approx(25.0)
    assert written.header.bottom_exposure_s == pytest.approx(25.0)
    assert written.header.bottom_layers == 1.0
    assert written.layer_count == 1


def test_the_plate_makes_the_round_trip(tmp_path):
    """The plate with all the tests is written by the same path and read back unchanged."""
    mask = _mask_png(tmp_path, "plate", *SCREEN_ARGS, name="plate.png")
    target = _write(tmp_path, mask, name="plate_25s.px6s")
    written = read_file(target)
    assert np.array_equal(written.layer_image(0), np.array(Image.open(mask)))


def test_mirror_x_reflects_the_mask_before_encoding(tmp_path):
    mask = _mask_png(tmp_path, "bars", *SCREEN_ARGS, "--widths-mm", "0.2", "--lines", "1",
                     "--at", "0,0", name="bars.png")
    target = _write(tmp_path, mask, "--mirror-x")
    written = read_file(target)
    assert np.array_equal(written.layer_image(0), np.fliplr(np.array(Image.open(mask))))
    assert not np.array_equal(written.layer_image(0), np.array(Image.open(mask)))


def test_the_report_names_the_time_brightness_and_white_area(tmp_path, capsys):
    mask = _mask_png(tmp_path, "bars", *SCREEN_ARGS, "--widths-mm", "0.2", "--lines", "1",
                     "--at", "0,0", name="bars.png")
    capsys.readouterr()
    target = _write(tmp_path, mask, name="reported.px6s")
    out = capsys.readouterr().out
    white = int((np.array(Image.open(mask)) > 0).sum())
    assert f"template: {TEMPLATE}" in out
    assert "resolution: 5760 x 3600 px; pixel 34.00 um" in out
    assert "exposure: normal 25.000 s, bottom 25.000 s, bottom layers 1, layers 1" in out
    assert "light pwm: not stored in px6s v517" in out
    assert "mirror: off" in out
    assert f"white: {white} px = " in out and " mm2" in out
    assert f"Wrote {target}: 5760 x 3600 px mask" in out


def test_a_mask_of_the_wrong_size_is_refused():
    printer = _template()
    with pytest.raises(Refusal) as exc:
        write_from_template(printer, np.zeros((10, 10), dtype=np.uint8), 25.0)
    assert "10x10 px" in str(exc.value)
    assert "5760 x 3600 px" in str(exc.value)


def test_values_other_than_black_and_white_are_refused():
    printer = _template()
    mask = printer.layer_image(0).copy()
    mask[0, 0] = 128
    with pytest.raises(Refusal) as exc:
        write_from_template(printer, mask, 25.0)
    assert "other than 0 and 255" in str(exc.value)
    assert "128" in str(exc.value)


def test_a_template_of_another_version_is_refused():
    printer = _template()
    other = replace(printer, mark=replace(printer.mark, version=516))
    with pytest.raises(Refusal) as exc:
        write_from_template(other, printer.layer_image(0), 25.0)
    assert "version 516" in str(exc.value)
    assert "517" in str(exc.value)


def test_a_template_with_more_than_one_layer_is_refused():
    printer = _template()
    two = replace(printer, layers=printer.layers * 2)
    with pytest.raises(Refusal) as exc:
        write_from_template(two, printer.layer_image(0), 25.0)
    assert "2 layer(s)" in str(exc.value)


def _reordered_template(tmp_path: Path) -> Path:
    """The same template with MODEL moved AFTER the layer image: addresses must move."""
    printer = _template()
    blocks = _blocks(printer)
    order = [block for block in blocks if block[0] != "model"]
    order += [block for block in blocks if block[0] == "model"]

    offsets: dict[str, int] = {}
    position = mark_size(printer.mark.version)
    for name, _, payload in order:
        offsets[name] = position
        position += len(payload)

    mark = bytearray(printer._data[:mark_size(printer.mark.version)])
    base = MARK_SIZE + 8
    for index, name in enumerate(ADDRESS_FIELDS[:ADDRESS_COUNT[printer.mark.version]]):
        mark[base + index * 4:base + index * 4 + 4] = offsets.get(name, 0).to_bytes(4, "little")

    body = bytearray()
    for name, _, payload in order:
        if name == "layer_definition":
            payload = bytearray(payload)
            payload[20:24] = offsets["layer_image"].to_bytes(4, "little")
            payload = bytes(payload)
        body += payload

    path = tmp_path / "reordered.px6s"
    path.write_bytes(bytes(mark) + bytes(body))
    return path


def test_a_block_after_the_layer_data_moves_with_it(tmp_path):
    """A shorter layer pushes MODEL: a stale address would leave a pointer inside the data."""
    path = _reordered_template(tmp_path)
    printer = read_file(path)
    assert printer.mark.addresses["model"] > printer.layers[0].data_address

    blank = np.zeros((printer.header.resolution_y, printer.header.resolution_x), dtype=np.uint8)
    written = write_from_template(printer, blank, 25.0)
    target = tmp_path / "blank.px6s"
    target.write_bytes(written.data)

    reread = read_file(target)
    layer = reread.layers[0]
    assert reread.mark.addresses["model"] == layer.data_address + layer.data_length, \
        "the model block must sit right after the new layer data"
    length = 48
    start = reread.mark.addresses["model"]
    assert written.data[start:start + length] == printer._data[
        printer.mark.addresses["model"]:printer.mark.addresses["model"] + length]
    assert not reread.layer_image(0).any()
