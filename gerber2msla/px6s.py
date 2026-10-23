# gerber2msla/px6s.py
"""Read an Anycubic ``.px6s`` file (format description: ``docs/format_px6s.md``).

READ ONLY: this module never writes a printer file. The description was taken from
UVtools (AGPL) as a FORMAT, not as code: every field in ``docs/format_px6s.md`` names the
class and method it was read from. Nothing here is copied or translated from C#.

What the reader gives the rest of the tool:

  * the file mark — signature, version, and the addresses of the blocks;
  * the HEADER table — pixel size, layer height, normal and BOTTOM exposure, bottom layer
    count, resolution;
  * the MACHINE table — printer name, layer image format and the pixel size the machine
    reports;
  * LAYERDEF — one 32-byte record per layer: where its RLE data starts, how long it is,
    the layer's own exposure time, lift and height;
  * the layer image itself, decoded from the ``pw0Img`` run-length code.

The layer picture is returned as a ``uint8`` array of shape ``(height, width)``: row 0 is
the FIRST row of the layer data, which is the top of the image as the file stores it. The
file itself has no mirror flag — ``display_mirror_x`` lives in the slicer profile, not in
``px6s`` — so a caller that needs an unmirrored mask must decide it itself.

The format is little-endian throughout (the C# serializer writes binary little-endian).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

MARK = b"ANYCUBIC"
MARK_SIZE = 12
VERSION_515 = 515
VERSION_516 = 516
VERSION_517 = 517
VERSION_518 = 518
KNOWN_VERSIONS = (VERSION_515, VERSION_516, VERSION_517, VERSION_518)

ADDRESS_FIELDS = (
    "header", "software", "preview", "layer_image_color_table", "layer_definition",
    "extra", "machine", "layer_image", "model", "sub_layer_definition", "preview2",
)
"""Addresses stored in the file mark, in file order; how many of them a version has."""
ADDRESS_COUNT = {VERSION_515: 7, VERSION_516: 8, VERSION_517: 9, VERSION_518: 11}

LAYER_DEF_SIZE = 32
"""One layer record: address, length, lift height, lift speed, exposure, height, pixels, pad."""

TABLE_NAME_SIZE = 12
TABLE_BASE_SIZE = TABLE_NAME_SIZE + 4


class Px6sError(Exception):
    """The file is not a px6s this reader understands; the message says what was found."""


@dataclass(frozen=True, slots=True)
class FileMark:
    """The first block: signature, version and where every other block starts."""

    version: int
    table_count: int
    addresses: dict[str, int]


@dataclass(frozen=True, slots=True)
class Header:
    """The HEADER table: the print's own numbers, in the units the file stores."""

    table_length: int
    pixel_size_um: float
    layer_height_mm: float
    exposure_s: float
    wait_before_cure_s: float
    bottom_exposure_s: float
    bottom_layers: float
    lift_height_mm: float
    lift_speed_mm_s: float
    retract_speed_mm_s: float
    resolution_x: int
    resolution_y: int
    anti_aliasing: int


@dataclass(frozen=True, slots=True)
class Machine:
    """The MACHINE table: the printer's name, its layer format and the pixel it reports."""

    name: str
    layer_image_format: str
    resolution_x: int
    resolution_y: int
    pixel_width_um: float
    pixel_height_um: float


@dataclass(frozen=True, slots=True)
class LayerInfo:
    """One LAYERDEF record — where the layer data is and what this layer asks for."""

    data_address: int
    data_length: int
    lift_height_mm: float
    lift_speed_mm_s: float
    exposure_s: float
    layer_height_mm: float
    non_zero_pixels: int


@dataclass(frozen=True, slots=True)
class Px6sFile:
    """A parsed file: the blocks' numbers and the layer records; images decode on demand."""

    path: Path
    mark: FileMark
    header: Header
    machine: Machine | None
    layers: tuple[LayerInfo, ...]
    _data: bytes

    @property
    def layer_count(self) -> int:
        return len(self.layers)

    def layer_image(self, index: int = 0) -> np.ndarray:
        """Decode layer ``index`` (0 is the BOTTOM layer) to a ``(height, width)`` array."""
        if not 0 <= index < len(self.layers):
            raise Px6sError(f"layer {index} does not exist: the file has "
                            f"{len(self.layers)} layer(s)")
        layer = self.layers[index]
        start = layer.data_address
        end = start + layer.data_length
        if start < 0 or end > len(self._data):
            raise Px6sError(f"layer {index} data {start} ... {end} is outside the file "
                            f"of {len(self._data)} bytes")
        return decode_pw0(self._data[start:end], self.header.resolution_x,
                          self.header.resolution_y)


