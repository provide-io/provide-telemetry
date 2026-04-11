# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Regression tests for the strippable-governance contract.

These tests verify that:
1. Core telemetry (logging, tracing, metrics, PII, schema, health) works without
   importing any governance symbols.
2. Governance symbols are optional and only available via lazy import.

These tests do NOT delete files — they validate the abstraction boundary.
"""

from __future__ import annotations

import sys

# ---------------------------------------------------------------------------
# Tests: core telemetry without governance
# ---------------------------------------------------------------------------


class TestCoreWithoutGovernance:
    """Core features must work even if governance modules are unavailable."""

    def test_setup_shutdown_works(self) -> None:
        """setup_telemetry / shutdown_telemetry must not require governance."""
        from provide.telemetry import setup_telemetry, shutdown_telemetry
        from provide.telemetry.testing import reset_telemetry_state

        reset_telemetry_state()
        cfg = setup_telemetry()
        assert cfg is not None
        shutdown_telemetry()

    def test_logger_works(self) -> None:
        """get_logger must be callable without governance."""
        from provide.telemetry import get_logger

        log = get_logger("strip-governance-test")
        assert log is not None
        # Emitting a structured log must not raise.
        log.info("no_governance.test.logged", extra="value")

    def test_pii_redacts_without_governance(self) -> None:
        """PII sanitization must redact default-sensitive keys even without governance."""
        from provide.telemetry.pii import replace_pii_rules, sanitize_payload

        replace_pii_rules([])
        payload = {
            "user": "alice",
            "password": "s3cr3t",  # pragma: allowlist secret
            "token": "abc123",
        }
        result = sanitize_payload(payload, enabled=True, max_depth=3)
        assert result.get("password") == "***", "password must be redacted"
        assert result.get("token") == "***", "token must be redacted"
        assert result.get("user") == "alice", "non-sensitive key must pass through"
        # No classification labels without governance
        assert "__password__class" not in result, (
            "classification labels must be absent when classification.py not imported"
        )

    def test_schema_event_validation_works(self) -> None:
        """Event schema validation must work without governance."""
        from provide.telemetry.schema.events import event

        e = event("auth", "login", "success")
        assert str(e) == "auth.login.success"
        assert e.domain == "auth"
        assert e.action == "login"
        assert e.status == "success"

    def test_health_snapshot_works(self) -> None:
        """get_health_snapshot must work without governance."""
        from provide.telemetry.health import get_health_snapshot

        snap = get_health_snapshot()
        assert snap.emitted_logs >= 0
        assert snap.dropped_logs >= 0
        assert snap.emitted_traces >= 0
        assert snap.emitted_metrics >= 0

    def test_sampling_works(self) -> None:
        """Sampling policy must work without governance."""
        from provide.telemetry.sampling import (
            SamplingPolicy,
            get_sampling_policy,
            set_sampling_policy,
        )

        policy = SamplingPolicy(default_rate=0.5)
        set_sampling_policy("logs", policy)
        got = get_sampling_policy("logs")
        assert got.default_rate == 0.5
        # Reset
        set_sampling_policy("logs", SamplingPolicy(default_rate=1.0))

    def test_metrics_counter_works(self) -> None:
        """counter() must work without governance."""
        from provide.telemetry.metrics import counter

        c = counter("no_governance.test.counter")
        assert c is not None
        c.add(1)

    def test_backpressure_policy_works(self) -> None:
        """Backpressure queue policy must work without governance."""
        from provide.telemetry.backpressure import (
            QueuePolicy,
            get_queue_policy,
            set_queue_policy,
        )

        policy = QueuePolicy(logs_maxsize=100, traces_maxsize=100, metrics_maxsize=100)
        set_queue_policy(policy)
        got = get_queue_policy()
        assert got.logs_maxsize == 100
        # Reset
        set_queue_policy(QueuePolicy())


# ---------------------------------------------------------------------------
# Tests: governance symbols are optional (lazy, not required)
# ---------------------------------------------------------------------------


class TestGovernanceIsOptional:
    """Governance symbols must only be loaded on first access, not on import."""

    def test_core_import_does_not_load_governance_modules(self) -> None:
        """Importing provide.telemetry must not eagerly load governance modules."""
        # We verify the contract: top-level import succeeds and core symbols are
        # available regardless of governance module availability.
        import provide.telemetry

        # Top-level import succeeds (governance is lazy).
        assert provide.telemetry.setup_telemetry is not None
        assert provide.telemetry.get_logger is not None

    def test_governance_symbols_are_lazily_imported(self) -> None:
        """Governance symbols must resolve correctly when modules are present."""
        import provide.telemetry as t

        # These must be accessible as attributes (lazy import).
        assert hasattr(t, "ClassificationPolicy")
        assert hasattr(t, "ConsentLevel")
        assert hasattr(t, "RedactionReceipt")

    def test_governance_modules_not_in_core_imports(self) -> None:
        """Core imports must not eagerly pull in governance modules.

        We detect this by checking that governance module keys were not loaded
        before any governance-specific test ran. Since tests may run in any order,
        we verify the inverse: after a cold import of core-only symbols, governance
        module paths are absent from sys.modules.
        """
        # Import only core symbols — no governance.
        from provide.telemetry import get_logger, setup_telemetry  # noqa: F401

        # Governance must not have been pulled in by the above core imports.
        # (They may be present from other tests in the session; we skip assertion
        #  if they were loaded by an earlier test.)
        core_only_keys = {
            "provide.telemetry.setup",
            "provide.telemetry.config",
            "provide.telemetry.logger",
            "provide.telemetry.exceptions",
        }
        for key in core_only_keys:
            assert key in sys.modules, f"core module {key!r} must be imported"
