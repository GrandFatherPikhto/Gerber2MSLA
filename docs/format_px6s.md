# The Anycubic `.px6s` format, version 517 — as this project reads it

Scope: one printer, one version — the Anycubic Photon Mono X 6Ks writes `px6s` version
517, and `gerber2msla/px6s.py` reads exactly that (versions 515, 516 and 518 differ only in
how many block addresses the file mark carries; the reader accepts them too).

Source of the description: **UVtools** (`github.com/sn4k3/UVtools`, `UVtools.Core`), commit
`86c7c3c`, file `UVtools.Core/FileFormats/AnycubicFile.cs`. It is read as a FORMAT only:
UVtools is AGPL, so no line of its C# is copied or translated here — every field below
names the class and method it was read from. The numbers were then checked by our own
reader against the two real files in `techdocs/px6s_examples/` (see §9).

Byte order is **little-endian** everywhere (the C# serializer writes binary
little-endian). All blocks are addressed absolutely from the start of the file: the file
mark carries their offsets, and offsets — not the length fields — are authoritative (§3).

## 1. File mark — `class FileMark`

| offset | size | type | field | source |
|---:|---:|---|---|---|
| 0 | 12 | ASCIIZ | mark `ANYCUBIC` (`SectionMarkFile`, `MarkSize = 12`) | `FileMark.Mark` |
| 12 | 4 | uint32 | version (`VERSION_517 = 0x0205 = 517`) | `FileMark.Version` |
| 16 | 4 | uint32 | number of tables (9 on these files) | `FileMark.NumberOfTables` |
| 20 | 4·N | uint32 | block addresses, in this order | `FileMark` field order |

Address order and when a version has it (fields with a version condition in `FileMark`):

| # | address field | v515 | v516 | v517 | v518 |
|---:|---|---|---|---|---|
| 0 | header | yes | yes | yes | yes |
| 1 | software | yes | yes | yes | yes |
| 2 | preview | yes | yes | yes | yes |
| 3 | layer image color table | yes | yes | yes | yes |
| 4 | layer definition | yes | yes | yes | yes |
| 5 | extra | yes | yes | yes | yes |
| 6 | machine | — | yes | yes | yes |
| 7 | layer image (first layer data) | yes | yes | yes | yes |
| 8 | model | — | — | yes | yes |
| 9 | sub-layer definition | — | — | — | yes |
| 10 | preview2 | — | — | — | yes |

So the mark is 20 + 4·N bytes: 56 for v517, 48 for v515, 52 for v516, 64 for v518. On
these files the first block starts exactly at the end of the mark: `HEADER @ 56`.

## 2. Named tables — `class AnycubicNamedTable`

Most blocks open with the same header:

| offset | size | type | field |
|---:|---:|---|---|
| 0 | 12 | ASCIIZ | table name (`HEADER`, `PREVIEW`, `LAYERDEF`, `EXTRA`, `MACHINE`, `MODEL`) |
| 12 | 4 | uint32 | table length |

The length is the block's payload — with the 16-byte table header excluded for
`HEADER`, `LAYERDEF` and `MODEL`, and included for `PREVIEW` and `MACHINE`
(`IncludeBaseTableLength` in `AnycubicNamedTable`). Optional trailing fields appear only
when the length is large enough; those conditions are quoted per block below.

`EXTRA`, `MODEL` and the software block in the real files show that this field is not
always written honestly (`EXTRA` says 24 while its payload is 56 bytes; `MODEL` says 0
while it occupies 48). The reader therefore takes every block's start from the file mark
and never walks the file by lengths.

## 3. Block order on a real file (01_test01.px6s)

| block | address | size in the file | note |
|---|---:|---:|---|
| file mark | 0 | 56 | 9 addresses |
| `HEADER` | 56 | 16 + 92 | length 92 (payload) |
| `PREVIEW` | 164 | 75292 | length incl. header and image |
| layer image color table | 75456 | 28 | no name, no length field |
| `LAYERDEF` | 75484 | 16 + 36 | payload = 4 + 1 × 32 |
| `EXTRA` | 75536 | 72 | length field lies (24); payload is 56 |
| `MACHINE` | 75608 | 156 | length incl. header |
| software (`AC-PC`) | 75764 | 164 | no table name; starts with the software name |
| `MODEL` | 75928 | 48 | length field says 0 |
| layer image data | 75976 | 2354656 / 11620 | the first layer's RLE; see §7 |

## 4. `HEADER` — `sealed class Header : AnycubicNamedTable`

Offsets are from the start of the table (the 16-byte name+length included). Field order
and types from `Header`; the conditions are its `SerializeWhen(TableLength, …)` rules.

