# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Regression tests for code review batch #4 (three cross-language findings).

1. Consent not enforced — consent checks now gating all signal hot paths.
2. PROVIDE_TRACE_SAMPLE_RATE inert — now wired via min() with sampling.traces_rate.
3. Log backpressure missing — try_acquire("logs") now in apply_sampling.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import structlog

from provide.telemetry.consent import ConsentLevel, set_consent_level
from provide.telemetry.health import get_health_snapshot, reset_health_for_tests
from provide.telemetry.logger.processors import apply_sampling
from provide.telemetry.metrics.fallback import Counter, Gauge, Histogram
from provide.telemetry.sampling import SamplingPolicy, set_sampling_policy


class TestConsentBlocksLogs:
    """Finding 1: consent=NONE must drop log records before emitting."""

    def test_apply_sampling_drops_when_consent_none(self) -> None:
        set_consent_level(ConsentLevel.NONE)
        reset_health_for_tests()
        with pytest.raises(structlog.DropEvent):
            apply_sampling(None, "info", {"event": "test.consent.none"})
        assert get_health_snapshot().emitted_logs == 0

    def test_apply_sampling_drops_debug_at_functional_consent(self) -> None:
        set_consent_level(ConsentLevel.FUNCTIONAL)
        reset_health_for_tests()
        # FUNCTIONAL only allows WARNING and above for logs
        with pytest.raises(structlog.DropEvent):
            apply_sampling(None, "debug", {"event": "test.consent.functional.debug"})
        assert get_health_snapshot().emitted_logs == 0

    def test_apply_sampling_allows_warning_at_functional_consent(self) -> None:
        from provide.telemetry.logger.processors import _BACKPRESSURE_TICKET_KEY

        set_consent_level(ConsentLevel.FUNCTIONAL)
        set_sampling_policy("logs", SamplingPolicy(default_rate=1.0))
        reset_health_for_tests()
        result = apply_sampling(None, "warning", {"event": "test.consent.functional.warn"})
        # apply_sampling now stashes a backpressure ticket — strip it for comparison.
        result.pop(_BACKPRESSURE_TICKET_KEY, None)
        assert result == {"event": "test.consent.functional.warn"}
        assert get_health_snapshot().emitted_logs == 1

    def test_apply_sampling_allows_full_consent(self) -> None:
        from provide.telemetry.logger.processors import _BACKPRESSURE_TICKET_KEY

        set_consent_level(ConsentLevel.FULL)
        set_sampling_policy("logs", SamplingPolicy(default_rate=1.0))
        reset_health_for_tests()
        result = apply_sampling(None, "info", {"event": "test.consent.full"})
        result.pop(_BACKPRESSURE_TICKET_KEY, None)
        assert result == {"event": "test.consent.full"}
        assert get_health_snapshot().emitted_logs == 1


class TestConsentBlocksMetrics:
    """Finding 1: consent=NONE must block metric writes."""

    def test_counter_add_blocked_by_consent_none(self) -> None:
        set_consent_level(ConsentLevel.NONE)
        set_sampling_policy("metrics", SamplingPolicy(default_rate=1.0))
        reset_health_for_tests()
        c = Counter("regression.consent.counter")
        c.add(1)
        assert c.value == 0
        assert get_health_snapshot().emitted_metrics == 0

    def test_gauge_add_blocked_by_consent_none(self) -> None:
        set_consent_level(ConsentLevel.NONE)
        set_sampling_policy("metrics", SamplingPolicy(default_rate=1.0))
        reset_health_for_tests()
        g = Gauge("regression.consent.gauge_add")
        g.add(5)
        assert g.value == 0
        assert get_health_snapshot().emitted_metrics == 0

    def test_gauge_set_blocked_by_consent_none(self) -> None:
        set_consent_level(ConsentLevel.NONE)
        set_sampling_policy("metrics", SamplingPolicy(default_rate=1.0))
        reset_health_for_tests()
        g = Gauge("regression.consent.gauge_set")
        g.set(10)
        assert g.value == 0
        assert get_health_snapshot().emitted_metrics == 0

    def test_histogram_record_blocked_by_consent_none(self) -> None:
        set_consent_level(ConsentLevel.NONE)
        set_sampling_policy("metrics", SamplingPolicy(default_rate=1.0))
        reset_health_for_tests()
        h = Histogram("regression.consent.histogram")
        h.record(0.5)
        assert h.count == 0
        assert get_health_snapshot().emitted_metrics == 0

    def test_minimal_consent_blocks_metrics(self) -> None:
        set_consent_level(ConsentLevel.MINIMAL)
        set_sampling_policy("metrics", SamplingPolicy(default_rate=1.0))
        reset_health_for_tests()
        Counter("regression.consent.minimal").add(1)
        assert get_health_snapshot().emitted_metrics == 0


