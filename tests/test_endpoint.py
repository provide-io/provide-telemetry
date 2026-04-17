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

    def test_only_logger_key_used_when_logger_name_absent(self) -> None:
        """When only 'logger' key is present (not 'logger_name'), it should be used.

        Kills mutmut_6/7/8: get("logger") -> get(None) / get("XXloggerXX") / get("LOGGER").
        """
        from provide.telemetry.logger.processors import inject_logger_name

        result = inject_logger_name(None, "info", {"logger": "my.module", "event": "test"})
        assert result["logger_name"] == "my.module"

    def test_logger_name_takes_priority_over_logger(self) -> None:
        """When both 'logger_name' and 'logger' are present, 'logger_name' wins.

        Kills mutmut_1 (name=None), mutmut_2 (or->and), mutmut_3/4/5 (key mutations).
        With mutmut_1: name=None, falls through to getattr which returns None (no attr).
        With mutmut_2 (and): get("logger_name")="first" is truthy, and get("logger")="second"
          -> name="second" (wrong).
        With mutmut_3/4/5: get(None)/(wrong key) returns None for logger_name, falls to logger.
        """
        from provide.telemetry.logger.processors import inject_logger_name

        result = inject_logger_name(None, "info", {"logger_name": "first", "logger": "second", "event": "test"})
        assert result["logger_name"] == "first"

    def test_logger_key_only_no_logger_attr_on_logger_object(self) -> None:
        """Logger object without .name attr, but 'logger' key in event_dict.

        Kills mutmut_6/7/8 from the code path where 'logger_name' is absent.
        """
        from provide.telemetry.logger.processors import inject_logger_name

        result = inject_logger_name(object(), "info", {"logger": "from_dict", "event": "test"})
        assert result["logger_name"] == "from_dict"

    def test_ipv6_empty_port_raises(self) -> None:
        """IPv6 with trailing colon (empty port) must raise.

        Kills _check_port mutmut_14/15/17: rsplit("]",1)[-1] variations.
        For http://[::1]:, netloc=[::1]: -> rsplit("]",1)=["[::1", ":"], [-1]=":"
        """
        with pytest.raises(ValueError, match="invalid OTLP endpoint port"):
            validate_otlp_endpoint("http://[::1]:")

    def test_none_error_message_content(self) -> None:
        """Error message for None endpoint must contain 'invalid OTLP endpoint'.

        Kills validate_otlp_endpoint mutmut_3: "XXinvalid OTLP endpoint: NoneXX".
        """
        with pytest.raises(ValueError, match=r"^invalid OTLP endpoint: None$"):
            validate_otlp_endpoint(None)

    def test_truthy_netloc_but_no_hostname_raises(self) -> None:
        """URL with netloc=':8080' (truthy) but hostname=None must still raise.

        Kills validate_otlp_endpoint mutmut_8: changes `or not netloc or hostname is None`
        to `or (not netloc and hostname is None)`. The mutant would skip the check when
        netloc is truthy even though hostname is None (no actual host).
        """
        with pytest.raises(ValueError, match="invalid OTLP endpoint"):
            validate_otlp_endpoint("http://:8080")

    def test_port_error_includes_endpoint_string(self) -> None:
        """Port validation error must include the original endpoint string.

        Kills validate_otlp_endpoint mutmut_19: _check_port(parsed, None).
        With None, the f-string would show "invalid OTLP endpoint port: None".
        """
        with pytest.raises(ValueError, match=r"invalid OTLP endpoint port: 'http://host:0'"):
            validate_otlp_endpoint("http://host:0")
