# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Helpers for :mod:`provide.telemetry.config` env parsing.

Kept as a sibling module so ``config.py`` stays under the 500 LOC gate.
"""

from __future__ import annotations

__all__ = [
    "MAX_DURATION_SECONDS",
    "MAX_EXPORT_RETRIES",
    "parse_duration_float",
    "parse_env_retries",
    "resolve_otlp_endpoint",
    "validate_retries_ceiling",
    "warn_on_endpoint_shadowing",
]

import warnings
from collections.abc import Mapping

from provide.telemetry.exceptions import ConfigurationError

# Upper bound on any *_timeout_seconds or *_backoff_seconds config value.
# 3600s (one hour) is already far outside any healthy exporter deadline; values
# above this usually indicate a unit mistake (minutes/ms confused with seconds)
# and silently tie up worker threads, so we reject them up front.
MAX_DURATION_SECONDS = 3600.0

# Upper bound on PROVIDE_EXPORTER_*_RETRIES. run_with_resilience makes
# retries + 1 attempts per export call, so an unbounded value turns one bad
# exporter into hours of blocking retries. TypeScript rejects the same values
# (its MAX_EXPORT_ATTEMPTS is this + 1), so an env shared across a polyglot
# deployment fails the same way in every language.
MAX_EXPORT_RETRIES = 100


def validate_retries_ceiling(value: int, field: str) -> None:
    """Reject an exporter retries value above :data:`MAX_EXPORT_RETRIES`."""
    if value > MAX_EXPORT_RETRIES:
        raise ConfigurationError(f"{field} must be at most {MAX_EXPORT_RETRIES}, got {value}")


def parse_env_retries(value: str, field: str) -> int:
    """Parse an exporter retries env var, enforcing the shared ceiling.

    Mirrors :func:`config._parse_env_int` but additionally rejects values
    greater than :data:`MAX_EXPORT_RETRIES`, naming the env var so the operator
    who set it can find it.
    """
    try:
        parsed = int(value)
    except ValueError:
        raise ConfigurationError(f"invalid integer for {field}: {value!r}") from None
    validate_retries_ceiling(parsed, field)
    return parsed


def parse_duration_float(value: str, field: str) -> float:
    """Parse a duration env var, enforcing an upper bound.

    Mirrors :func:`config._parse_env_float` but additionally rejects values
    greater than :data:`MAX_DURATION_SECONDS`.  Used for every
    ``*_timeout_seconds`` and ``*_backoff_seconds`` input.
    """
    try:
        parsed = float(value)
    except ValueError:
        raise ConfigurationError(f"invalid float for {field}: {value!r}") from None
    if parsed < 0.0:
        raise ConfigurationError(f"{field} must be >= 0 seconds, got {parsed!r}")
    if parsed > MAX_DURATION_SECONDS:
        raise ConfigurationError(f"{field} must be <= {MAX_DURATION_SECONDS} seconds, got {parsed!r}")
    return parsed


# Signal name → (specific env var, resolved value).  We use a sorted tuple so
# the emitted warning order is deterministic across runs.
_SIGNAL_SPECIFIC_VARS: tuple[tuple[str, str], ...] = (
    ("logs", "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT"),
    ("metrics", "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"),
    ("traces", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"),
)
_FALLBACK_VAR = "OTEL_EXPORTER_OTLP_ENDPOINT"


def resolve_otlp_endpoint(data: Mapping[str, str], specific_var: str, signal_path: str) -> str | None:
    """Resolve a per-signal OTLP endpoint from specific or shared env vars."""
    specific = data.get(specific_var)
    if specific:
        return specific
    shared = data.get(_FALLBACK_VAR)
    if not shared:
        return None
    return f"{shared.rstrip('/')}/{signal_path}"


def warn_on_endpoint_shadowing(data: Mapping[str, str]) -> None:
    """Emit a ``UserWarning`` when a specific endpoint var shadows the fallback.

    If both a signal-specific endpoint env var (e.g.
    ``OTEL_EXPORTER_OTLP_LOGS_ENDPOINT``) and the generic
    ``OTEL_EXPORTER_OTLP_ENDPOINT`` are set to **different** values, the
    specific one wins — that's easy to miss in ops.  Warn so the shadow is
    visible.  If they match, stay quiet.
    """
    fallback = data.get(_FALLBACK_VAR)
    if not fallback:
        return
    for signal, specific_var in _SIGNAL_SPECIFIC_VARS:
        specific = data.get(specific_var)
        if specific and specific != fallback:
            warnings.warn(
                (
                    f"{specific_var}={specific!r} shadows {_FALLBACK_VAR}="
                    f"{fallback!r} for {signal}; resolved value is {specific!r}"
                ),
                UserWarning,
                stacklevel=3,
            )
