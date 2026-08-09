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
    # rsplit on "]" avoids false positives from IPv6 colons, and rpartition on
    # "@" avoids them from userinfo: in "user:pw@host" the colon separates
    # credentials, not a host from a port. Without the rpartition this rejected
    # every credentialed endpoint that did not also name an explicit port —
    # "https://user:pw@collector.example/v1/logs" failed with "invalid OTLP
    # endpoint port", which is both wrong and misleading. Go never had the bug
    # because net/url keeps User out of Host; Python, Rust and TypeScript all
    # scanned the whole authority and all three had it.
    #
    # No maxsplit, and no `# pragma: no mutate`. Taking [-1] makes maxsplit
    # unobservable, so passing one only created mutants that were equivalent
    # (1 -> 2, dropping the argument) while a bare pragma to silence them
    # suppressed every *other* mutation on the line as well — including the
    # separator and the index, which are load-bearing for IPv6 endpoints. With
    # the argument gone, split/rsplit are genuinely indistinguishable here (the
    # last segment is the same either way) and everything mutmut still generates
    # is killable — see test_endpoint_ipv6_without_port_is_accepted.
    host_port = parsed.netloc.rpartition("@")[2]
    after_bracket = host_port.rsplit("]")[-1]
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
