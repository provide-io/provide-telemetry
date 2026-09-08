# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""The log signal's OTel ``Resource`` comes from the shared builder.

Traces and metrics call ``build_resource``; the log provider hand-rolled its own
``Resource.create({...})``, which meant the identity attached to exported log
records did not go through the ``floor < OTEL_* env < explicit`` ladder every
other signal follows. Two consequences: ``OTEL_SERVICE_NAME`` was honoured on
spans and ignored on logs, and ``deployment.environment`` never reached the log
resource at all.

Go (``sdklog.WithResource(_buildResource(cfg))``), TypeScript
(``otel-logs.ts`` → ``buildOtelResource``), Rust (one ``build_resource`` passed
to ``install_logger_provider``) and C# (one ``resource``, three
``SetResourceBuilder``) all share the builder across signals. Python was the
outlier.

The wiring test is the point of the file: ``build_resource`` was correct and
fixture-covered the whole time, and nothing failed when the log path stopped
calling it.
"""

from __future__ import annotations

from typing import Any

import pytest

from provide.telemetry.config import LoggingConfig, TelemetryConfig


def _otlp_config(**kw: Any) -> TelemetryConfig:
    logging_kw: dict[str, Any] = {"otlp_endpoint": "http://localhost:4318", "otlp_enabled": True}
    return TelemetryConfig(logging=LoggingConfig(**logging_kw), **kw)


@pytest.mark.parametrize(
    ("module_path", "attribute"),
    [
        ("provide.telemetry.tracing.provider", "build_resource"),
        ("provide.telemetry.metrics.provider", "build_resource"),
        ("provide.telemetry.logger.core", "build_resource"),
    ],
)
def test_every_signal_builds_its_resource_through_the_shared_builder(module_path: str, attribute: str) -> None:
    """A signal that hand-rolls its Resource silently leaves the ladder.

    Naming the three here means the next one to do it fails on import rather
    than by diverging in production.
    """
    import importlib

    module = importlib.import_module(module_path)

    assert hasattr(module, attribute), f"{module_path} does not import {attribute}"


def test_the_log_resource_honours_otel_service_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_SERVICE_NAME", "checkout")
    captured: dict[str, Any] = {}

    class _Resource:
        @staticmethod
        def create(attrs: dict[str, str]) -> object:
            captured.update(attrs)
            return object()

    from provide.telemetry._resource import build_resource

    build_resource(_otlp_config(), _Resource)

    assert "service.name" not in captured, "service.name was pinned by the SDK, so OTEL_SERVICE_NAME could not fill it"


def test_the_log_resource_carries_the_environment() -> None:
    captured: dict[str, Any] = {}

    class _Resource:
        @staticmethod
        def create(attrs: dict[str, str]) -> object:
            captured.update(attrs)
            return object()

    from provide.telemetry._resource import build_resource

    build_resource(_otlp_config(), _Resource, environ={})

    assert "deployment.environment" in captured


def test_two_environments_do_not_share_a_log_provider() -> None:
    """The reuse key decides whether an installed provider is kept.

    Once the resource carries deployment.environment, a key that ignores it
    hands a second environment the first one's resource.
    """
    from provide.telemetry.logger._otel_logs import log_provider_config_key

    dev = _otlp_config(environment="dev")
    prod = _otlp_config(environment="prod")

    assert log_provider_config_key(dev) != log_provider_config_key(prod)
