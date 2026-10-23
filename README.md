# Gerber2MSLA

Expose photoresist boards on an MSLA printer (Anycubic Photon Mono X 6Ks): a mask in
exact screen pixels becomes a printer file, and later a board comes from Gerber.

The LCD lights WHOLE pixels, so this tool works in pixels of the screen — 5760 x 3600 on
this printer, 34 um per pixel according to the UVtools/PrusaSlicer profile (a profile,
not a verified spec sheet). The printer file is a one-layer `.px6s`; nothing here talks
to the printer, and no laser is involved.

State: the package is a skeleton plus the pixel-bound test masks. The converter
(PNG to `.px6s`) is the next step of the plan `techdocs/handoff/deepseek/plan_2026_10_23_png2px6s.md`.

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
