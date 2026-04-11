# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Internal helpers for masking OTLP credentials in config representations."""

from __future__ import annotations

import dataclasses
from urllib.parse import urlparse, urlunparse


def _mask_header_value(value: str) -> str:
    """Mask a header value: show first 4 chars + **** if >= 8 chars, else ****."""
    if len(value) < 8:
        return "****"
    return value[:4] + "****"


def _mask_headers(headers: dict[str, str]) -> dict[str, str]:
    return {k: _mask_header_value(v) for k, v in headers.items()}


def _mask_endpoint_url(url: str) -> str:
    """Mask password in URL userinfo (user:password@host)."""
    parsed = urlparse(url)
    if parsed.password:
        masked_netloc = f"{parsed.username}:****@{parsed.hostname}"
        if parsed.port:
            masked_netloc += f":{parsed.port}"
        return urlunparse(parsed._replace(netloc=masked_netloc))
    return url


def _masked_dataclass_repr(obj: object) -> str:
    """Return repr() for an otlp-bearing dataclass, masking headers/endpoint."""
    parts = []
    for f in dataclasses.fields(obj):  # type: ignore[arg-type]
        val = getattr(obj, f.name)
        if f.name == "otlp_headers":
            val = _mask_headers(val)
        elif f.name == "otlp_endpoint" and val is not None:
            val = _mask_endpoint_url(val)
        parts.append(f"{f.name}={val!r}")
    return f"{obj.__class__.__name__}({', '.join(parts)})"
