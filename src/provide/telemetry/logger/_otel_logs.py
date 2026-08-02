# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Stateless OTel log-provider wiring.

Split out of ``core.py`` to keep that module under the 500-line ceiling. Only the
stateless helpers live here — deciding whether an installed provider can be
reused reads ``core``'s module globals and so stays there.
"""

from __future__ import annotations

import logging
import warnings
from typing import Any, Protocol, cast

from provide.telemetry import _otel
from provide.telemetry.config import TelemetryConfig


def has_otel_logs() -> bool:
    return _otel.has_otel()


class InstrumentationLoggingHandlerFactory(Protocol):
    def __call__(
        self,
        level: int,
        logger_provider: object | None,
        log_code_attributes: bool,
        **kwargs: object,
    ) -> logging.Handler: ...


def load_otel_logs_components() -> tuple[Any, Any, Any, Any, Any] | None:
    """Load the SDK components. Callers gate on has_otel_logs() first."""
    return _otel.load_otel_logs_components()


def load_instrumentation_logging_handler() -> InstrumentationLoggingHandlerFactory | None:
    return _otel.load_instrumentation_logging_handler()


def log_provider_config_key(config: TelemetryConfig) -> tuple[object, ...]:
    """Identity of the provider-affecting config fields.

    Two configs with equal keys can share an installed log provider; any
    difference requires a fresh one.
    """
    return (
        config.service_name,
        config.version,
        config.logging.otlp_endpoint,
        tuple(sorted(config.logging.otlp_headers.items())),
        config.exporter.logs_timeout_seconds,
    )


def make_otel_logging_handler(
    sdk_logs_mod: Any,
    provider: object,
    level: int,
    config: TelemetryConfig,
    instrumentation_handler_cls: InstrumentationLoggingHandlerFactory | None = None,
) -> logging.Handler:
    """Build the stdlib handler that forwards records to the OTel log provider.

    The factory is injected rather than looked up here so that a caller — and the
    tests that patch it — controls which one is used. Resolving it internally
    would make the lookup unpatchable from ``core``.
    """
    if instrumentation_handler_cls is not None:
        return instrumentation_handler_cls(
            level=level,
            logger_provider=provider,
            log_code_attributes=config.logging.log_code_attributes,
        )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        handler = sdk_logs_mod.LoggingHandler(level=level, logger_provider=provider)
        # cast() returns its second argument unchanged at runtime, so mutating
        # the type argument cannot be observed.
        return cast(logging.Handler, handler)  # pragma: no mutate
