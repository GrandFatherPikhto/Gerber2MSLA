# gerber2msla/config_strict.py
"""The strict reading of a TOML config: one table of keys per level, refusals by name.

TWO configs use these helpers — the plate (`plate_config.py`, plan К1) and the board
(`board_config.py`, plan Б1) — and that is the whole reason this module exists: a second
copy of "an unknown key is a refusal" is where the two configs would start to disagree
about what "strict" means. The functions were MOVED here from `plate_config.py` without a
rewording, so the plate's refusals are the same strings as before; the only wording that
had to become general is `_required`, which used to say "every key a FIGURE needs" and now
says "every key IT needs" — a board has sides, not figures.

The leading underscore stays on purpose, exactly as in `masks.py`: it means "not for the
operator", not "not for the other half of the tool". The public surface of this module is
nothing; what it gives is the set of refusals.

THE RULES, once, for both configs:

  * every level is checked against an explicit tuple of keys — the ROOT, each table,
    each figure/side, and the inline range tables. `_keys` refuses an unknown key BY
    NAME and lists the keys that belong there;
  * a key that is missing is refused with its own name and the words "no defaults":
    these configs do not fill anything in, because a silent default is exactly how a
    typo becomes a file nobody meant to expose;
  * a value of the wrong type is refused with the key and what was found: `bool` is
    never a number (``True`` is an ``int`` in Python, so the type is compared by
    identity), a pixel count is never a float, a pair is exactly two finite numbers;
  * a TOML syntax error is refused with the LINE of the file (`TOMLDecodeError.lineno`
    on 3.14, the message text before it), never with a traceback;
  * every refusal is ONE ASCII English line: it travels to stderr of the command and to
    the report of the exposure.
"""
from __future__ import annotations

import math
import re
import tomllib
from pathlib import Path

from .masks import Refusal


# ───────────────────────────── refusal wording ─────────────────────────────

def _what(value: object) -> str:
    """What was found, in the operator's terms: a table, an array, the number 6.0..."""
    if isinstance(value, bool):
        return f"a boolean ({value!r})"
    if isinstance(value, (int, float)):
        return f"the number {value!r}"
    if isinstance(value, str):
        return f"a string ({value!r})"
    if isinstance(value, list):
        return f"an array of {len(value)} item(s)"
    if isinstance(value, dict):
        return "a table"
    return type(value).__name__


def _noun(count: int) -> str:
    return "key" if count == 1 else "keys"


def _table(value: object, where: str, source: str) -> dict:
    if type(value) is not dict:
        raise Refusal(f"{source}: {where} must be a table, got {_what(value)}")
    return value


def _keys(table: dict, allowed: tuple[str, ...], where: str, source: str) -> None:
    """Strictness, first half: a key that does not belong here is refused BY NAME."""
    unknown = sorted(set(table) - set(allowed))
    if unknown:
        listed = ", ".join(f"'{key}'" for key in unknown)
        raise Refusal(f"{source}: {where}: unknown {_noun(len(unknown))} {listed}; "
                      f"the known keys are {', '.join(allowed)}")


def _required(table: dict, key: str, where: str, source: str):
    """Strictness, second half: no key means no value — there are no defaults here."""
    if key not in table:
        raise Refusal(f"{source}: {where}: no '{key}': this config has no defaults, "
                      f"every key it needs must be in the file")
    return table[key]


def _number(value: object, key: str, where: str, source: str, *,
            positive: bool = True) -> float:
    """A millimetre-like number; ``int`` is fine (``width_mm = 70``), ``bool`` is not.

    ``True`` is an ``int`` in Python, so the type is compared by identity: a
    ``height_mm = true`` from the file is a refusal and never a plate 1 mm high.
    """
    if type(value) not in (int, float):
        raise Refusal(f"{source}: {where}: '{key}' must be a number, got {_what(value)}")
    number = float(value)
    if not math.isfinite(number):
        raise Refusal(f"{source}: {where}: '{key}' must be finite, got {value!r}")
    if positive and number <= 0.0:
        raise Refusal(f"{source}: {where}: '{key}' must be positive, got {value!r}")
    if not positive and number < 0.0:
        raise Refusal(f"{source}: {where}: '{key}' must not be negative, got {value!r}")
    return number