| offset | size | type | field | meaning |
|---:|---:|---|---|---|
| 16 | 4 | float32 | `PixelSizeUm` | pixel size in micrometres (34.0 here) |
| 20 | 4 | float32 | `LayerHeight` | layer height in mm |
| 24 | 4 | float32 | `ExposureTime` | NORMAL exposure, seconds |
| 28 | 4 | float32 | `WaitTimeBeforeCure` | seconds |
| 32 | 4 | float32 | `BottomExposureTime` | BOTTOM exposure, seconds |
| 36 | 4 | float32 | `BottomLayersCount` | number of bottom layers — stored as a FLOAT |
| 40 | 4 | float32 | `LiftHeight` | mm |
| 44 | 4 | float32 | `LiftSpeed` | mm/s |
| 48 | 4 | float32 | `RetractSpeed` | mm/s |
| 52 | 4 | float32 | `VolumeMl` | ml |
| 56 | 4 | uint32 | `AntiAliasing` | anti-aliasing level (1 on these files) |
| 60 | 4 | uint32 | `ResolutionX` | screen pixels across (5760) |
| 64 | 4 | uint32 | `ResolutionY` | screen pixels down (3600) |
| 68 | 4 | float32 | `WeightG` | g |
| 72 | 4 | float32 | `Price` | — |
| 76 | 4 | 4 bytes | `PriceCurrencySymbol` | `$`, `¥` or `€` in UTF-8 |
| 80 | 4 | uint32 | `PerLayerSettings` | bool as uint32 |
| 84 | 4 | uint32 | `PrintTime` | seconds |
| 88 | 4 | uint32 | `TransitionLayerCount` | v516+, when length ≥ 84 |
| 92 | 4 | uint32 | `TransitionLayerType` | v516+, when length ≥ 84 |
| 96 | 4 | uint32 | `AdvancedMode` | when length ≥ 84 |
| 100 | 2 | uint16 | `Grey` | when length ≥ 86 |
| 102 | 2 | uint16 | `BlurLevel` | when length ≥ 88 |
| 104 | 4 | uint32 | `ResinType` | when length ≥ 92 |
| 108 | 4 | uint32 | `IntelligentMode` | v518, when length ≥ 96 |

Both real files: length 92, so the last field present is `ResinType`.

## 5. `PREVIEW` — `class Preview : AnycubicNamedTable`

| offset | size | type | field |
|---:|---:|---|---|
| 16 | 4 | uint32 | `ResolutionX` (224) |
| 20 | 4 | 4 bytes | mark, `x` + NUL |
| 24 | 4 | uint32 | `ResolutionY` (168) |
| 28 | w·h·2 | bytes | RGB565 pixels (`DataSize = ResolutionX * ResolutionY * 2`) |

The length field includes the table header and the image (`IncludeBaseTableLength`), so
75292 = 28 + 224·168·2. The preview is for the printer's display: our tool never builds
it from this, and never reads it as geometry.

## 6. Layer image color table and `LAYERDEF`

Layer image color table (`sealed class LayerImageColorTable`, **no** name and no length):

| offset | size | type | field |
|---:|---:|---|---|
| 0 | 4 | uint32 | `UseFullGreyscale` (0 here) |
| 4 | 4 | uint32 | `GreyMaxCount` (16) |
| 8 | 16 | 16 bytes | `Grey` levels: 15, 31, 47, … 239, 255 |
| 24 | 4 | uint32 | `Unknown` |

`LAYERDEF` (`sealed class LayerDefinition`, payload = 4 + count·32):

| offset | size | type | field |
|---:|---:|---|---|
| 16 | 4 | uint32 | `LayerCount` |
| 20 + i·32 | 32 | one record per layer | `LayerDef` (below) |

One `LayerDef` record (`sealed class LayerDef`, `ClassSize = 32`; **no checksum** in v517):

| offset in record | size | type | field | meaning |
|---:|---:|---|---|---|
| 0 | 4 | uint32 | `DataAddress` | absolute offset of this layer's RLE bytes |
| 4 | 4 | uint32 | `DataLength` | length of those bytes |
| 8 | 4 | float32 | `LiftHeight` | mm |
| 12 | 4 | float32 | `LiftSpeed` | mm/s |
| 16 | 4 | float32 | `ExposureTime` | THIS layer's exposure, seconds |
| 20 | 4 | float32 | `LayerHeight` | this layer's thickness, mm |
| 24 | 4 | uint32 | `NonZeroPixelCount` | the file's own lit-pixel count |
| 28 | 4 | uint32 | `Padding1` | zeros |

Layer 0 is the BOTTOM layer (`DecodeInternally`: `PositionZ` is the running sum of
`LayerHeight`, layer 0 first). On a one-layer file layer 0 is therefore the bottom layer,
and the printer exposes it with `BottomExposureTime` for the first `BottomLayersCount`
layers — see §8.

## 7. Layer data — the `pw0Img` run-length code

`MACHINE.LayerImageFormat` says `pw0Img` (UVtools: `RleFormat` is PW0 unless the file ends
in `.pws`). The layer image is `ResolutionX · ResolutionY` pixels, one byte each, filled
row by row (row 0 first), and each pixel's value is a grey level — but see §8 for what the
slicer actually writes.

The RLE (`LayerDef.Decode` → `AnycubicFile.DecodePW0`):

