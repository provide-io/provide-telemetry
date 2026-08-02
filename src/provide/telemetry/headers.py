# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Shared header extraction helpers."""

from __future__ import annotations

__all__ = ["get_header"]

from typing import Any

# Codec names are looked up case-insensitively, so a case mutation of either
# selects the identical codec — the only provably-equivalent mutation at the
# decode call sites. They are hoisted here so each carries its own suppression:
# a bare pragma on the `value.decode(...)` lines would have silenced the whole
# line, including the argument-removal mutants that turn a decode into a
# TypeError and the `"XXutf-8XX"` mutant that raises LookupError past the
# UnicodeDecodeError handler.
_PRIMARY_CODEC = "utf-8"  # pragma: no mutate
_FALLBACK_CODEC = "latin-1"  # pragma: no mutate


def get_header(scope: dict[str, Any], key: bytes) -> str | None:
    """Return a decoded header value or None for malformed/unsupported values."""
    for name, value in scope.get("headers", []):
        if not isinstance(name, (bytes, str)):
            continue
        if _normalize_header_name(name) != key:
            continue
        return _decode_header_value(value)
    return None


def _normalize_header_name(name: bytes | str) -> bytes:
    if isinstance(name, bytes):
        return name.lower()
    lowered = name.lower()
    if not lowered.isascii():
        return b""
    return lowered.encode()


def _decode_header_value(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        try:
            return value.decode(_PRIMARY_CODEC)
        except UnicodeDecodeError:
            return value.decode(_FALLBACK_CODEC)
    return None
