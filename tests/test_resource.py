# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for the layered OTel resource builder (precedence contract).

framework default  <  OTEL_* env  <  explicit config
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from provide.telemetry._resource import (
    _env_identity_keys,
    _resolve_resource_attrs,
    build_resource,
)
from provide.telemetry.config import TelemetryConfig


def _cfg(
    service_name: str = "provide-service",
    environment: str = "dev",
    version: str = "0.0.0",
) -> TelemetryConfig:
    # Explicit params (not **overrides) so both mypy and ty accept the types.
    return TelemetryConfig(service_name=service_name, environment=environment, version=version)


class TestEnvIdentityKeys:
    def test_empty_environment_yields_no_keys(self) -> None:
        assert _env_identity_keys({}) == set()

    def test_otel_service_name_adds_service_name(self) -> None:
        assert _env_identity_keys({"OTEL_SERVICE_NAME": "svc"}) == {"service.name"}

    def test_blank_otel_service_name_is_ignored(self) -> None:
        # Guards the .strip() truthiness check.
        assert _env_identity_keys({"OTEL_SERVICE_NAME": "   "}) == set()

    def test_resource_attributes_keys_are_parsed(self) -> None:
        keys = _env_identity_keys({"OTEL_RESOURCE_ATTRIBUTES": "host.name=web-1,deployment.environment=prod"})
        assert keys == {"host.name", "deployment.environment"}

    def test_pairs_without_a_value_separator_are_skipped(self) -> None:
        # "service.version" alone has no '=', so it contributes no key.
        assert _env_identity_keys({"OTEL_RESOURCE_ATTRIBUTES": "service.version"}) == set()

    def test_blank_keys_are_skipped(self) -> None:
        assert _env_identity_keys({"OTEL_RESOURCE_ATTRIBUTES": "=orphan, =x"}) == set()

    def test_key_split_on_first_equals(self) -> None:
        # A value containing '=' must not bleed into the key (partition, not
        # rpartition): "k=v=w" is key "k".
        assert _env_identity_keys({"OTEL_RESOURCE_ATTRIBUTES": "k=v=w"}) == {"k"}

    def test_service_name_from_both_sources_is_deduped(self) -> None:
        keys = _env_identity_keys({"OTEL_SERVICE_NAME": "svc", "OTEL_RESOURCE_ATTRIBUTES": "service.name=other"})
        assert keys == {"service.name"}


class TestResolveResourceAttrs:
    def test_all_default_no_env_falls_back_to_floor(self) -> None:
        assert _resolve_resource_attrs(_cfg(), set()) == {
            "service.name": "provide-service",
            "deployment.environment": "dev",
            "service.version": "0.0.0",
        }

    def test_explicit_values_are_included(self) -> None:
        resolved = _resolve_resource_attrs(_cfg(service_name="checkout", environment="prod", version="1.2.3"), set())
        assert resolved == {
            "service.name": "checkout",
            "deployment.environment": "prod",
            "service.version": "1.2.3",
        }

    def test_explicit_wins_even_when_env_provides_key(self) -> None:
        # Explicit differs from default → included so it overrides env.
        resolved = _resolve_resource_attrs(_cfg(service_name="checkout"), {"service.name"})
        assert resolved["service.name"] == "checkout"

    def test_default_key_provided_by_env_is_omitted(self) -> None:
        # Left at default AND supplied by env → omitted so env shows through.
        resolved = _resolve_resource_attrs(_cfg(), {"service.name"})
        assert "service.name" not in resolved
        # The keys env does not provide still get the floor.
        assert resolved["deployment.environment"] == "dev"
        assert resolved["service.version"] == "0.0.0"

    def test_default_key_absent_from_env_uses_floor(self) -> None:
        resolved = _resolve_resource_attrs(_cfg(), set())
        assert resolved["service.name"] == "provide-service"


class TestBuildResource:
    def test_passes_resolved_attrs_to_resource_create(self) -> None:
        resource_cls = SimpleNamespace(create=Mock(return_value="RES"))
        out = build_resource(_cfg(service_name="checkout"), resource_cls, environ={})
        assert out == "RES"
        resource_cls.create.assert_called_once_with(
            {
                "service.name": "checkout",
                "deployment.environment": "dev",
                "service.version": "0.0.0",
            }
        )

    def test_env_provided_identity_is_omitted_so_sdk_applies_it(self) -> None:
        resource_cls = SimpleNamespace(create=Mock(return_value="RES"))
        build_resource(_cfg(), resource_cls, environ={"OTEL_SERVICE_NAME": "env-svc"})
        # service.name left to the SDK's env detector; floor fills the rest.
        resource_cls.create.assert_called_once_with({"deployment.environment": "dev", "service.version": "0.0.0"})

    def test_defaults_to_process_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # environ=None reads os.environ; clear the OTEL_* vars for determinism.
        for var in ("OTEL_SERVICE_NAME", "OTEL_RESOURCE_ATTRIBUTES"):
            monkeypatch.delenv(var, raising=False)
        resource_cls = SimpleNamespace(create=Mock(return_value="RES"))
        build_resource(_cfg(), resource_cls)
        resource_cls.create.assert_called_once_with(
            {
                "service.name": "provide-service",
                "deployment.environment": "dev",
                "service.version": "0.0.0",
            }
        )