# ────────────────────────────── low level ──────────────────────────────────

def _u32(data: bytes, offset: int, what: str) -> int:
    if offset + 4 > len(data):
        raise Px6sError(f"the file ends inside {what}: need 4 bytes at {offset}, "
                        f"the file has {len(data)}")
    return struct.unpack_from("<I", data, offset)[0]


def _f32(data: bytes, offset: int) -> float:
    return struct.unpack_from("<f", data, offset)[0]


def _text(data: bytes, offset: int, size: int) -> str:
    chunk = data[offset:offset + size]
    return chunk.split(b"\x00", 1)[0].decode("ascii", errors="replace")


def _table_name(data: bytes, offset: int) -> tuple[str, int]:
    """The 12-byte name and the 4-byte table length that open every named block."""
    if offset + TABLE_BASE_SIZE > len(data):
        raise Px6sError(f"the file ends inside a table header at {offset}")
    return _text(data, offset, TABLE_NAME_SIZE), _u32(data, offset + TABLE_NAME_SIZE, "a table length")


# ────────────────────────────── the blocks ─────────────────────────────────

def _read_mark(data: bytes) -> FileMark:
    if len(data) < MARK_SIZE + 8:
        raise Px6sError(f"too short for a px6s file: {len(data)} bytes")
    if data[:MARK_SIZE].split(b"\x00", 1)[0] != MARK:
        found = data[:MARK_SIZE].split(b"\x00", 1)[0].decode("ascii", errors="replace")
        raise Px6sError(f"not a px6s file: the mark is {found!r}, expected {MARK!r}")
    version = _u32(data, MARK_SIZE, "the version")
    if version not in KNOWN_VERSIONS:
        raise Px6sError(f"unsupported px6s version {version}: this reader knows "
                        f"{', '.join(str(v) for v in KNOWN_VERSIONS)}")
    table_count = _u32(data, MARK_SIZE + 4, "the table count")
    count = ADDRESS_COUNT[version]
    base = MARK_SIZE + 8
    if base + count * 4 > len(data):
        raise Px6sError(f"the file ends inside the {count} block addresses of version {version}")
    addresses = {name: _u32(data, base + index * 4, f"the {name} address")
                 for index, name in enumerate(ADDRESS_FIELDS[:count])}
    return FileMark(version=version, table_count=table_count, addresses=addresses)


def _read_header(data: bytes, address: int) -> Header:
    name, length = _table_name(data, address)
    if name != "HEADER":
        raise Px6sError(f"the header address {address} holds {name!r}, expected 'HEADER'")
    base = address + TABLE_BASE_SIZE
    need = base + 72
    if length < 72 or need > len(data):
        raise Px6sError(f"the HEADER table is {length} bytes; at least 72 are required")
    return Header(
        table_length=length,
        pixel_size_um=_f32(data, base + 0),
        layer_height_mm=_f32(data, base + 4),
        exposure_s=_f32(data, base + 8),
        wait_before_cure_s=_f32(data, base + 12),
        bottom_exposure_s=_f32(data, base + 16),
        bottom_layers=_f32(data, base + 20),
        lift_height_mm=_f32(data, base + 24),
        lift_speed_mm_s=_f32(data, base + 28),
        retract_speed_mm_s=_f32(data, base + 32),
        anti_aliasing=_u32(data, base + 40, "the anti-aliasing level"),
        resolution_x=_u32(data, base + 44, "the resolution X"),
        resolution_y=_u32(data, base + 48, "the resolution Y"),
    )


