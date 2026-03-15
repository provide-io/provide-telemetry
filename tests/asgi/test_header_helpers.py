# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

from __future__ import annotations

from undef.telemetry.headers import _decode_header_value, _normalize_header_name, get_header


def test_get_header_handles_missing_and_unsupported_entries() -> None:
    assert get_header({}, b"x-request-id") is None
    scope = {"headers": [(1, b"ignored"), (b"x-request-id", 123)]}
    assert get_header(scope, b"x-request-id") is None
    # Unsupported header-name entries must be skipped, not treated as terminal.
    scope_with_late_match = {"headers": [(1, b"ignored"), (b"x-request-id", b"rid")]}
    assert get_header(scope_with_late_match, b"x-request-id") == "rid"


def test_get_header_decodes_bytes_and_accepts_string_values() -> None:
    scope = {"headers": [("X-Request-Id", "rid"), (b"x-session-id", b"sid")]}
    assert get_header(scope, b"x-request-id") == "rid"
    assert get_header(scope, b"x-session-id") == "sid"


def test_get_header_decodes_non_utf8_via_latin1() -> None:
    scope = {"headers": [(b"x-request-id", b"\xff")]}
    assert get_header(scope, b"x-request-id") == "\xff"
    scope2 = {"headers": [(b"x-request-id", b"caf\xe9")]}
    assert get_header(scope2, b"x-request-id") == "café"


def test_get_header_uses_exact_normalized_key_match() -> None:
    scope = {"headers": [(b"x-other", b"wrong"), ("X-Request-Id", "right")]}
    assert get_header(scope, b"x-request-id") == "right"
    assert get_header(scope, b"x-missing") is None


def test_normalize_header_name_returns_lowercase_bytes() -> None:
    assert _normalize_header_name(b"X-REQUEST-ID") == b"x-request-id"
    normalized = _normalize_header_name("X-REQUEST-ID")
    assert normalized == b"x-request-id"
    assert isinstance(normalized, bytes)


def test_normalize_header_name_utf8_string_path() -> None:
    # HTTP header names are ASCII-only; non-ASCII values are rejected.
    assert _normalize_header_name("X-ÄCTOR-ID") == b""
    # Lone surrogates are rejected instead of raising during normalization.
    assert _normalize_header_name("X-\udcff-ID") == b""


def test_decode_header_value_type_handling() -> None:
    assert _decode_header_value("abc") == "abc"
    assert _decode_header_value(b"abc") == "abc"
    assert _decode_header_value(b"\xff") == "\xff"
    assert _decode_header_value(b"caf\xe9") == "café"
    assert _decode_header_value(42) is None
