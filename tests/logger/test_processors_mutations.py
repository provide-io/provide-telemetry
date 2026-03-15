# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Tests targeting surviving mutation-testing mutants in logger/processors.py."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import structlog

from undef.telemetry.config import TelemetryConfig
from undef.telemetry.logger.processors import (
    add_standard_fields,
    apply_sampling,
    enforce_event_schema,
    merge_runtime_context,
)

# ── merge_runtime_context: trace_id / span_id key names ─────────────


class TestMergeRuntimeContextKeys:
    def test_trace_id_key_is_exact(self) -> None:
        """Kills: 'trace_id' → 'XXtrace_idXX' in both .get() and assignment."""
        with (
            patch(
                "undef.telemetry.logger.processors.get_trace_context",
                return_value={"trace_id": "abc123", "span_id": None},
            ),
            patch(
                "undef.telemetry.logger.processors.get_context",
                return_value={},
            ),
        ):
            result = merge_runtime_context(None, "", {"event": "x"})
        assert "trace_id" in result
        assert result["trace_id"] == "abc123"
        assert "span_id" not in result

    def test_span_id_key_is_exact(self) -> None:
        """Kills: 'span_id' → 'XXspan_idXX' in both .get() and assignment."""
        with (
            patch(
                "undef.telemetry.logger.processors.get_trace_context",
                return_value={"trace_id": None, "span_id": "def456"},
            ),
            patch(
                "undef.telemetry.logger.processors.get_context",
                return_value={},
            ),
        ):
            result = merge_runtime_context(None, "", {"event": "x"})
        assert "span_id" in result
        assert result["span_id"] == "def456"
        assert "trace_id" not in result

    def test_both_trace_and_span_set(self) -> None:
        """Both keys present when both values are non-None."""
        with (
            patch(
                "undef.telemetry.logger.processors.get_trace_context",
                return_value={"trace_id": "t1", "span_id": "s1"},
            ),
            patch(
                "undef.telemetry.logger.processors.get_context",
                return_value={},
            ),
        ):
            result = merge_runtime_context(None, "", {"event": "x"})
        assert result["trace_id"] == "t1"
        assert result["span_id"] == "s1"

    def test_neither_trace_nor_span_set(self) -> None:
        """Neither key present when both values are None."""
        with (
            patch(
                "undef.telemetry.logger.processors.get_trace_context",
                return_value={"trace_id": None, "span_id": None},
            ),
            patch(
                "undef.telemetry.logger.processors.get_context",
                return_value={},
            ),
        ):
            result = merge_runtime_context(None, "", {"event": "x"})
        assert "trace_id" not in result
        assert "span_id" not in result


# ── add_standard_fields: error taxonomy key checks ───────────────────


class TestAddStandardFieldsErrorTaxonomy:
    def test_adds_error_taxonomy_when_exc_name_present(self) -> None:
        """Kills: 'exc_name' → 'XXexc_nameXX' in the `in` check."""
        config = TelemetryConfig.from_env({})
        processor = add_standard_fields(config)
        event_dict: dict[str, object] = {
            "event": "app.error.occurred",
            "exc_name": "ValueError",
        }
        result = processor(None, "", event_dict)
        assert "error_type" in result
        assert result["error_name"] == "ValueError"

    def test_skips_taxonomy_when_error_type_already_present(self) -> None:
        """Kills: 'error_type' → 'XXerror_typeXX' in the `not in` check."""
        config = TelemetryConfig.from_env({})
        processor = add_standard_fields(config)
        event_dict: dict[str, object] = {
            "event": "app.error.occurred",
            "exc_name": "ValueError",
            "error_type": "custom",
        }
        result = processor(None, "", event_dict)
        assert result["error_type"] == "custom"
        # Should NOT have overwritten with classify_error output
        assert result.get("error_code") is None

    def test_skips_taxonomy_when_no_exc_name(self) -> None:
        """Kills: 'exc_name' → 'XXexc_nameXX' in the `in` check."""
        config = TelemetryConfig.from_env({})
        processor = add_standard_fields(config)
        event_dict: dict[str, object] = {"event": "app.request.ok"}
        result = processor(None, "", event_dict)
        assert "error_type" not in result

    def test_passes_status_code_to_classify_error(self) -> None:
        """Kills: 'status_code' key string and int isinstance check."""
        config = TelemetryConfig.from_env({})
        processor = add_standard_fields(config)
        event_dict: dict[str, object] = {
            "event": "app.error.occurred",
            "exc_name": "RuntimeError",
            "status_code": 503,
        }
        result = processor(None, "", event_dict)
        assert result["error_type"] == "server"
        assert result["error_code"] == "503"

    def test_non_int_status_code_treated_as_none(self) -> None:
        """Kills: isinstance(status_code, int) boundary."""
        config = TelemetryConfig.from_env({})
        processor = add_standard_fields(config)
        event_dict: dict[str, object] = {
            "event": "app.error.occurred",
            "exc_name": "RuntimeError",
            "status_code": "not-a-number",
        }
        result = processor(None, "", event_dict)
        # Non-int status_code → passed as None → classify_error returns 'internal'
        assert result["error_type"] == "internal"
        assert result["error_code"] == "0"

    def test_exc_name_value_passed_to_classify_error(self) -> None:
        """Kills: str(event_dict['exc_name']) → str(event_dict['XXexc_nameXX'])."""
        config = TelemetryConfig.from_env({})
        processor = add_standard_fields(config)
        event_dict: dict[str, object] = {
            "event": "app.error.occurred",
            "exc_name": "KeyError",
        }
        with patch(
            "undef.telemetry.logger.processors.classify_error",
            wraps=lambda exc, sc=None: {"error_type": "internal", "error_code": "0", "error_name": exc},
        ) as mock_classify:
            result = processor(None, "", event_dict)
        mock_classify.assert_called_once_with("KeyError", None)
        assert result["error_name"] == "KeyError"

    def test_taxonomy_skipped_when_include_error_taxonomy_false(self) -> None:
        """Taxonomy should not be added when slo.include_error_taxonomy is False."""
        config = TelemetryConfig.from_env({"UNDEF_SLO_INCLUDE_ERROR_TAXONOMY": "false"})
        processor = add_standard_fields(config)
        event_dict: dict[str, object] = {
            "event": "app.error.occurred",
            "exc_name": "ValueError",
        }
        result = processor(None, "", event_dict)
        assert "error_type" not in result


