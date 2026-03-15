# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
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

    def __init__(
        self,
        colors: bool = True,
        key_color: str = "",
        value_color: str = "",
        fields: tuple[str, ...] = (),
    ) -> None:
        self._colors = colors
        self._key_color = key_color
        self._value_color = value_color
        self._fields = fields

    def __call__(self, logger: object, name: str, event_dict: dict[str, Any]) -> str:  # noqa: ARG002
        parts: list[str] = []

        # 1. Timestamp
        ts = event_dict.pop("timestamp", None)
        if ts is not None:
            ts_str = str(ts)
            if self._colors:
                parts.append(DIM + ts_str + RESET)
            else:
                parts.append(ts_str)

        # 2. Level
        level = event_dict.pop("level", "")
        level_str = str(level).lower()
        padded = level_str.ljust(_LEVEL_PAD)
        if self._colors:
            color = LEVEL_COLORS.get(level_str, "")
            parts.append("[" + color + padded + RESET + "]")
        else:
            parts.append("[" + padded + "]")

        # 3. Event / message body
        event = event_dict.pop("event", "")
        parts.append(str(event))

        # 4. Remaining keys — sorted, optionally filtered key=repr(value) pairs
        fields_set = set(self._fields)
        filtered_items = [(k, event_dict[k]) for k in sorted(event_dict) if not self._fields or k in fields_set]
        for key, val in filtered_items:
            val_repr = repr(val)
            key_part = self._key_color + key + RESET if self._colors and self._key_color else key
            val_part = self._value_color + val_repr + RESET if self._colors and self._value_color else val_repr
            parts.append(key_part + "=" + val_part)

        return " ".join(parts)