def _read_machine(data: bytes, address: int) -> Machine:
    name, length = _table_name(data, address)
    if name != "MACHINE":
        raise Px6sError(f"the machine address {address} holds {name!r}, expected 'MACHINE'")
    base = address + TABLE_BASE_SIZE
    if base + 144 > len(data) or length < 144:
        raise Px6sError(f"the MACHINE table is {length} bytes; at least 144 are required")
    machine = Machine(
        name=_text(data, base, 96),
        layer_image_format=_text(data, base + 96, 16),
        pixel_width_um=0.0,
        pixel_height_um=0.0,
        resolution_x=0,
        resolution_y=0,
    )
    if length >= 160:
        machine = replace(machine, pixel_width_um=_f32(data, base + 140))
    if length >= 164:
        machine = replace(machine, pixel_height_um=_f32(data, base + 144))
    if length >= 206:
        machine = replace(machine,
                          resolution_x=struct.unpack_from("<H", data, base + 188)[0])
    if length >= 208:
        machine = replace(machine,
                          resolution_y=struct.unpack_from("<H", data, base + 190)[0])
    return machine


def _read_layers(data: bytes, address: int) -> tuple[LayerInfo, ...]:
    name, length = _table_name(data, address)
    if name != "LAYERDEF":
        raise Px6sError(f"the layer address {address} holds {name!r}, expected 'LAYERDEF'")
    base = address + TABLE_BASE_SIZE
    count = _u32(data, base, "the layer count")
    expected = 4 + count * LAYER_DEF_SIZE
    if length != expected:
        raise Px6sError(f"LAYERDEF says {count} layer(s), which is {expected} bytes, "
                        f"but its length field is {length}")
    start = base + 4
    if start + count * LAYER_DEF_SIZE > len(data):
        raise Px6sError(f"the file ends inside the {count} layer records")
    layers = []
    for index in range(count):
        offset = start + index * LAYER_DEF_SIZE
        layers.append(LayerInfo(
            data_address=_u32(data, offset, "a layer data address"),
            data_length=_u32(data, offset + 4, "a layer data length"),
            lift_height_mm=_f32(data, offset + 8),
            lift_speed_mm_s=_f32(data, offset + 12),
            exposure_s=_f32(data, offset + 16),
            layer_height_mm=_f32(data, offset + 20),
            non_zero_pixels=_u32(data, offset + 24, "a layer pixel count"),
        ))
    return tuple(layers)


def read_file(path: str | Path) -> Px6sFile:
    """Parse the blocks and the layer records; the layer images are decoded on demand."""
    target = Path(path)
    try:
        data = target.read_bytes()
    except OSError as error:
        raise Px6sError(f"cannot read {target}: {error.strerror or error}") from None
    mark = _read_mark(data)
    header = _read_header(data, mark.addresses["header"])
    machine_address = mark.addresses.get("machine", 0)
    machine = _read_machine(data, machine_address) if machine_address else None
    layer_address = mark.addresses.get("layer_definition", 0)
    if not layer_address:
        raise Px6sError("the file has no LAYERDEF table address")
    layers = _read_layers(data, layer_address)
    return Px6sFile(path=target, mark=mark, header=header, machine=machine, layers=layers,
                    _data=data)


# ────────────────────────────── layer codec ────────────────────────────────

def decode_pw0(encoded: bytes, width: int, height: int) -> np.ndarray:
    """Decode the ``pw0Img`` run-length code into a ``(height, width)`` uint8 array.

    A byte carries a 4-bit code and a 4-bit count: code 0 and 0xF are black and white with
    the count in the NEXT byte (the nibble is its high part, so up to 4095 pixels), every
    other code is a grey level ``code * 17`` repeated ``count`` times. The runs fill the
    image row by row; a run may not cross the end and the data may not end short.
    """
    expected = width * height
    image = np.zeros(expected, dtype=np.uint8)
    position = 0
    index = 0
    length = len(encoded)
    while index < length:
        byte = encoded[index]
        code = byte >> 4
        repeat = byte & 0x0F
        if code == 0x0:
            color = 0
            index += 1
            if index >= length:
                repeat = expected - position
            else:
                repeat = (repeat << 8) + encoded[index]
        elif code == 0xF:
            color = 255
            index += 1
            if index >= length:
                repeat = expected - position
            else:
                repeat = (repeat << 8) + encoded[index]
        else:
            color = (code << 4) | code
        index += 1

        if position + repeat > expected:
            raise Px6sError(f"the run-length data runs off the end: {position} + {repeat} "
                            f"= {position + repeat}, the layer holds {expected} pixels")
        image[position:position + repeat] = color
        position += repeat
        if position == expected:
            break

    if position != expected:
        raise Px6sError(f"the run-length data ends short: {position} pixels of {expected}")
    return image.reshape(height, width)
