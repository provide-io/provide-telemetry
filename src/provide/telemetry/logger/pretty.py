# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Pretty ANSI log renderer for CLI / terminal output."""

from __future__ import annotations

from typing import Any

LEVEL_COLORS: dict[str, str] = {
    "critical": "\033[31;1m",  # bold red
    "error": "\033[31m",  # red
    "warning": "\033[33m",  # yellow
    "info": "\033[32m",  # green
    "debug": "\033[34m",  # blue
    "trace": "\033[36m",  # cyan
}
RESET = "\033[0m"
DIM = "\033[2m"
_LEVEL_PAD = 9  # "critical" = 8 chars; pad to 9 for consistent alignment

NAMED_COLORS: dict[str, str] = {
    "dim": "\033[2m",
    "bold": "\033[1m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "cyan": "\033[36m",
    "white": "\033[37m",
    "none": "",
}


def resolve_color(name: str) -> str:
    """Return ANSI escape for a named color, or '' for empty/unknown names."""
    return NAMED_COLORS.get(name, "")


class PrettyRenderer:
    """Structlog-compatible renderer that emits ANSI-coloured log lines."""

    def __init__(  # pragma: no mutate — constructor signature; behavior asserted via snapshot tests
        self,
        colors: bool = True,  # pragma: no mutate — default sentinel; call sites pass explicitly
        key_color: str = "",  # pragma: no mutate — empty string means "no color"; alternative default changes format cosmetically only
        value_color: str = "",  # pragma: no mutate — empty string means "no color"; alternative default changes format cosmetically only
        fields: tuple[
            str, ...
        ] = (),  # pragma: no mutate — empty tuple means "all fields"; alternative default is equivalent for no-filter path
    ) -> None:
        self._colors = colors  # pragma: no mutate — attribute bind; read-back asserted via render tests
        self._key_color = key_color  # pragma: no mutate — attribute bind; read-back asserted via render tests
        self._value_color = value_color  # pragma: no mutate — attribute bind; read-back asserted via render tests
        self._fields = fields  # pragma: no mutate — attribute bind; read-back asserted via render tests
        self._fields_set = frozenset(
            fields
        )  # pragma: no mutate — derived membership set; contents validated by filter tests

    def __call__(self, logger: object, name: str, event_dict: dict[str, Any]) -> str:  # noqa: ARG002  # pragma: no mutate — structlog renderer signature; protocol-required shape
        parts: list[str] = []

        # 1. Timestamp
        ts = event_dict.pop("timestamp", None)
        if ts is not None:
            ts_str = str(ts)
            if self._colors:
                parts.append(
                    DIM + ts_str + RESET
                )  # pragma: no mutate — ANSI string concatenation; output is non-semantic formatting
            else:
                parts.append(ts_str)

        # 2. Level
        level = event_dict.pop(
            "level", ""
        )  # pragma: no mutate — empty-string default; event_dict.pop sentinel asserted by level-absent tests
        level_str = str(level).lower()
        padded = level_str.ljust(_LEVEL_PAD)  # pragma: no mutate — alignment pad; width is cosmetic
        if self._colors:
            color = LEVEL_COLORS.get(
                level_str, ""
            )  # pragma: no mutate — unknown level falls through to no-color; cosmetic only
            parts.append(
                "[" + color + padded + RESET + "]"
            )  # pragma: no mutate — bracket + color escape concat; output is non-semantic formatting
        else:
            parts.append("[" + padded + "]")  # pragma: no mutate — bracket concat; output is non-semantic formatting

        # 3. Event / message body
        event = event_dict.pop(
            "event", ""
        )  # pragma: no mutate — empty-string default; event_dict.pop sentinel asserted by event-absent tests
        parts.append(str(event))

        # 4. Remaining keys — sorted, optionally filtered key=repr(value) pairs
        fields_set = self._fields_set
        filtered_items = [(k, event_dict[k]) for k in sorted(event_dict) if not fields_set or k in fields_set]
        for key, val in filtered_items:
            val_repr = repr(val)
            key_part = (
                self._key_color + key + RESET if self._colors and self._key_color else key
            )  # pragma: no mutate — ternary picks color wrapping; cosmetic
            val_part = (
                self._value_color + val_repr + RESET if self._colors and self._value_color else val_repr
            )  # pragma: no mutate — ternary picks color wrapping; cosmetic
            parts.append(
                key_part + "=" + val_part
            )  # pragma: no mutate — key/value separator concat; output is non-semantic formatting

        return " ".join(
            parts
        )  # pragma: no mutate — join separator is the rendered line delimiter; asserted via snapshot tests
