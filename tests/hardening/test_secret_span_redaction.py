# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Span-scoped secret redaction and the filesystem-path guard.

The long_base64 pattern is ``[A-Za-z0-9+/]{40,}`` and ``/`` belongs to the
base64 alphabet, so a deep path of unpunctuated segments used to match it and
the whole field became ``***`` -- including fields whose entire job was to
print a remediation command.
"""

from __future__ import annotations

import pytest

from provide.telemetry.pii import (
    _MAX_SECRET_SCAN_LENGTH,
    _looks_like_path,
    _secret_span,
    redact_secret_spans,
)

# A JWT has three dot-separated parts; the jwt pattern matches only the first
# two, which is why redaction widens to the whitespace-delimited token.
JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"  # pragma: allowlist secret
    ".eyJzdWIiOiIxMjM0NTY3ODkwIn0"
    ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
)

PATHS = [
    "/home/deploy/apps/production/current/lib/service",
    "/var/lib/docker/overlay2/abcdef0123456789/merged/app",
    "make -C /home/deploy/apps/production/current/native/capture install",
    "/private/var/folders/sg/wy47gw996f78fznt898m8x540000gn/T/pytest-of-tim",
]


@pytest.mark.parametrize("line", PATHS)
def test_a_filesystem_path_is_not_a_secret(line: str) -> None:
    assert _secret_span(line) is None
    assert redact_secret_spans(line) == line


def test_a_real_base64_secret_is_still_redacted() -> None:
    secret = "GstpFvsHIiSVR91i5FLxOKZ8mNRZ5EifnBQR2i6bOhs="  # pragma: allowlist secret
    assert redact_secret_spans(secret) == "***"


def test_slash_bearing_base64_is_not_mistaken_for_a_path() -> None:
    """Long wordless segments are base64, not directories."""
    secret = "abcdefghij/klmnopqrst/uvwxyzABCD/EFGHIJKLMN/OPQRSTUVWX"  # pragma: allowlist secret
    assert redact_secret_spans(secret) == "***"


def test_a_partial_match_still_removes_the_whole_credential() -> None:
    """Covers the leading-edge widening: the token starts before the match."""
    signature = JWT.rsplit(".", 1)[1]
    out = redact_secret_spans(f"auth header prefix{JWT} rejected")
    assert signature not in out
    assert out == "auth header *** rejected"


def test_surrounding_words_survive() -> None:
    assert redact_secret_spans("token AKIAIOSFODNN7EXAMPLE leaked") == "token *** leaked"


def test_a_value_below_the_minimum_length_is_never_scanned() -> None:
    assert _secret_span("short") is None
    assert redact_secret_spans("short") == "short"


def test_an_oversize_value_is_not_scanned() -> None:
    """ReDoS cap: past _MAX_SECRET_SCAN_LENGTH the scan is skipped entirely."""
    oversize = "A" * (_MAX_SECRET_SCAN_LENGTH + 1)
    assert _secret_span(oversize) is None
    assert redact_secret_spans(oversize) == oversize


def test_a_long_value_with_no_pattern_match_is_left_alone() -> None:
    """Reaches the end of the pattern loop without a match."""
    clean = "the quick brown fox jumps over the lazy dog and keeps on running"
    assert _secret_span(clean) is None
    assert redact_secret_spans(clean) == clean


def test_a_span_with_too_few_segments_is_not_path_shaped() -> None:
    assert _looks_like_path("usr/local") is False


def test_a_span_of_long_wordless_segments_is_not_path_shaped() -> None:
    assert _looks_like_path("ABCDEFGHIJ/1234567890/KLMNOPQRST") is False


def test_a_span_of_short_lowercase_words_is_path_shaped() -> None:
    assert _looks_like_path("usr/local/lib") is True
