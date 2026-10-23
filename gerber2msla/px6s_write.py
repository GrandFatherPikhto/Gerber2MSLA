# gerber2msla/px6s_write.py
"""Write a one-layer ``.px6s`` by REPLACING the described fields of a real template.

The template is the printer's own file (made by the slicer); everything that belongs to
the machine — the ``MACHINE``, ``EXTRA``, ``SOFTWARE`` and ``MODEL`` tables, the colour
table, the lift heights and speeds, the block order — is copied BYTE FOR BYTE. Only the
fields the format description names are written:

  * the layer image, from our own ``pw0Img`` encoder;
  * ``ExposureTime`` and ``BottomExposureTime``, both set to the requested time, and
    ``BottomLayersCount`` = 1 with a single layer;
  * the layer record's address, length, exposure and non-zero pixel count;
  * the previews (``PREVIEW``, and ``PREVIEW2`` when the template has one), as RGB565;
  * the block addresses in the file mark and the table lengths that move with them.

Format description: ``docs/format_px6s.md``. UVtools (AGPL) was read as a FORMAT only.

What the file does NOT carry is written down as well, not invented: there is no mirror
flag (``--mirror-x`` is the operator's decision) and no brightness field (``LightPWM``
belongs to the printer profile), so the report says so in words.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from .masks import Refusal
from .px6s import (ADDRESS_COUNT, ADDRESS_FIELDS, MARK_SIZE, Px6sFile, VERSION_517,
                   read_file)

WHITE = 255
SUPPORTED_VERSION = VERSION_517
"""The writer knows the version the X6Ks writes; anything else is a refusal."""


@dataclass(frozen=True, slots=True)
class Written:
    """The bytes of the new file plus the report lines that explain them."""

    data: bytes
    report: tuple[str, ...]


# ────────────────────────────── the layer codec ────────────────────────────

def encode_pw0(pixels: np.ndarray) -> bytes:
    """Encode a layer with the ``pw0Img`` run-length code of the description.

    Equal high nibbles of consecutive pixels form one run; neighbouring runs of the same
    colour are merged; a black or white run goes to two bytes (the high nibble and the
    next byte hold its length, at most 4095), any other grey level to one byte with a
    1…15 count. A decoded layer therefore holds multiples of 17 only.
    """
    flat = pixels.ravel()
    if flat.size == 0:
        return b""

    codes = (flat >> 4).astype(np.int16)
    boundaries = np.flatnonzero(np.diff(codes)) + 1
    starts = np.concatenate(([0], boundaries))
    ends = np.concatenate((boundaries, [flat.size]))
    lengths = (ends - starts).tolist()
    colours = codes[starts].tolist()

    encoded = bytearray()
    run_colour = -1
    run_length = 0

    def flush(colour: int, length: int) -> None:
        while length > 0:
            if colour in (0, 0xF):
                chunk = min(length, 4095)
                encoded.extend(((colour << 4) | (chunk >> 8), chunk & 0xFF))
            else:
                chunk = min(length, 15)
                encoded.append((colour << 4) | chunk)
            length -= chunk

    for colour, length in zip(colours, lengths):
        if colour == run_colour:
            run_length += length
        else:
            flush(run_colour, run_length)
            run_colour = colour
            run_length = length
    flush(run_colour, run_length)
    return bytes(encoded)


# ────────────────────────────── the previews ───────────────────────────────

def render_preview_rgb565(mask: np.ndarray, width: int, height: int) -> bytes:
    """The mask as an RGB565 preview: nearest neighbour, little-endian, white stays white.

    The description stores preview pixels as RGB565 (``Preview.Data``; UVtools
    ``EncodeImage(DATATYPE_RGB565, …)``); the size comes from the template, so the block
    length does not change when the mask changes.
    """
    picture = Image.fromarray(mask, mode="L").resize((width, height),
                                                     Image.Resampling.NEAREST)
    grey = np.asarray(picture, dtype=np.uint16)
    red = (grey >> 3) & 0x1F
    green = (grey >> 2) & 0x3F
    blue = (grey >> 3) & 0x1F
    packed = ((red << 11) | (green << 5) | blue).astype("<u2")
    return packed.tobytes()


# ────────────────────────────── block plumbing ─────────────────────────────

@dataclass(frozen=True, slots=True)
class _Block:
    """One block of the template: its name, where it starts and its bytes."""

    name: str
    payload: bytes


def _u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 4], "little")


def _patch_u32(data: bytearray, offset: int, value: int) -> None:
    data[offset:offset + 4] = int(value).to_bytes(4, "little")


def _patch_f32(data: bytearray, offset: int, value: float) -> None:
    data[offset:offset + 4] = np.float32(value).tobytes()


def mark_size(mark_version: int) -> int:
    """Bytes taken by the file mark: signature, version, count and the addresses."""
    return MARK_SIZE + 8 + 4 * ADDRESS_COUNT[mark_version]


def _template_blocks(template: Px6sFile) -> list[_Block]:
    """Every addressed block of the template, in FILE ORDER, plus the layer image.

    A block ends where the next one starts: the length fields of `EXTRA` and `MODEL` lie
    in the real files, so they are not used here.
    """
    data = template._data
    addressed = sorted(((name, address) for name, address in template.mark.addresses.items()
                        if address), key=lambda item: item[1])
    blocks: list[_Block] = []
    for index, (name, address) in enumerate(addressed):
        if name == "layer_image":
            length = template.layers[0].data_length
        elif index + 1 < len(addressed):
            length = addressed[index + 1][1] - address
        else:
            length = len(data) - address       # the last block ends with the file
        blocks.append(_Block(name=name, payload=data[address:address + length]))
    return blocks


def _patched_blocks(template: Px6sFile, blocks: list[_Block], layer: bytes,
                    picture_of: np.ndarray, exposure_s: float) -> list[_Block]:
    """The template's blocks with ONLY the described fields replaced."""
    patched: list[_Block] = []
    for block in blocks:
        payload = bytearray(block.payload)
        if block.name == "header":
            _patch_f32(payload, 24, exposure_s)      # ExposureTime
            _patch_f32(payload, 32, exposure_s)      # BottomExposureTime
            _patch_f32(payload, 36, 1.0)             # BottomLayersCount
        elif block.name == "layer_definition":
            _patch_u32(payload, 20 + 4, len(layer))                   # record DataLength
            _patch_f32(payload, 20 + 16, exposure_s)                  # record ExposureTime
            _patch_u32(payload, 20 + 24, int((picture_of > 0).sum()))  # NonZeroPixelCount
        elif block.name in ("preview", "preview2"):
            width = _u32(payload, 16)
            height = _u32(payload, 24)
            picture = render_preview_rgb565(picture_of, width, height)
            payload[28:28 + len(picture)] = picture
            _patch_u32(payload, 12, 28 + len(picture))                # TableLength
        elif block.name == "layer_image":
            payload = bytearray(layer)
        patched.append(_Block(name=block.name, payload=bytes(payload)))
    return patched


