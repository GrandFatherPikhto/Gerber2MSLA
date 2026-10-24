# Gerber2MSLA

Expose photoresist boards on an MSLA printer (Anycubic Photon Mono X 6Ks): a mask in
exact screen pixels becomes a printer file, and later a board comes from Gerber.

The LCD lights WHOLE pixels, so this tool works in pixels of the screen — 5760 x 3600 on
this printer, 34 um per pixel according to the UVtools/PrusaSlicer profile (a profile,
not a verified spec sheet). The printer file is a one-layer `.px6s`; nothing here talks
to the printer, and no laser is involved.

State: pixel-bound test masks (`bars`, `grid`) work as `gerber2msla masks …`; the
converter (PNG to `.px6s`) is the next step of the plan
`techdocs/handoff/deepseek/plan_2026_10_23_png2px6s.md`.

## Test masks

```
gerber2msla masks bars   --screen-px WxH --pixel-um PXxPY -o out/bars.png \
                         [--widths-mm 0.2,0.15,0.1 | --widths-px 6,5,4,3,2,1] \
                         [--lines 5] [--at X,Y] [--mirror] [--invert] [--marker|--no-marker]
gerber2msla masks grid   --screen-px WxH --pixel-um PXxPY -o out/grid.png \
                         [--width-mm 50 --height-mm 40] [--line-mm 0.2 | --line-px 6] \
                         [--gap-mm 0.15 | --gap-px 4] [--direction both|x|y] …
gerber2msla masks square --screen-px WxH --pixel-um PXxPY -o out/square.png \
                         [--side-mm 100 | --side-px N] [--line-mm 0.2 | --line-px 6] …
gerber2msla masks plate  --screen-px WxH --pixel-um PXxPY -o out/plate.png \
                         [--plate-mm 70x78] [--margin-mm 2] [--grid-mm 30x30] \
                         [--widths-mm … | --widths-px …] [--lines 5] …
```