# ── apply_sampling: signal, key names, dropped event ─────────────────


class TestApplySamplingMutants:
    def test_signal_is_logs(self) -> None:
        """Kills: 'logs' → 'XXlogsXX' in should_sample call."""
        with patch(
            "undef.telemetry.logger.processors.should_sample",
            return_value=True,
        ) as mock_sample:
            apply_sampling(None, "", {"event": "app.test.ok"})
        mock_sample.assert_called_once_with("logs", "app.test.ok")

    def test_event_key_read_correctly(self) -> None:
        """Kills: 'event' key → 'XXeventXX'."""
        with patch(
            "undef.telemetry.logger.processors.should_sample",
            return_value=True,
        ) as mock_sample:
            apply_sampling(None, "", {"event": "my.specific.event"})
        mock_sample.assert_called_once_with("logs", "my.specific.event")

    def test_dropped_event_raises_drop_event(self) -> None:
        """When sampling rejects, DropEvent is raised to suppress the log."""
        with (
            patch(
                "undef.telemetry.logger.processors.should_sample",
                return_value=False,
            ),
            pytest.raises(structlog.DropEvent),
        ):
            apply_sampling(None, "", {"event": "app.test.ok"})

    def test_sampled_event_passes_through(self) -> None:
        """When sampled, original event_dict is returned unchanged."""
        original: dict[str, object] = {"event": "app.test.ok", "extra": "data"}
        with patch(
            "undef.telemetry.logger.processors.should_sample",
            return_value=True,
        ):
            result = apply_sampling(None, "", original)
        assert result is original


# ── enforce_event_schema: strict_event_name=True when strict_schema ──


class TestEnforceEventSchemaMutants:
    def test_strict_schema_forces_strict_event_name_true(self) -> None:
        """Kills: strict_event_name=True → strict_event_name=False."""
        config = TelemetryConfig.from_env({"UNDEF_TELEMETRY_STRICT_SCHEMA": "true"})
        processor = enforce_event_schema(config)
        # A non-dotted name should fail when strict_event_name is True
        with patch(
            "undef.telemetry.logger.processors.validate_event_name",
        ) as mock_validate:
            processor(None, "", {"event": "app.test.ok"})
        mock_validate.assert_called_once_with("app.test.ok", strict_event_name=True)

    def test_non_strict_schema_uses_config_value(self) -> None:
        """When strict_schema=False, strict_event_name comes from event_schema config."""
        config = TelemetryConfig.from_env(
            {
                "UNDEF_TELEMETRY_STRICT_SCHEMA": "false",
                "UNDEF_TELEMETRY_STRICT_EVENT_NAME": "false",
            }
        )
        processor = enforce_event_schema(config)
        with patch(
            "undef.telemetry.logger.processors.validate_event_name",
        ) as mock_validate:
            processor(None, "", {"event": "anything"})
        mock_validate.assert_called_once_with("anything", strict_event_name=False)

    def test_required_keys_passed_when_strict(self) -> None:
        """Kills: required_keys mutations."""
        config = TelemetryConfig.from_env(
            {
                "UNDEF_TELEMETRY_STRICT_SCHEMA": "true",
                "UNDEF_TELEMETRY_REQUIRED_KEYS": "service,env",
            }
        )
        processor = enforce_event_schema(config)
        with (
            patch(
                "undef.telemetry.logger.processors.validate_event_name",
            ),
            patch(
                "undef.telemetry.logger.processors.validate_required_keys",
            ) as mock_req,
        ):
            event_dict: dict[str, object] = {"event": "app.test.ok", "service": "s", "env": "e"}
            processor(None, "", event_dict)
        mock_req.assert_called_once()
        actual_keys = mock_req.call_args[0][1]
        assert "service" in actual_keys
        assert "env" in actual_keys

    def test_required_keys_respected_when_not_strict(self) -> None:
        """When strict_schema=False, required_keys from config are still enforced."""
        config = TelemetryConfig.from_env(
            {
                "UNDEF_TELEMETRY_STRICT_SCHEMA": "false",
                "UNDEF_TELEMETRY_REQUIRED_KEYS": "service,env",
            }
        )
        processor = enforce_event_schema(config)
        with (
            patch(
                "undef.telemetry.logger.processors.validate_event_name",
            ),
            patch(
                "undef.telemetry.logger.processors.validate_required_keys",
            ) as mock_req,
        ):
            processor(None, "", {"event": "app.test.ok"})
        actual_keys = mock_req.call_args[0][1]
        assert "service" in actual_keys
        assert "env" in actual_keys
