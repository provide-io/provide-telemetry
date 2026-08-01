# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""OTLP endpoint validation helpers."""

from __future__ import annotations

from urllib.parse import ParseResult, urlparse

_VALID_PORT_RANGE = range(1, 65536)


def _check_port(parsed: ParseResult, endpoint: str) -> None:
    """Reject non-numeric, out-of-range, or empty port components."""
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"invalid OTLP endpoint port: {endpoint!r}") from exc
    if port is not None and port not in _VALID_PORT_RANGE:
        raise ValueError(f"invalid OTLP endpoint port: {endpoint!r}")
    # "http://host:" — colon present but urlparse sets port=None.
    # rsplit on "]" avoids false positives from IPv6 colons.
    # Taking [-1] makes the maxsplit argument irrelevant — the text after the
    # final "]" is the same for any maxsplit >= 1 and for none at all — so the
    # only non-equivalent mutation here is rsplit -> split, which is killed by
    # test_bracket_in_userinfo_is_split_from_the_right. The pragma has to sit on
    # a single-line statement: mutmut ignores one trailing a multi-line `if`.
    after_bracket = parsed.netloc.rsplit("]", 1)[-1]  # pragma: no mutate
    if port is None and ":" in after_bracket:
        raise ValueError(f"invalid OTLP endpoint port: {endpoint!r}")


def validate_otlp_endpoint(endpoint: str | None) -> str:
    """Return endpoint when it is a valid absolute OTLP HTTP URL, else raise ValueError."""
    if endpoint is None:
        raise ValueError("invalid OTLP endpoint: None")
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.hostname is None:
        raise ValueError(f"invalid OTLP endpoint: {endpoint!r}")
    _check_port(parsed, endpoint)
    return endpoint