class TestConsentBlocksTraces:
    """Finding 1: consent=NONE must bypass span creation in @trace decorator."""

    def test_sync_trace_bypasses_span_when_consent_none(self) -> None:
        from provide.telemetry.tracing.decorators import trace

        set_consent_level(ConsentLevel.NONE)
        reset_health_for_tests()

        @trace()
        def inner() -> str:
            return "result"

        assert inner() == "result"
        assert get_health_snapshot().emitted_traces == 0

    async def test_async_trace_bypasses_span_when_consent_none(self) -> None:
        from provide.telemetry.tracing.decorators import trace

        set_consent_level(ConsentLevel.NONE)
        reset_health_for_tests()

        @trace()
        async def inner() -> str:
            return "async_result"

        assert await inner() == "async_result"
        assert get_health_snapshot().emitted_traces == 0

    def test_minimal_consent_blocks_traces(self) -> None:
        from provide.telemetry.tracing.decorators import trace

        set_consent_level(ConsentLevel.MINIMAL)
        reset_health_for_tests()

        @trace()
        def inner() -> int:
            return 42

        assert inner() == 42
        assert get_health_snapshot().emitted_traces == 0


class TestLogBackpressure:
    """Finding 3: try_acquire('logs') now gates apply_sampling."""

    def test_apply_sampling_drops_when_log_queue_full(self) -> None:
        """apply_sampling must raise DropEvent when try_acquire returns None."""
        import provide.telemetry.backpressure as _bp

        set_sampling_policy("logs", SamplingPolicy(default_rate=1.0))
        reset_health_for_tests()
        # Simulate a full log queue by having try_acquire return None.
        with patch.object(_bp, "try_acquire", return_value=None), pytest.raises(structlog.DropEvent):
            apply_sampling(None, "info", {"event": "backpressure.test"})
        assert get_health_snapshot().emitted_logs == 0

    def test_apply_sampling_succeeds_with_unlimited_queue(self) -> None:
        from provide.telemetry.logger.processors import _BACKPRESSURE_TICKET_KEY

        set_sampling_policy("logs", SamplingPolicy(default_rate=1.0))
        reset_health_for_tests()
        result = apply_sampling(None, "info", {"event": "unlimited.log"})
        result.pop(_BACKPRESSURE_TICKET_KEY, None)
        assert result == {"event": "unlimited.log"}
        assert get_health_snapshot().emitted_logs == 1


class TestTraceSampleRateWired:
    """Finding 2: PROVIDE_TRACE_SAMPLE_RATE must now influence trace sampling."""

    def test_trace_sample_rate_applied_via_min(self) -> None:
        """When tracing.sample_rate < sampling.traces_rate, the lower value wins."""
        from provide.telemetry.config import TelemetryConfig, TracingConfig
        from provide.telemetry.runtime import apply_runtime_config
        from provide.telemetry.sampling import get_sampling_policy

        # sampling.traces_rate=1.0 (default), tracing.sample_rate=0.0
        # min(1.0, 0.0) == 0.0 → traces always dropped
        cfg = TelemetryConfig(tracing=TracingConfig(sample_rate=0.0))
        apply_runtime_config(cfg)
        policy = get_sampling_policy("traces")
        assert policy.default_rate == 0.0

    def test_sampling_traces_rate_wins_when_lower(self) -> None:
        """sampling.traces_rate beats tracing.sample_rate when it is lower."""
        from provide.telemetry.config import SamplingConfig, TelemetryConfig, TracingConfig
        from provide.telemetry.runtime import apply_runtime_config
        from provide.telemetry.sampling import get_sampling_policy

        cfg = TelemetryConfig(
            tracing=TracingConfig(sample_rate=1.0),
            sampling=SamplingConfig(traces_rate=0.25),
        )
        apply_runtime_config(cfg)
        policy = get_sampling_policy("traces")
        assert policy.default_rate == 0.25

    def test_both_default_gives_rate_one(self) -> None:
        """When both are at their defaults (1.0), effective rate is 1.0."""
        from provide.telemetry.config import TelemetryConfig
        from provide.telemetry.runtime import apply_runtime_config
        from provide.telemetry.sampling import get_sampling_policy

        apply_runtime_config(TelemetryConfig())
        policy = get_sampling_policy("traces")
        assert policy.default_rate == 1.0
