"""The printer-file command line: `write` (and, from П3, `dump`).

The `write` cell moved here from `tests/test_cli.py` in the П2 fix, unchanged: a module's
cells live in the file of that module (`gerber2msla/cli_px6s.py`). What is checked here is
the COMMAND LINE only — the format itself is held by `tests/test_px6s_write.py` and
`tests/test_px6s.py`.
"""
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from gerber2msla.cli import main


def test_write_refuses_a_mask_that_is_not_mode_l(tmp_path, capsys):
    """A colour PNG is not a mask: one line, code 2, and no file left behind."""
    template = Path(__file__).resolve().parents[1] / "tests" / "data" / "01_test02.px6s"
    if not template.is_file():
        pytest.skip("no tests/data/01_test02.px6s: the template is copied in with the writer")
    mask = tmp_path / "rgb.png"
    Image.fromarray(np.zeros((8, 8, 3), dtype=np.uint8), mode="RGB").save(mask)
    target = tmp_path / "out.px6s"
    assert main(["write", str(mask), "--template", str(template), "-o", str(target),
                 "--exposure-s", "25"]) == 2
    err = capsys.readouterr().err
    assert "mode L" in err and "RGB" in err
    assert not target.exists()