def write_from_template(template: Px6sFile, mask: np.ndarray, exposure_s: float,
                        *, mirror_x: bool = False) -> Written:
    """Build the new file's bytes from the template and the mask."""
    if template.mark.version != SUPPORTED_VERSION:
        raise Refusal(f"template version {template.mark.version} is not supported by the "
                      f"writer: it writes version {SUPPORTED_VERSION} only")
    if template.layer_count != 1:
        raise Refusal(f"the template has {template.layer_count} layer(s); the writer "
                      f"builds a ONE-layer file and will not guess which layer to keep")
    if not exposure_s > 0:
        raise Refusal(f"the exposure must be positive, got {exposure_s!r} s")

    width, height = template.header.resolution_x, template.header.resolution_y
    if mask.ndim != 2 or mask.shape != (height, width):
        given = "x".join(str(size) for size in mask.shape) if mask.ndim == 2 else "?"
        raise Refusal(f"the mask is {given} px, the template is {width} x {height} px")
    distinct = np.unique(mask)
    if not np.isin(distinct, (0, WHITE)).all():
        raise Refusal(f"the mask holds values other than 0 and 255: "
                      f"{', '.join(str(int(value)) for value in distinct[:8])} — only a "
                      f"black-and-white mask is written (grey is a separate decision)")

    layer_mask = np.fliplr(mask) if mirror_x else mask
    layer = encode_pw0(layer_mask)
    blocks = _patched_blocks(template, _template_blocks(template), layer, layer_mask,
                             exposure_s)

    # Lay the blocks out again in the template's order: addresses and the lengths that
    # depend on them are RECOMPUTED, so a layer of another length cannot leave a stale
    # pointer behind.
    offsets: dict[str, int] = {}
    position = mark_size(template.mark.version)
    for block in blocks:
        offsets[block.name] = position
        position += len(block.payload)

    mark = bytearray(template._data[:mark_size(template.mark.version)])
    address_base = MARK_SIZE + 8
    for index, name in enumerate(ADDRESS_FIELDS[:ADDRESS_COUNT[template.mark.version]]):
        _patch_u32(mark, address_base + index * 4, offsets.get(name, 0))

    body = bytearray()
    for block in blocks:
        payload = bytearray(block.payload)
        if block.name == "layer_definition":
            _patch_u32(payload, 20, offsets["layer_image"])   # the record's DataAddress
        body += payload

    white = int((layer_mask > 0).sum())
    pixel_mm = template.header.pixel_size_um / 1000.0
    previews = [block.name for block in blocks if block.name in ("preview", "preview2")]
    report = [
        f"template: {template.path}",
        f"machine: {template.machine.name if template.machine else 'not in the file'}",
        f"resolution: {width} x {height} px; pixel {template.header.pixel_size_um:.2f} um",
        f"exposure: normal {exposure_s:.3f} s, bottom {exposure_s:.3f} s, bottom layers 1, "
        f"layers 1",
        "light pwm: not stored in px6s v517 (the printer profile says LightPWM_255; the "
        "file has no brightness field)",
        f"mirror: {'on (the mask is reflected along X before encoding)' if mirror_x else 'off'}",
        f"layer data: {template.layers[0].data_length} bytes -> {len(layer)} bytes",
        f"white: {white} px = {white * pixel_mm * pixel_mm:.3f} mm2 "
        f"(one pixel {template.header.pixel_size_um:.2f} um square)",
        *(_preview_line(block) for block in blocks if block.name == "preview"),
        ("preview2: updated" if "preview2" in previews
         else "preview2: absent in this template (address 0) — nothing to update"),
    ]
    return Written(data=bytes(mark) + bytes(body), report=tuple(report))


def _preview_line(block: _Block) -> str:
    width = _u32(block.payload, 16)
    height = _u32(block.payload, 24)
    return f"preview: {width} x {height} px RGB565 updated"


def write_file(template_path: str | Path, mask: np.ndarray, output: str | Path,
               exposure_s: float, *, mirror_x: bool = False) -> tuple[Path, tuple[str, ...]]:
    """Read the template, build the new bytes, write them; return the path and the report."""
    template = read_file(template_path)
    written = write_from_template(template, mask, exposure_s, mirror_x=mirror_x)
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(written.data)
    return target, written.report


__all__ = ["Written", "encode_pw0", "mark_size", "render_preview_rgb565", "write_file",
           "write_from_template"]
