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

```sh
.venv/bin/gerber2msla masks bars --screen-px 5760x3600 --pixel-um 34x34 \
    -o out/bars.png --widths-px 6,5,4,3,2,1
.venv/bin/gerber2msla masks grid --screen-px 5760x3600 --pixel-um 34x34 \
    -o out/grid.png --width-mm 50 --height-mm 40 --line-px 6 --gap-px 4
```

* `--screen-px` and `--pixel-um` are **mandatory**: an invented number is worse than a
  refusal. The pixel may be not square — two sizes, one per axis.
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

Getting the PNG to the printer (Claude's route, not verified by Denis yet): open any
one-layer file of that printer in **UVtools**, replace the layer with the imported PNG,
set the exposure time and save. The mask fixes the geometry; the exposure time is the dose.

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
