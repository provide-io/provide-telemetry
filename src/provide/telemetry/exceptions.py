# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Exception hierarchy for provide.telemetry."""

from __future__ import annotations

__all__ = [
    "ConfigurationError",
    "ProviderImmutableError",
    "TelemetryError",
]


class TelemetryError(Exception):
    """Base exception for all provide.telemetry errors."""


class ConfigurationError(TelemetryError, ValueError):
    """Raised when telemetry configuration is invalid.

    Invalid configuration is both a telemetry-domain error and an invalid
    value error, so callers may catch either boundary.
    """


class ProviderImmutableError(ConfigurationError, RuntimeError):
    """Raised when a provider-changing runtime update is requested in host mode.

    Backward-compatibility note:
      * subclassing ``RuntimeError`` keeps ``pytest.raises(RuntimeError)``-based
        assertions functioning for existing test suites;
      * subclassing ``ConfigurationError`` keeps telemetry-domain exception trees
        aligned with the package's existing ``TelemetryError`` hierarchy.
    """
