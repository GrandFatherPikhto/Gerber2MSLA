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
