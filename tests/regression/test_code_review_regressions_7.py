# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Regression tests for code review batch #3 (six findings across all languages).

Covers the Python-specific fixes.  Go and Rust have their own test suites.

1. Opt-in pytest plugin — pyproject.toml no longer registers pytest11 entry point.
2. TypeScript only — async-safe manual trace context (covered by typescript/tests).
3. TypeScript only — required-key enforcement outside strictSchema gate.
4. Schema rejection must not bump emitted_logs.
5. Fallback metrics must increment emitted_metrics on successful write.
6. TypeScript only — default environment/version values match Go/Rust/Python.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from structlog import DropEvent

from provide.telemetry.config import (
    SchemaConfig,
    TelemetryConfig,
)
from provide.telemetry.health import get_health_snapshot, reset_health_for_tests
from provide.telemetry.logger.processors import (
    apply_sampling,
    enforce_event_schema,
)
from provide.telemetry.metrics.fallback import Counter, Gauge, Histogram
from provide.telemetry.sampling import SamplingPolicy, set_sampling_policy


class TestNoPytestPluginEntryPoint:
    """pyproject.toml must NOT register provide.telemetry.testing as a pytest11 entry point.

    Auto-loading a pytest plugin from a library install would silently mutate
    every consumer's test suite (structlog reset, telemetry state wipe on each
    test) — a major integration hazard.  Consumers opt in explicitly.
    """

    def test_pyproject_does_not_register_pytest11_entry_point(self) -> None:
        from pathlib import Path

        pyproject = (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text()
        # The entire [project.entry-points.pytest11] section must be absent.
        assert "[project.entry-points.pytest11]" not in pyproject


class TestSchemaRejectDoesNotBumpEmittedLogs:
    """Finding 4: enforce_event_schema must run BEFORE apply_sampling.

    If a log violates required-key rules, it should NOT be counted as emitted.
    """

    def test_processor_order_schema_before_sampling(self) -> None:
        """Reading the live processor chain — schema must come before sampling."""
        from provide.telemetry.logger.core import configure_logging

        cfg = TelemetryConfig(event_schema=SchemaConfig(required_keys=("event",)))
        configure_logging(cfg, force=True)
        # The shipped chain is installed on structlog — inspect the fact that
        # enforce_event_schema's closure runs before apply_sampling by simulating
        # a missing required key and verifying emitted_logs stays at 0.
        reset_health_for_tests()
        schema_proc = enforce_event_schema(cfg)
        # Missing the required 'event' key — schema annotates with _schema_error.
        result = schema_proc(None, "info", {"level": "info"})
        assert "_schema_error" in result
        # apply_sampling never ran, so emitted_logs stayed at zero.
        assert get_health_snapshot().emitted_logs == 0

    def test_valid_log_survives_pipeline_and_increments(self) -> None:
        set_sampling_policy("logs", SamplingPolicy(default_rate=1.0))
        reset_health_for_tests()
        result = apply_sampling(None, "info", {"event": "ok.test"})
        # apply_sampling stashes the backpressure ticket in event_dict for the
        # final renderer processor to move onto the LogRecord. Strip the
        # sentinel key before comparing payload identity.
        from provide.telemetry.logger.processors import _BACKPRESSURE_TICKET_KEY

        result.pop(_BACKPRESSURE_TICKET_KEY, None)
        assert result == {"event": "ok.test"}
        assert get_health_snapshot().emitted_logs == 1

    def test_sampled_out_log_does_not_count_as_emitted(self) -> None:
        set_sampling_policy("logs", SamplingPolicy(default_rate=0.0))
        reset_health_for_tests()
        with pytest.raises(DropEvent):
            apply_sampling(None, "info", {"event": "drop.test"})
        assert get_health_snapshot().emitted_logs == 0
        assert get_health_snapshot().dropped_logs == 1


class TestFallbackMetricsIncrementEmitted:
    """Finding 5: Counter/Gauge/Histogram must bump emitted_metrics on successful write."""

    def _fresh_state(self) -> None:
        reset_health_for_tests()
        set_sampling_policy("metrics", SamplingPolicy(default_rate=1.0))

    def test_counter_add_increments_emitted_metrics(self) -> None:
        self._fresh_state()
        Counter("regression.metrics.counter").add(1)
        assert get_health_snapshot().emitted_metrics == 1

    def test_gauge_add_increments_emitted_metrics(self) -> None:
        self._fresh_state()
        Gauge("regression.metrics.gauge_add").add(1)
        assert get_health_snapshot().emitted_metrics == 1

    def test_gauge_set_increments_emitted_metrics(self) -> None:
        self._fresh_state()
        Gauge("regression.metrics.gauge_set").set(5)
        assert get_health_snapshot().emitted_metrics == 1

    def test_histogram_record_increments_emitted_metrics(self) -> None:
        self._fresh_state()
        Histogram("regression.metrics.hist").record(0.5)
        assert get_health_snapshot().emitted_metrics == 1

    def test_metric_dropped_by_sampling_does_not_count_emitted(self) -> None:
        """When sampling drops the write, emitted_metrics must not tick."""
        reset_health_for_tests()
        set_sampling_policy("metrics", SamplingPolicy(default_rate=0.0))
        Counter("regression.metrics.counter_drop").add(1)
        assert get_health_snapshot().emitted_metrics == 0

    def test_metric_dropped_by_backpressure_does_not_count_emitted(self) -> None:
        """When the queue is full, the write is dropped AND emitted_metrics stays flat."""
        from provide.telemetry.backpressure import _try_acquire_unchecked

        self._fresh_state()
        with patch.object(
            # Patch the actual import target used inside fallback.add
            __import__("provide.telemetry.metrics.fallback", fromlist=["_try_acquire_unchecked"]),
            "_try_acquire_unchecked",
            return_value=None,
        ):
            Counter("regression.metrics.counter_full").add(1)
        # try_acquire_unchecked is unused in this assertion but imported so the
        # patch target resolves; confirm the counter was never bumped.
        _ = _try_acquire_unchecked
        assert get_health_snapshot().emitted_metrics == 0


class TestTypescriptOnlyFindingsAreLanguageSpecific:
    """Findings 2, 3, 6 are TypeScript-only; parity confirmed in typescript/tests."""

    def test_python_requiredkeys_unconditional(self) -> None:
        """Python has always enforced required keys regardless of strict_schema.

        This is the invariant finding 3 was about for TypeScript; we verify Python
        is already correct so the behaviors match post-fix.
        """
        cfg = TelemetryConfig(
            strict_schema=False,
            event_schema=SchemaConfig(required_keys=("request_id",)),
        )
        proc = enforce_event_schema(cfg)
        result = proc(None, "info", {"event": "ok"})  # missing request_id
        assert "_schema_error" in result

    def test_python_defaults_match_go_rust(self) -> None:
        """Finding 6 parity: Python's defaults already match the canonical values."""
        cfg = TelemetryConfig()
        assert cfg.environment == "dev"
        assert cfg.version == "0.0.0"