`--screen-px` and `--pixel-um` are **mandatory and have no defaults**: an invented number is
worse than a refusal. For the Anycubic Photon Mono X 6Ks the printer profile in UVtools (and
PrusaSlicer's `Anycubic Photon Mono X 6Ks.ini`) says 195.84 x 122.4 mm over 5760 x 3600 px,
i.e. **34 um per pixel** — that is a PROFILE, not a verified spec sheet and not a
measurement. The real pixel is measured with the `square` (see below), one axis at a time.

```sh
.venv/bin/gerber2msla masks bars --screen-px 5760x3600 --pixel-um 34x34 \
    -o out/bars.png --widths-px 6,5,4,3,2,1
.venv/bin/gerber2msla masks grid --screen-px 5760x3600 --pixel-um 34x34 \
    -o out/grid.png --width-mm 50 --height-mm 40 --line-px 6 --gap-px 4
.venv/bin/gerber2msla masks square --screen-px 5760x3600 --pixel-um 34x34 \
    -o out/square.png --side-mm 100 --line-mm 0.2
.venv/bin/gerber2msla masks plate --screen-px 5760x3600 --pixel-um 34x34 \
    -o out/plate.png --plate-mm 70x78
```

* The pixel may be not square — two sizes, one per axis.
* `bars` — groups of lines with the gap equal to the line width: a horizontal block (the Y
  resolution) and a vertical block (the X resolution), each square so the two axes compare;
* `grid` — a rectangle filled with lines: the first line is flush with the near edge, a line
  is drawn only whole, the leftover at the far edge is a gap;
* `square` — a closed contour; the side (100 mm by default — the laser's 150 mm does not fit
  this screen) and the line are whole pixels of their OWN axis. The report prints
  `pixel_um_x = measured_x_mm / n_x * 1000` (and Y) with this order's numbers: measure both
  sides with calipers, OUTER edge to outer edge, and type the result into `--pixel-um`. The
  diagonals only check the measurement (`d1 = d2` expected) — the LCD grid has no skew,
  only a scale;
* `plate` — every test on ONE exposure: the square frame (plate minus the margin), one
  letter F, `bars` on the left half and `grid` on the right half. The layout is fixed
  because a mask has no captions. On a plate the grid default is 30 x 30 mm — the
  single-command 50 x 40 does not fit half a plate, and the report says so with numbers.
  Figures that overlap or leave the frame are refused, never silently shrunk;
* every width becomes `n = round(width / pitch)` pixels of its OWN axis, and the report
  prints the requested width beside the ACTUAL one: a 0.100 mm line on a 34 um pixel is
  3 px = 0.102 mm. That actual number is the one to expect on the plate.
* `--widths-px 6,5,4,3,2,1` is the list to start with on this screen: six DIFFERENT
  steps of 34 um. The millimetre list 0.2/0.15/0.1/0.08/0.06/0.05 gives 6, 4, 3, 2, 2, 1 —
  two identical groups, and the tool announces that.
* a width may be asked in millimetres or in WHOLE PIXELS; the two forms exclude each
  other. A millimetre request more than 10 % off is announced: «0.050 mm along Y is
  drawn as 34.0 um (-32 %)».
* every figure carries the letter **F** in its top-left corner and the pattern starts to
  its right; the F is asymmetric in both axes, so a mirrored exposure (the stem on the
  right) or an upside-down one (the arms at the bottom) is visible on the plate.
  `--no-marker` turns it off.
* white is an exposed pixel: the LINES are white by default (negative resist),
  `--invert` swaps that, and `--mirror` reflects the finished picture along X.
* the report — screen, pixel, widths requested and actual, mirror, polarity — is also
  written into the PNG text chunk `msla_tests`, so the file remembers what it is.

## A plate from a config

The built-in plate is one layout. Your own plate is a **TOML** file: what lies where, in
millimetres from the plate's own top-left corner — and which printer file draws it, and
where the results go.

```sh
# the whole job is the file: no -o, no --template, no screen (they are refused by name)
.venv/bin/gerber2msla masks plate --config examples/plate_70x80_25s.toml
```

```toml
[output]                         # everything about the printer (plan Б0)
template = "../tests/data/01_test02.px6s"   # the screen and the header pixel come from HERE
px6s = "../out/plate_70x80_25s.px6s"        # optional
png = "../out/plate_70x80_25s.png"          # optional; at least one of px6s / png
# pixel_um = [34.0, 34.0]        # optional MEASUREMENT: the geometry moves, the header does not

[plate]
width_mm = 70
height_mm = 78
exposure_s = 25                  # for a .px6s; both times come from here
# exposure_s = [7, 10, 15, 20, 25, 30, 35, 45]   # a LIST: one file per time (a series)
# rotate = 90                    # optional: turn the finished plate counter-clockwise

[marker]                         # optional: no [marker] means no letter F
at_mm = [3.196, 3.196]

[[figure]]
kind = "square"                  # square | bars | patches | grid | text
at_mm = [2, 2]
size_mm = [66, 74]
line_mm = 0.2                    # or line_px = 6

[[figure]]
kind = "patches"                 # one 10 mm patch per width, a row per width
at_mm = [5, 5]
patch_mm = 10
patch_gap_mm = 1.5
widths_mm = { from = 0.05, to = 0.20, step = 0.05 }   # inclusive
gap = "same"                     # gap = the stripe width; or gap_mm / gap_px

[[figure]]
kind = "text"                    # a label in the plate's own 5 x 7 font
at_mm = [29, 60]
text = "{exposure_s}s"           # the ONE substitution: the plate's own time (20, 7, 2.5)
stroke_px = 6                    # one font dot = 6 x 6 SCREEN pixels
```

* **The config is strict in both directions.** There are no defaults: a key that is not
  in the table of its kind, and a key that is missing, are both refusals that name the
  key and list the keys that belong there. An unknown figure kind, a wrong type
  (`true` is not a number, `6.0` is not a pixel count), a table that is not a table — all
  refused. A TOML syntax error is refused with the LINE NUMBER of the file. A typo never
  becomes a default.
* **One source of truth.** Next to `--config`, the built-in layout flags (`--plate-mm`,
  `--at`, `--widths-*`, `--lines`, `--grid-mm`, `--margin-mm`, `--square-line-*`,
  `--line-*`, `--gap-*`, `--direction`), `--exposure-s`, `-o`, `--template`,
  `--screen-px` and `--pixel-um` are refused by name: the config answers those questions.
  The plate is centred on the screen; a figure that leaves the plate or overlaps another
  is refused with both names, never shrunk.
* **`[output]` is the printer and the output, and nothing else.** Its paths count from the
  config FILE, not from your shell's directory (the folder is created). `template` is
  always required — even for a PNG-only config, because the screen is the printer's, not a
  guess. A `.px6s` takes its time from `[plate] exposure_s`: a config that writes one
  without it is refused with the key's name.
* **One picture, two files.** A `png` and a `.px6s` of one call come out of ONE `compose`,
  so they cannot differ by a pixel. Overwriting is allowed and the report says
  `overwrote <path>`: a config is a recipe, and the file is made again from it.
* **`patches`** rows: the left square of a row holds stripes along X (the Y resolution
  shows), the right one stripes along Y (the X resolution). A stripe is drawn whole and
  the first is flush with the near edge — the leftover at the far edge is a gap, because
  a stretched stripe would measure a width nobody asked for.
* **A LIST of times is a series** (25.10: the operator used to copy one config per time and
  change a single number): `exposure_s = [7, 10, 15, 20, 25, 30, 35, 45]` writes one file per
  time, in the order of the list — its own label (`{exposure_s}`), its own name, its own
  line in the report. Every `[output]` path (`px6s` AND `png`) must carry `{exposure_s}`,
  otherwise the config is refused: the files would overwrite each other. A time given twice
  is refused too. One command does the whole series:

  ```sh
  .venv/bin/gerber2msla masks plate --config examples/plate_70x80_series.toml
  ```

  The 20, 25 and 30 s files of that series are byte for byte the files of the single
  configs — a series changes nothing but the names.
* **`text` is the utility's OWN 5 x 7 font** ([`font5x7.py`](gerber2msla/font5x7.py)),
  not a TTF: a vector font is rasterised by the platform, comes out grey and slightly
  different machine to machine, and the plates of one series are compared with a
  magnifier. One font dot is `stroke_px` x `stroke_px` SCREEN pixels — a square in
  PIXELS, so a non-square pixel does not lean the letters. The set is `0-9`, `A-Z`,
  `a-z`, space and `. , - _ : / ( ) + = %`; anything else (Cyrillic, for one) is a
  refusal that names the character and its place in the line.
* **`{exposure_s}` is the ONE substitution a label may hold**, and it is filled with
  `[plate] exposure_s` as written — `20`, `7`, `2.5`, no trailing zeros. A copied config
  with another time therefore draws another label (25.10: the operator changed the time to
  7 s and the plate kept saying "25s"). Any other brace — a wrong name, a second
  substitution, an unpaired brace — is refused with the character number in `text`.
* **`[plate] rotate = 0 | 90 | 180 | 270`** turns the FINISHED plate — every figure and the
  marker, so the F lies on its side — counter-clockwise, and centres the turned plate
  again: 70 x 80 mm at 90 degrees is 2353 x 2059 px at 1703, 770 px. A quarter turn on a
  non-square pixel is refused: the axes would swap their meaning.
  `examples/plate_70x80_20s_rot90.toml` reproduces `out/plate_70x80_20s_rot90.px6s`, the
  file that was turned by hand, BYTE FOR BYTE.
* **The config travels with the mask.** The whole file, byte for byte, goes into the PNG
  chunk `plate_config` (iTXt, UTF-8 — your comments are yours, and Russian is fine); the
  report prints it too. The report chunk `msla_tests` is unchanged.
* `examples/plate_70x78.toml` is the built-in plate written as a config — the ORACLE:
  its PNG is pixel-for-pixel the PNG without `--config`.
  `examples/plate_70x78_patches.toml` is the same plate with 10 mm patches.

## A board from a config

```sh
.venv/bin/gerber2msla board --config examples/board_heatingtable.toml
```

```toml
[output]                                    # the same table as the plate's
template = "../tests/data/01_test02.px6s"
dir = "../out/HeatingTable"                 # <side>.px6s, <side>_align.px6s, board_report.txt
png = true                                  # required: also <side>.png next to every file

[board]
outline = "gerber/...-Edge_Cuts.gbr"        # required: ONE frame for every file of the board
drills = ["gerber/...-PTH.drl", "gerber/...-NPTH.drl"]

[[side]]
name = "top"                                # -> top.px6s, top_align.px6s
copper = "gerber/...-F_Cu.gbr"
mirror = true                               # measured 25.10: an unmirrored file reads mirrored on the copper
holes = false                               # false = tenting; true = holes poured in the working mask too
exposure_s = 25
align_s = 1                                 # optional: <name>_align.px6s, WITH the holes, 1 s
```

* **One frame for the whole board.** `outline` is required here — on the single-file command
  line it is only a warning, but two sides of one board cannot be lined up without a shared
  frame. The report prints that frame once; every file carries it in its own chunk.
* **The mirror is the side's own, and it is a MEASURED fact** (25.10, two plates): a file
  written without `--mirror` reads mirrored on the copper, so `top` (F_Cu) goes out with
  `mirror = true`, while `bottom` (B_Cu, which KiCad draws as seen from the top) goes out
  with `mirror = false`. The utility still never mirrors on its own: the flag says it, and
  the report states which one was used.
* **The alignment file always has the holes** and its own `align_s`: it is the file the two
  sides are aligned by. `align_s` without `drills` is refused — there is nothing to align by.
* **A side is a file name**: `name` is `[a-z0-9_-]+` and unique, and it becomes `<name>.px6s`.
* **Strict like the plate**: an unknown key, a missing key, a wrong type, a syntax error with
  the LINE NUMBER. Next to `--config` every flag is refused by name — including the copper
  argument and `-o`.
* **Paths count from the config file**, overwriting is allowed (`overwrote <path>`), and
  `board_report.txt` next to the files keeps the whole report and the config text.
* `examples/board_heatingtable.toml` is the real HeatingTable board with a `gerber/`
  placeholder: copy it next to the KiCad project's `gerber/` folder, or fix the paths.
  `diagnostics/probe_board_config_2026_10_24.py` runs it on the real board through a
  temporary copy and leaves `out/HeatingTable/` for UVtools.

## Write a printer file

```sh
.venv/bin/gerber2msla write out/plate.png --template real.px6s \
    -o out/plate_25s.px6s --exposure-s 25 [--mirror-x]
```

* the **template** is a real one-layer `px6s` of this printer (version 517), made by the
  slicer: everything that belongs to the machine — lift heights, speeds, the `MACHINE`,
  `EXTRA`, `SOFTWARE` and `MODEL` blocks — is copied byte for byte. Only the layer, the
  two exposure times, the layer count and the previews are written;
* the mask must be exactly the template's resolution, mode `L`, values 0/255; anything
  else is refused with the numbers found;
* **the bottom-layer trap:** in a one-layer file layer 0 IS the bottom layer, and the
  printer exposes it with the bottom time. Both `ExposureTime` and `BottomExposureTime`
  are set to `--exposure-s`, the bottom layer count to 1 — the report says what was
  written;
* `--mirror-x` reflects the mask before encoding and is OFF by default: the file carries
  no mirror flag, so the decision is yours and is checked once by the F marker on the
  plate. The report says whether it was on;
* `LightPWM` is not stored in `px6s` v517 at all; the report says so instead of inventing
  a brightness;
* the report also prints the white pixel count and its area in mm², and the path written.

Getting the file to the printer: open it in **UVtools** first — the layer must equal your
mask and the times must be yours — and only then copy it to the printer. Nothing in this
tool talks to the printer.

## Read a printer file back

```sh
.venv/bin/gerber2msla dump out/plate_25s.px6s [-o out/layer.png]
```

* prints what the FILE says, with no interpretation: version and block count, machine name
  and layer format, resolution and pixel size, both exposure times, bottom layers and layer
  count, lift height and speeds, and the address of every block; each layer gets its own
  line — address, length, lift, exposure, non-zero pixels;
* `-o` saves layer 0 as an 8-bit grey PNG — the very picture `write` encoded, so
  `masks plate` → `write` → `dump -o` → PNG is a check that needs no printer;
* a file that is not a `px6s` is refused in one line with code 2, and no PNG is written;
* `dump` adds no byte-level knowledge: `gerber2msla/px6s.py` had already parsed the blocks,
  and the format is written down in [docs/format_px6s.md](docs/format_px6s.md). The layer's
  own exposure time and the header's bottom time are both printed, so the one-layer trap
  above can be seen in the file itself.

## Dose series

```sh
.venv/bin/gerber2msla dose out/plate.png --template real.px6s -o out/dose \
    --exposure-s 15,20,25,30,35
.venv/bin/gerber2msla dose out/plate.png --template real.px6s -o out/dose --series 15 35 5
```

* a layer has ONE exposure time for the whole picture, so the ladder is a set of FILES: the
  same mask, one file per time. The name carries the time — `out/dose_25.0s.px6s`;
* two forms, never both: an explicit list, or a geometric series
  `ratio = (stop/start)**(1/(count-1))` — dose acts by multiplication, so equal steps in
  TIME are not equal steps in dose (the same arithmetic as Gerber2LDI's dose strip);
* every file goes through the same writer as `write`: the machine blocks stay byte for byte,
  and both times in each file are that file's own time (layer 0 IS the bottom layer);
* the report is the table «file → normal and bottom time», read back FROM the files;
* a repeated time, a flat or falling series, or two times that round to one file name are
  refused: one silently lost level is worse than no series at all.

## Install (development)

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Tests

```sh
.venv/bin/python -m pytest -q -rsf -p no:cacheprovider -n auto
.venv/bin/python -m pytest -q -rsf -p no:cacheprovider -n auto --reverse
```

Russian version: [README_ru.md](README_ru.md).
