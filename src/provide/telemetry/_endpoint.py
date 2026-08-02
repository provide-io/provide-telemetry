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
    #
    # No maxsplit, and no `# pragma: no mutate`. Taking [-1] makes maxsplit
    # unobservable, so passing one only created mutants that were equivalent
    # (1 -> 2, dropping the argument) while a bare pragma to silence them
    # suppressed every *other* mutation on the line as well — including the
    # separator and the index, which are load-bearing for IPv6 endpoints. With
    # the argument gone, split/rsplit are genuinely indistinguishable here (the
    # last segment is the same either way) and everything mutmut still generates
    # is killable — see test_endpoint_ipv6_without_port_is_accepted.
    after_bracket = parsed.netloc.rsplit("]")[-1]
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
