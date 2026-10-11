# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Internal helpers for masking OTLP credentials in config representations."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

if TYPE_CHECKING:
    from provide.telemetry.config import TelemetryConfig


def redact_config(config: TelemetryConfig) -> dict[str, object]:
    """Return config fields as a dict with OTLP secrets masked."""
    # asdict() deep-copies every non-dataclass value it meets, which a live
    # ReceiptSink holding a socket or a database client cannot survive. The
    # sink is a delivery destination rather than configuration data, so it is
    # detached for the walk and reported by presence only.
    sink = config.receipt_sink
    # A placeholder nobody reads: raw's entry is replaced below and the field is
    # restored in `finally`, so any stand-in asdict can copy behaves the same.
    config.receipt_sink = None  # pragma: no mutate — placeholder never read; the entry is replaced below and the real sink restored in finally
    try:
        raw = dataclasses.asdict(config)
    finally:
        config.receipt_sink = sink
    raw["receipt_sink"] = None if sink is None else type(sink).__name__
    for v in raw.values():
        if isinstance(v, dict):
            if "otlp_headers" in v:
                v["otlp_headers"] = _mask_headers(v["otlp_headers"])
            if "otlp_endpoint" in v and v["otlp_endpoint"] is not None:
                v["otlp_endpoint"] = _mask_endpoint_url(v["otlp_endpoint"])
    return raw


def _mask_header_value(value: str) -> str:
    """Mask a header value: show first 4 chars + **** if >= 8 chars, else ****."""
    if len(value) < 8:
        return "****"
    return value[:4] + "****"


def _mask_headers(headers: dict[str, str]) -> dict[str, str]:
    return {k: _mask_header_value(v) for k, v in headers.items()}


def _mask_netloc_password(netloc: str) -> str:
    """Replace the password in ``user:password@host`` and keep the rest verbatim.

    Text surgery on the authority rather than a rebuild from the parsed parts:
    ``.port`` raises on a malformed port, ``.hostname`` lowercases the host and
    strips an IPv6 literal's brackets, and none of that is the masker's to
    change. The last ``@`` ends the userinfo and the first ``:`` ends the user,
    the same split ``urllib`` makes.
    """
    userinfo, at, host = netloc.rpartition("@")
    username, colon, password = userinfo.partition(":")
    if not at or not colon or not password:
        return netloc
    return f"{username}:****@{host}"


def _mask_endpoint_url(url: str) -> str:
    """Mask the password in URL userinfo, malformed endpoints included.

    ``urlsplit`` itself raises on a broken IPv6 literal, and finds no authority
    at all in a scheme-less ``user:password@host``. Either way the authority is
    located by hand -- after ``://`` if there is one, up to the first ``/``,
    ``?`` or ``#`` -- so a config that cannot be parsed can still be printed
    without its credentials.
    """
    try:
        parsed = urlsplit(url)
    except ValueError:
        parsed = None
    if parsed is not None and parsed.netloc:
        masked = _mask_netloc_password(parsed.netloc)
        return url if masked == parsed.netloc else urlunsplit(parsed._replace(netloc=masked))
    scheme_end = url.find("://")
    start = scheme_end + 3 if scheme_end >= 0 else 0
    rest = url[start:]
    end = min((index for index in map(rest.find, "/?#") if index >= 0), default=len(rest))
    return url[:start] + _mask_netloc_password(rest[:end]) + rest[end:]


def _masked_dataclass_repr(obj: object) -> str:
    """Return repr() for an otlp-bearing dataclass, masking headers/endpoint."""
    parts = []
    for f in dataclasses.fields(obj):  # type: ignore
        val = getattr(obj, f.name)
        if f.name == "otlp_headers":
            val = _mask_headers(val)
        elif f.name == "otlp_endpoint" and val is not None:
            val = _mask_endpoint_url(val)
        parts.append(f"{f.name}={val!r}")
    return f"{obj.__class__.__name__}({', '.join(parts)})"
