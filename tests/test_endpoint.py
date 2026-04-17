# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for provide.telemetry._endpoint — OTLP endpoint validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from provide.telemetry._endpoint import validate_otlp_endpoint

_FIXTURES_PATH = Path(__file__).resolve().parent.parent / "spec" / "behavioral_fixtures.yaml"
_FIXTURES = yaml.safe_load(_FIXTURES_PATH.read_text())
_ENDPOINT_FIXTURES = _FIXTURES["endpoint_validation"]


def _find_project_root() -> Path:
    """Walk up from this file until we find VERSION, anchoring to the real project root."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "VERSION").exists():
            return parent
    raise FileNotFoundError("Could not locate project root (no VERSION file found)")  # pragma: no cover


_FIXTURES_PATH = _find_project_root() / "spec" / "behavioral_fixtures.yaml"
_FIXTURES = yaml.safe_load(_FIXTURES_PATH.read_text())
_ENDPOINT_FIXTURES = _FIXTURES["endpoint_validation"]


class TestValidateOtlpEndpoint:
    def test_valid_http_endpoint(self) -> None:
        assert validate_otlp_endpoint("http://localhost:4318") == "http://localhost:4318"

    def test_valid_https_endpoint(self) -> None:
        assert validate_otlp_endpoint("https://collector.example.com") == "https://collector.example.com"

    def test_valid_endpoint_with_path(self) -> None:
        assert validate_otlp_endpoint("http://host:4318/v1/traces") == "http://host:4318/v1/traces"

    def test_missing_scheme_raises(self) -> None:
        with pytest.raises(ValueError, match="invalid OTLP endpoint"):
            validate_otlp_endpoint("localhost:4318")

    def test_invalid_scheme_raises(self) -> None:
        with pytest.raises(ValueError, match="invalid OTLP endpoint"):
            validate_otlp_endpoint("ftp://host:4318")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="invalid OTLP endpoint"):
            validate_otlp_endpoint("")

    def test_path_only_raises(self) -> None:
        with pytest.raises(ValueError, match="invalid OTLP endpoint"):
            validate_otlp_endpoint("/v1/traces")

    def test_scheme_only_raises(self) -> None:
        with pytest.raises(ValueError, match="invalid OTLP endpoint"):
            validate_otlp_endpoint("http://")

    def test_none_raises(self) -> None:
        with pytest.raises(ValueError, match="invalid OTLP endpoint"):
            validate_otlp_endpoint(None)


class TestEndpointFixtureParity:
    @pytest.mark.parametrize("case", _ENDPOINT_FIXTURES["valid"], ids=lambda c: c["description"])
    def test_parity_valid_endpoint(self, case: dict[str, str]) -> None:
        assert validate_otlp_endpoint(case["endpoint"]) == case["endpoint"]

    @pytest.mark.parametrize("case", _ENDPOINT_FIXTURES["invalid"], ids=lambda c: c["description"])
    def test_parity_invalid_endpoint(self, case: dict[str, str]) -> None:
        with pytest.raises(ValueError):
            validate_otlp_endpoint(case["endpoint"])


class TestInjectLoggerName:
    """Cover inject_logger_name branches: 85->87 (no name anywhere), 87->89 (falsy name skipped)."""

    def test_injects_logger_name_from_event_dict(self) -> None:
        from provide.telemetry.logger.processors import inject_logger_name

        result = inject_logger_name(None, "info", {"logger_name": "mymod", "event": "test"})
        assert result["logger_name"] == "mymod"

    def test_falls_back_to_logger_attr(self) -> None:
        from types import SimpleNamespace

        from provide.telemetry.logger.processors import inject_logger_name

        fake_logger = SimpleNamespace(name="fallback_mod")
        result = inject_logger_name(fake_logger, "info", {"event": "test"})
        assert result["logger_name"] == "fallback_mod"

    def test_no_name_anywhere_skips_injection(self) -> None:
        from provide.telemetry.logger.processors import inject_logger_name

        result = inject_logger_name(None, "info", {"event": "test"})
        assert "logger_name" not in result

    def test_empty_name_skips_injection(self) -> None:
        from provide.telemetry.logger.processors import inject_logger_name

        result = inject_logger_name(None, "info", {"logger_name": "", "event": "test"})
        assert "logger_name" not in result or result.get("logger_name") == ""