def _whole(value: object, key: str, where: str, source: str, *, minimum: int = 1) -> int:
    """A whole pixel count: ``6`` yes, ``6.0`` no — a count of pixels has no fraction."""
    if type(value) is not int:
        raise Refusal(f"{source}: {where}: '{key}' must be a whole number of pixels, "
                      f"got {_what(value)}")
    if value < minimum:
        raise Refusal(f"{source}: {where}: '{key}' must be at least {minimum}, got {value}")
    return value


def _pair(value: object, key: str, where: str, source: str, *,
          positive: bool = True) -> tuple[float, float]:
    """Two numbers: ``at_mm`` and ``size_mm``. Three is as wrong as one."""
    if type(value) is not list:
        raise Refusal(f"{source}: {where}: '{key}' must be an array of two numbers, "
                      f"got {_what(value)}")
    if len(value) != 2:
        raise Refusal(f"{source}: {where}: '{key}' must hold exactly two numbers, "
                      f"got {len(value)}")
    return (_number(value[0], f"{key}[0]", where, source, positive=positive),
            _number(value[1], f"{key}[1]", where, source, positive=positive))


def _flag(value: object, key: str, where: str, source: str) -> bool:
    """A TOML boolean: ``true``/``false``, not 1/0 and not "yes" (YAML's trap, not ours)."""
    if type(value) is not bool:
        raise Refusal(f"{source}: {where}: '{key}' must be true or false, "
                      f"got {_what(value)}")
    return value


def _text(value: object, key: str, where: str, source: str) -> str:
    """A free string — a path or a name. `_string` is for a CLOSED set of words."""
    if type(value) is not str:
        raise Refusal(f"{source}: {where}: '{key}' must be a string, got {_what(value)}")
    return value


def _string(value: object, key: str, where: str, source: str,
            choices: tuple[str, ...]) -> str:
    if type(value) is not str:
        raise Refusal(f"{source}: {where}: '{key}' must be a string, got {_what(value)}")
    if value not in choices:
        raise Refusal(f"{source}: {where}: '{key}' must be one of "
                      f"{', '.join(repr(choice) for choice in choices)}, got {value!r}")
    return value


# ──────────────────────────── reading the file ─────────────────────────────

def _syntax_line(exc: tomllib.TOMLDecodeError) -> int:
    """The line the TOML parser stopped on: an attribute on 3.14, the text before it.

    Both paths are kept on purpose: the attribute is the honest one, the regex is what
    the older minor versions have, and the project's floor is 3.11 — a refusal with the
    line number must not depend on which machine's Python read the file.
    """
    line = getattr(exc, "lineno", None)
    if isinstance(line, int) and line > 0:
        return line
    found = re.search(r"line (\d+)", str(exc))
    return int(found.group(1)) if found else 0


def _loads(text: str, source: str) -> dict:
    """TOML text → a table; a syntax error is one line that names the LINE."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        message = getattr(exc, "msg", None) or str(exc)
        line = _syntax_line(exc)
        where = f"line {line}" if line else "a TOML syntax error"
        raise Refusal(f"{source}: {where}: {message}") from None
    return _table(data, "the whole file", source)


def _read_text(target: Path, what: str) -> str:
    """The file as UTF-8; missing file and foreign bytes are refusals, not tracebacks.

    ``what`` is the operator's name for the file ("the plate config", "the board
    config"), so the message reads as a sentence about HIS file, not about ours.
    """
    try:
        return target.read_text(encoding="utf-8")
    except OSError as exc:
        raise Refusal(f"cannot read {what} {target}: {exc}") from None
    except UnicodeDecodeError as exc:
        raise Refusal(f"{what} {target} is not UTF-8: {exc}") from None


__all__: list[str] = []
"""Deliberately empty: this module is the other half of the tool, not its interface."""
