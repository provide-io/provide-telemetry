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

import re

import pytest

from provide.telemetry.pii import (
    _MAX_SECRET_SCAN_LENGTH,
    _custom_secret_patterns,
    _expand_to_token,
    _looks_like_path,
    _secret_spans,
    redact_secret_spans,
    register_secret_pattern,
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

# A path that the long_base64 pattern matches, and a base64 secret it also
# matches. Each is checked standalone below so neither test can pass by
# accident.
SHADOWING_PATH = "/home/deploy/apps/production/current/lib/service"
B64_SECRET = "c2VjcmV0a2V5MTIzNDU2Nzg5MGFiY2RlZmdoaWprbG1ub3A"  # pragma: allowlist secret


@pytest.mark.parametrize("line", PATHS)
def test_a_filesystem_path_is_not_a_secret(line: str) -> None:
    assert _secret_spans(line) == []
    assert redact_secret_spans(line) == line


def test_every_secret_in_a_value_is_redacted() -> None:
    """A second credential in the same field must not survive the first.

    Whole-value blanking covered every secret in a field for free. Scoping
    redaction to one token dropped that guarantee silently: the field is
    still flagged as containing a secret, but only the first one goes.
    """
    first, second = "AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLB"
    assert _secret_spans(first) != [], "first constant must be a secret"
    assert _secret_spans(second) != [], "second constant must be a secret"

    out = redact_secret_spans(f"first {first} second {second}")

    assert first not in out
    assert second not in out
    assert out == "first *** second ***"


def test_a_path_does_not_shadow_a_secret_later_in_the_value() -> None:
    """A path-shaped match must not stop the scan for that pattern.

    long_base64 matches the path first. Suppressing it as path-shaped moved
    the loop on to the next pattern, and long_base64 is the last one -- so
    the real secret behind the path was never looked for and reached the log
    in full. A path prefix must not be a redaction bypass.
    """
    assert _secret_spans(SHADOWING_PATH) == [], "path must be suppressed alone"
    assert _secret_spans(B64_SECRET) != [], "secret must be caught alone"

    out = redact_secret_spans(f"{SHADOWING_PATH} {B64_SECRET}")

    assert B64_SECRET not in out
    assert out == f"{SHADOWING_PATH} ***"


def test_a_path_after_a_secret_is_still_left_alone() -> None:
    """The mirror of the shadowing case: secret first, path second.

    Once the scan stopped short-circuiting, every later match of a pattern is
    examined too -- so the path guard has to hold for those as well, not only
    for the first match. Here long_base64 hits the secret first and the path
    second; the second match must be skipped, not redacted.
    """
    out = redact_secret_spans(f"{B64_SECRET} {SHADOWING_PATH}")

    assert B64_SECRET not in out
    assert out == f"*** {SHADOWING_PATH}"


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
    assert _secret_spans("short") == []
    assert redact_secret_spans("short") == "short"


def test_an_oversize_value_is_not_scanned() -> None:
    """ReDoS cap: past _MAX_SECRET_SCAN_LENGTH the scan is skipped entirely."""
    oversize = "A" * (_MAX_SECRET_SCAN_LENGTH + 1)
    assert _secret_spans(oversize) == []
    assert redact_secret_spans(oversize) == oversize


def test_a_long_value_with_no_pattern_match_is_left_alone() -> None:
    """Reaches the end of the pattern loop without a match."""
    clean = "the quick brown fox jumps over the lazy dog and keeps on running"
    assert _secret_spans(clean) == []
    assert redact_secret_spans(clean) == clean


def test_a_span_with_too_few_segments_is_not_path_shaped() -> None:
    assert _looks_like_path("usr/local") is False


def test_a_span_of_long_wordless_segments_is_not_path_shaped() -> None:
    assert _looks_like_path("ABCDEFGHIJ/1234567890/KLMNOPQRST") is False


def test_a_span_of_short_lowercase_words_is_path_shaped() -> None:
    assert _looks_like_path("usr/local/lib") is True


def test_a_span_with_one_wordy_segment_in_three_is_not_path_shaped() -> None:
    """The ratio is a product, not a sum: one word in three is a minority.

    ``wordy + 2 >= 3`` would call this a path; ``wordy * 2 >= 3`` does not.
    """
    assert _looks_like_path("usr/AB12/CD34") is False


def test_a_pattern_matching_the_empty_string_redacts_nothing() -> None:
    """A degenerate custom pattern must terminate and take no innocent word.

    Scanning every match means a pattern that can match the empty string
    yields one at every position. Without a guard the walk either never ends
    or widens a zero-length match to whatever token it landed in, blanking a
    word that holds no secret.
    """
    register_secret_pattern("empty_matcher", re.compile("Z*"))
    try:
        clean = "the quick brown fox jumps over it"
        assert redact_secret_spans(clean) == clean
        assert _secret_spans(clean) == []
    finally:
        _custom_secret_patterns.clear()


def test_a_path_with_exactly_half_wordy_segments_is_path_shaped() -> None:
    """The wordy-segment test is >=, not >.

    Half the segments being short lowercase words is enough to call it a path.
    A deep path often carries opaque segments -- a hash, a version, a build id
    -- alongside the words, so requiring a strict majority would start
    redacting those again.
    """
    assert _looks_like_path("usr/local/AB12/CD34") is True


def test_a_credential_token_at_the_very_start_is_removed_whole() -> None:
    """Widening must reach index 0, and must land on it exactly.

    The earlier partial-match test puts the token mid-string, so the leftward
    walk always stops on a space. Here the token starts the value, so the walk
    has to run to the start of the string -- and the match begins at an odd
    offset inside it, so a walk that steps two at a time overshoots past zero.
    """
    prefixed = f"abcde{JWT} tail"
    assert _expand_to_token(prefixed, 5, 10) == (0, len(prefixed) - len(" tail"))
    assert redact_secret_spans(prefixed) == "*** tail"


def test_a_zero_length_match_does_not_end_the_scan() -> None:
    """Skipping an empty match must continue, not stop.

    A pattern with an optional group matches the empty string at every
    position before it reaches the real credential. Treating the first empty
    match as the end of the scan means the secret behind it is never found --
    the same shape of leak as a path shadowing a secret.
    """
    secret = "SUPERSECRETVALUE123"
    register_secret_pattern("optional_secret", re.compile(f"(?:{secret})?"))
    try:
        out = redact_secret_spans(f"prefix words {secret} suffix")
        assert secret not in out
        assert out == "prefix words *** suffix"
    finally:
        _custom_secret_patterns.clear()
