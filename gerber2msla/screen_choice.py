# gerber2msla/screen_choice.py
"""Where the screen and the pixel come from: the printer's template, or the two flags.

Decision of 24.10 (plan Г2): the resolution is ALWAYS the printer's, so with
``--template`` it comes from the file and ``--screen-px`` is refused — "the template
fixes the screen". The pixel is two different things and they are kept apart:

  * the pixel STORED IN THE FILE HEADER is a machine field: it is copied from the
    template byte for byte and never changes;
  * ``--pixel-um`` is a MEASUREMENT of how many screen pixels a millimetre takes. It
    changes the geometry only, and it may be not square (34 x 30 is exactly what the
    square test of П5а exists to measure).

So the report line says which pixel was used and what the header keeps:
``pixel: 34.00 x 30.00 um (measured, --pixel-um; the file header keeps 34.00)``. Without
``--template`` the pixel and the screen are mandatory, as in ``masks``, and the PNG
carries them (it is the only thing that can).

ONE function for every command that draws on the screen: `board` (Г2) and
`masks plate --config` (К2) ask the same question, and a second copy of this answer is
where two commands start to disagree about the same template.
"""
from __future__ import annotations

from .masks import Refusal, Screen


def screen_for(args, printer) -> tuple[Screen, str]:
    """The screen to draw on, and the line that says where its pixel came from."""
    if printer is not None:
        header = printer.header
        if args.screen_px is not None:
            raise Refusal("the template fixes the screen: --screen-px cannot be given with "
                          "--template")
        if args.pixel_um is None:
            pixel_x_um = pixel_y_um = header.pixel_size_um
            line = f"pixel: {pixel_x_um:.2f} x {pixel_y_um:.2f} um (template header)"
        else:
            pixel_x_um, pixel_y_um = args.pixel_um
            line = (f"pixel: {pixel_x_um:.2f} x {pixel_y_um:.2f} um (measured, --pixel-um; "
                    f"the file header keeps {header.pixel_size_um:.2f})")
        screen = Screen(width_px=header.resolution_x, height_px=header.resolution_y,
                        pixel_x_um=pixel_x_um, pixel_y_um=pixel_y_um)
        return screen, line

    if args.screen_px is None or args.pixel_um is None:
        raise Refusal("without --template the screen and the pixel are mandatory: "
                      "--screen-px WxH and --pixel-um PXxPY")
    pixel_x_um, pixel_y_um = args.pixel_um
    width_px, height_px = args.screen_px
    screen = Screen(width_px=width_px, height_px=height_px,
                    pixel_x_um=pixel_x_um, pixel_y_um=pixel_y_um)
    return screen, (f"pixel: {pixel_x_um:.2f} x {pixel_y_um:.2f} um (measured, --pixel-um; "
                    f"no template, so the mask carries it)")


__all__ = ["screen_for"]