* one byte is a 4-bit code (high nibble) and a 4-bit repeat (low nibble);
* **code 0** — black (0): the repeat is TWO bytes, high nibble first and the next byte as
  its low 8 bits, so 0…4095 pixels. If the code byte is the last byte of the data, the run
  is taken to fill the rest of the image;
* **code 0xF** — white (255): same two-byte repeat;
* **any other code** — grey level `code << 4 | code`, i.e. 17, 34, … 238, repeated
  `repeat` times (1…15). A zero repeat is possible in the format (see UVtools'
  `EncodePW0` grouping) and paints nothing;
* the runs must fill the image exactly: a run that crosses the end is an error, and data
  that ends short is an error (`Image ran off the end` / `Image ended short`).
  `NonZeroPixelCount` is the file's own count of lit pixels and matches the decoded image.

The encoder in UVtools (`EncodePW0`) groups equal high nibbles of consecutive pixels, so a
decoded layer's values are always multiples of 17.

## 8. What the file says about the bottom layer, greys and the mirror

* **Bottom layers.** `Header.BottomExposureTime` and `Header.BottomLayersCount` (a float!)
  are the printer's bottom-layer settings; every layer also carries its own `ExposureTime`
  in `LAYERDEF`. On the two real files: 1 layer, normal exposure 25.000 s, bottom exposure
  25.000 s, bottom layer count 1 — so Denis' memory of "one layer, 25 s" is confirmed by
  the file itself, and layer 0 is exposed with the bottom time.
* **Greys.** The files were written with `AntiAliasing = 1`, and the decoded layers hold
  only 0 and 255 — no grey pixels on the line edges. The format can carry them (codes
  1…14, and `AntiAliasing` > 1 switches to bit planes); these files do not.
* **Mirror.** There is no mirror flag in `px6s`: `display_mirror_x = 1` belongs to the
  slicer's printer profile, not to this file. UVtools' Anycubic reader has no mirror step
  either; the layer is stored as the slicer rendered it for the printer's LCD. What that
  means for a mask we write ourselves is decided by the operator (`--mirror`) and checked
  once by the F marker on the plate — it is not readable from the file.
* **Checksums.** None in v517: one `LayerDef` is 32 bytes with no CRC field, and the layer
  data is exactly the RLE bytes. UVtools carries CRC-16 helpers for `Rle4` (`CRCRle4`,
  `CRCEncodedRle`) but does not write them into these files (the append in `EncodePW0` is
  commented out and the length fields account for no trailing bytes).

## 9. Verification against the real files (`techdocs/px6s_examples/`, read only)

Both files, by our reader (`diagnostics/probe_px6s_examples_2026_10_23.py`):

| what | 01_test01.px6s | 01_test02.px6s |
|---|---|---|
| file size | 2 430 632 bytes | 87 596 bytes |
| version / tables | 517 / 9 | 517 / 9 |
| header length | 92 | 92 |
| pixel size (header) | 34.00 µm | 34.00 µm |
| layer height | 0.0500 mm | 0.0500 mm |
| exposure / bottom exposure | 25.000 / 25.000 s | 25.000 / 25.000 s |
| bottom layers | 1 | 1 |
| resolution | 5760 × 3600 | 5760 × 3600 |
| anti-aliasing | 1 | 1 |
| layers | 1 | 1 |
| layer data | @ 75976, 2 354 656 bytes | @ 75976, 11 620 bytes |
| nonzero pixels (file / decoded) | 4 287 978 / 4 287 978 | 3 805 630 / 3 805 630 |
| decoded shape | 3600 × 5760 | 3600 × 5760 |
| values in the layer | 0 and 255 only | 0 and 255 only |
| lines | 200, across array axis 1 | 200, down array axis 0 |
| line width | median 7 px (7…8) | median 6 px (6…7) |
| line step | 15 px | 15 px |
| lit field | rows 322…3262 (2941 px), columns 1413…4346 (2934 px) | rows 334…3265 (2932 px), columns 1402…4342 (2941 px) |

Reading of the numbers:

* the step is 15 px, not the nominal 14.7: 0.5 mm / 34 µm = 14.706, and the slicer writes
  whole pixels. The width follows the same rule: 0.25 mm → 7.35 → 7 px (test01),
  0.22 mm → 6.47 → 6 px (test02). The 34 µm pixel is therefore consistent with the file;
* test01's lines run along array axis 0 (rows) and repeat across axis 1, test02's the
  other way round: array axis 1 (5760 wide) is the screen X, axis 0 (3600) is Y, row 0 is
  the top of the image;
* both fields are 2941 px ≈ 100 mm and sit near the centre: test01 leaves 1413 px on the
  left and 1413 on the right, 322 above and 337 below; test02 1402 left, 1417 right, 334
  above and 334 below — the slicer's placement, not a file origin rule;
* machine table: name `Anycubic Photon Mono X 6Ks`, layer image format `pw0Img`; its own
  resolution and pixel fields are absent at length 156, so the header's numbers are the
  ones to use.
