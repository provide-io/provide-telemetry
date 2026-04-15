# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Regression tests for code review fixes F1-F6."""

from __future__ import annotations

from typing import Any

import pytest

from provide.telemetry import pii as pii_mod
from provide.telemetry import runtime as runtime_mod
from provide.telemetry.classification import (
    ClassificationPolicy,
    ClassificationRule,
    DataClass,
    _reset_classification_for_tests,
    register_classification_rules,
    set_classification_policy,
)
from provide.telemetry.config import RuntimeOverrides, SecurityConfig, SLOConfig, TelemetryConfig
from provide.telemetry.pii import (
    PIIRule,
    _apply_default_sensitive_key_redaction,
    _collect_rule_paths,
    _path_has_rule,
    replace_pii_rules,
    sanitize_payload,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    pii_mod.reset_pii_rules_for_tests()
    _reset_classification_for_tests()
    runtime_mod.reset_runtime_for_tests()
    from provide.telemetry import backpressure as backpressure_mod
    from provide.telemetry import resilience as resilience_mod
    from provide.telemetry import sampling as sampling_mod

    sampling_mod.reset_sampling_for_tests()
    backpressure_mod.reset_queues_for_tests()
    resilience_mod.reset_resilience_for_tests()


# ── F1: path-aware default redaction skip ────────────────────────────────────


class TestF1PathAwareDefaultRedactionSkip:
    """F1: custom rule for nested path must not block default redaction of unrelated top-level key."""

    def test_custom_nested_rule_does_not_suppress_top_level_password(self) -> None:
        """A custom rule for ('user', 'password') must NOT prevent default redaction of top-level password."""
        replace_pii_rules([PIIRule(path=("user", "password"), mode="hash")])
        payload = {"password": "top-level-secret", "user": {"password": "nested"}}  # pragma: allowlist secret
        result = sanitize_payload(payload, enabled=True)
        # Top-level password NOT covered by the custom rule path, so default redaction applies
        assert result["password"] == "***"
        # Nested user.password IS covered by the custom rule (hash mode)
        assert result["user"]["password"] != "top-level-secret"  # pragma: allowlist secret
        assert result["user"]["password"] != "***"  # hash, not redact

    def test_collect_rule_paths_returns_full_paths(self) -> None:
        """_collect_rule_paths must return full paths, not just leaf keys."""
        rules = (
            PIIRule(path=("user", "password")),
            PIIRule(path=("token",)),
        )
        paths = _collect_rule_paths(rules)
        assert ("user", "password") in paths
        assert ("token",) in paths
        # Must NOT contain partial paths or just leaf keys
        assert ("password",) not in paths

    def test_path_has_rule_exact_match(self) -> None:
        """_path_has_rule returns True for exact match."""
        rule_paths: frozenset[tuple[str, ...]] = frozenset({("user", "password")})
        assert _path_has_rule(rule_paths, ("user", "password")) is True

    def test_path_has_rule_no_match(self) -> None:
        """_path_has_rule returns False when child_path not in rule_paths."""
        rule_paths: frozenset[tuple[str, ...]] = frozenset({("user", "password")})
        assert _path_has_rule(rule_paths, ("password",)) is False

    def test_path_has_rule_wildcard_match(self) -> None:
        """_path_has_rule supports wildcard segments."""
        rule_paths: frozenset[tuple[str, ...]] = frozenset({("items", "*", "token")})
        assert _path_has_rule(rule_paths, ("items", "0", "token")) is True
        assert _path_has_rule(rule_paths, ("items", "anything", "token")) is True
        assert _path_has_rule(rule_paths, ("items", "token")) is False

    def test_list_item_rule_prevents_default_redaction_of_token(self) -> None:
        """A wildcard rule for list items suppresses default redaction inside those items."""
        replace_pii_rules([PIIRule(path=("items", "*", "token"), mode="truncate", truncate_to=100)])
        payload: dict[str, Any] = {"items": [{"token": "short"}]}
        result = sanitize_payload(payload, enabled=True)
        assert result["items"][0]["token"] == "short"

    def test_apply_default_with_rule_targeted_paths_kwarg(self) -> None:
        """rule_targeted_paths kwarg prevents redaction of covered path."""
        node: dict[str, Any] = {"password": "secret"}
        rule_paths: frozenset[tuple[str, ...]] = frozenset({("password",)})
        result = _apply_default_sensitive_key_redaction(node, node, rule_targeted_paths=rule_paths)
        assert result["password"] == "secret"  # not redacted: covered by rule  # pragma: allowlist secret

    def test_apply_default_without_rule_targeted_paths_redacts(self) -> None:
        """With empty rule_targeted_paths, default redaction applies to sensitive keys."""
        node: dict[str, Any] = {"password": "secret"}
        result = _apply_default_sensitive_key_redaction(node, node, rule_targeted_paths=frozenset())
        assert result["password"] == "***"


# ── F2: logging as hot-reloadable field ──────────────────────────────────────


# ── F3: processor closures read live config ───────────────────────────────────


class TestF3ProcessorLiveConfig:
    """F3: processor closures must reflect updated runtime config."""

    def test_harden_input_reads_live_security_max_value_length(self) -> None:
        from provide.telemetry.logger.processors import harden_input

        cfg = TelemetryConfig()
        runtime_mod.apply_runtime_config(cfg)
        proc = harden_input(max_value_length=1024, max_attr_count=64, max_depth=8)
        # Change max_attr_value_length via runtime
        runtime_mod.update_runtime_config(RuntimeOverrides(security=SecurityConfig(max_attr_value_length=5)))
        result = proc(None, "", {"event": "x", "key": "hello!"})  # 6 chars
        assert result["key"] == "hello"  # truncated to 5

    def test_harden_input_falls_back_when_no_active_config(self) -> None:
        """When _active_config is None, factory-captured values are used."""
        from provide.telemetry.logger.processors import harden_input

        # Ensure no active config
        runtime_mod.reset_runtime_for_tests()
        proc = harden_input(max_value_length=5, max_attr_count=0, max_depth=8)
        result = proc(None, "", {"event": "x", "key": "hello!"})
        assert result["key"] == "hello"  # truncated to factory value 5

    def test_sanitize_sensitive_fields_reads_live_pii_max_depth(self) -> None:
        from provide.telemetry.logger.processors import sanitize_sensitive_fields

        cfg = TelemetryConfig(pii_max_depth=8)
        runtime_mod.apply_runtime_config(cfg)
        proc = sanitize_sensitive_fields(enabled=True, max_depth=8)
        # Update pii_max_depth at runtime
        runtime_mod.update_runtime_config(RuntimeOverrides(pii_max_depth=1))
        # At depth=1, nested keys should NOT be redacted
        payload: dict[str, Any] = {"event": "x", "outer": {"password": "secret"}}
        result = proc(None, "", payload)
        # With max_depth=1, depth limit prevents redacting nested 'password'
        assert result["outer"]["password"] == "secret"  # pragma: allowlist secret

    def test_sanitize_sensitive_fields_falls_back_when_no_active_config(self) -> None:
        """When _active_config is None, factory max_depth is used."""
        from provide.telemetry.logger.processors import sanitize_sensitive_fields

        runtime_mod.reset_runtime_for_tests()
        proc = sanitize_sensitive_fields(enabled=True, max_depth=1)
        # With depth=1, nested password NOT redacted
        payload: dict[str, Any] = {"event": "x", "outer": {"password": "secret"}}
        result = proc(None, "", payload)
        assert result["outer"]["password"] == "secret"  # pragma: allowlist secret

    def test_enforce_event_schema_reads_live_strict_schema(self) -> None:
        from provide.telemetry.logger.processors import enforce_event_schema

        cfg = TelemetryConfig(strict_schema=False)
        runtime_mod.apply_runtime_config(cfg)
        proc = enforce_event_schema(cfg)
        # Enable strict via runtime
        runtime_mod.update_runtime_config(RuntimeOverrides(strict_schema=True))
        result = proc(None, "", {"event": "bad event name"})
        assert "_schema_error" in result
        assert "invalid event name" in result["_schema_error"]

    def test_add_standard_fields_reads_live_slo_include_error_taxonomy(self) -> None:
        from provide.telemetry.logger.processors import add_standard_fields

        cfg = TelemetryConfig()
        runtime_mod.apply_runtime_config(cfg)
        proc = add_standard_fields(cfg)
        # Disable error taxonomy at runtime
        runtime_mod.update_runtime_config(RuntimeOverrides(slo=SLOConfig(include_error_taxonomy=False)))
        event_dict: dict[str, Any] = {"event": "e", "exc_name": "ValueError"}
        result = proc(None, "", event_dict)
        assert "error_type" not in result


# ── F4: PROVIDE_TRACE/METRICS_ENABLED=false hard-disables ─────────────────────


class TestF4ExplicitlyDisabled:
    """F4: get_tracer/get_meter must return noop when explicitly disabled."""

    def test_get_tracer_returns_noop_when_tracing_disabled(self) -> None:
        from provide.telemetry.tracing.provider import _reset_tracing_for_tests, get_tracer, setup_tracing

        _reset_tracing_for_tests()
        cfg = TelemetryConfig.from_env({"PROVIDE_TRACE_ENABLED": "false"})
        setup_tracing(cfg)
        tracer = get_tracer()
        # Must return a noop tracer (no real OTel provider)
        from provide.telemetry.tracing.provider import _NoopTracer

        assert isinstance(tracer, _NoopTracer)
        _reset_tracing_for_tests()

    def test_tracing_explicitly_disabled_flag_set(self) -> None:
        from provide.telemetry.tracing import provider as tracing_provider

        tracing_provider._reset_tracing_for_tests()
        cfg = TelemetryConfig.from_env({"PROVIDE_TRACE_ENABLED": "false"})
        tracing_provider.setup_tracing(cfg)
        assert tracing_provider._tracing_explicitly_disabled is True
        tracing_provider._reset_tracing_for_tests()

    def test_tracing_explicitly_disabled_cleared_on_enabled(self) -> None:
        from provide.telemetry.tracing import provider as tracing_provider

        tracing_provider._reset_tracing_for_tests()
        # First disable
        tracing_provider.setup_tracing(TelemetryConfig.from_env({"PROVIDE_TRACE_ENABLED": "false"}))
        assert tracing_provider._tracing_explicitly_disabled is True
        tracing_provider._reset_tracing_for_tests()
        # Then enable
        tracing_provider.setup_tracing(TelemetryConfig.from_env({"PROVIDE_TRACE_ENABLED": "true"}))
        assert tracing_provider._tracing_explicitly_disabled is False
        tracing_provider._reset_tracing_for_tests()

    def test_metrics_explicitly_disabled_flag_set(self) -> None:
        from provide.telemetry.metrics import provider as metrics_provider

        metrics_provider._set_meter_for_test(None)
        cfg = TelemetryConfig.from_env({"PROVIDE_METRICS_ENABLED": "false"})
        metrics_provider.setup_metrics(cfg)
        assert metrics_provider._metrics_explicitly_disabled is True
        metrics_provider._set_meter_for_test(None)

    def test_get_meter_returns_none_when_metrics_disabled(self) -> None:
        from provide.telemetry.metrics import provider as metrics_provider

        metrics_provider._set_meter_for_test(None)
        cfg = TelemetryConfig.from_env({"PROVIDE_METRICS_ENABLED": "false"})
        metrics_provider.setup_metrics(cfg)
        meter = metrics_provider.get_meter()
        assert meter is None
        metrics_provider._set_meter_for_test(None)

    def test_metrics_explicitly_disabled_cleared_on_enabled(self) -> None:
        from provide.telemetry.metrics import provider as metrics_provider

        metrics_provider._set_meter_for_test(None)
        metrics_provider.setup_metrics(TelemetryConfig.from_env({"PROVIDE_METRICS_ENABLED": "false"}))
        assert metrics_provider._metrics_explicitly_disabled is True
        metrics_provider._set_meter_for_test(None)
        metrics_provider.setup_metrics(TelemetryConfig.from_env({"PROVIDE_METRICS_ENABLED": "true"}))
        assert metrics_provider._metrics_explicitly_disabled is False
        metrics_provider._set_meter_for_test(None)

    def test_reset_tracing_clears_explicitly_disabled(self) -> None:
        from provide.telemetry.tracing import provider as tracing_provider

        tracing_provider._tracing_explicitly_disabled = True
        tracing_provider._reset_tracing_for_tests()
        assert tracing_provider._tracing_explicitly_disabled is False

    def test_reset_meter_clears_explicitly_disabled(self) -> None:
        from provide.telemetry.metrics import provider as metrics_provider

        metrics_provider._metrics_explicitly_disabled = True
        metrics_provider._set_meter_for_test(None)
        assert metrics_provider._metrics_explicitly_disabled is False


# ── F5: ClassificationPolicy enforces actions ────────────────────────────────


class TestF5ClassificationPolicyEnforced:
    """F5: sanitize_payload must enforce drop/redact/hash from the classification policy."""

    def test_drop_action_removes_field_and_no_class_tag(self) -> None:
        register_classification_rules([ClassificationRule(pattern="dob", classification=DataClass.PHI)])
        # PHI default = "drop"
        result = sanitize_payload({"dob": "1990-01-01", "name": "Bob"}, enabled=True)
        assert "dob" not in result
        assert "__dob__class" not in result

    def test_redact_action_masks_value_and_adds_class_tag(self) -> None:
        register_classification_rules([ClassificationRule(pattern="email", classification=DataClass.PII)])
        # PII default = "redact"
        result = sanitize_payload({"email": "alice@example.com"}, enabled=True)
        assert result["email"] == "***"
        assert result["__email__class"] == "PII"

    def test_hash_action_hashes_value_and_adds_class_tag(self) -> None:
        register_classification_rules([ClassificationRule(pattern="card_num", classification=DataClass.PCI)])
        # PCI default = "hash"
        result = sanitize_payload({"card_num": "4111111111111111"}, enabled=True)
        assert result["card_num"] != "4111111111111111"
        assert result["card_num"] != "***"
        assert result["__card_num__class"] == "PCI"

    def test_pass_action_keeps_value_and_adds_class_tag(self) -> None:
        register_classification_rules([ClassificationRule(pattern="status", classification=DataClass.PUBLIC)])
        # PUBLIC default = "pass"
        result = sanitize_payload({"status": "ok"}, enabled=True)
        assert result["status"] == "ok"
        assert result["__status__class"] == "PUBLIC"

    def test_custom_policy_drop_removes_pii_field(self) -> None:
        register_classification_rules([ClassificationRule(pattern="email", classification=DataClass.PII)])
        set_classification_policy(ClassificationPolicy(PII="drop"))
        result = sanitize_payload({"email": "alice@example.com"}, enabled=True)
        assert "email" not in result
        assert "__email__class" not in result

    def test_custom_policy_redact_masks_phi_field(self) -> None:
        register_classification_rules([ClassificationRule(pattern="dob", classification=DataClass.PHI)])
        set_classification_policy(ClassificationPolicy(PHI="redact"))
        result = sanitize_payload({"dob": "1990-01-01"}, enabled=True)
        assert result["dob"] == "***"
        assert result["__dob__class"] == "PHI"

    def test_policy_hook_set_on_register_rules(self) -> None:
        register_classification_rules([ClassificationRule(pattern="x", classification=DataClass.PII)])
        assert pii_mod._policy_hook is not None

    def test_policy_hook_cleared_on_reset(self) -> None:
        register_classification_rules([ClassificationRule(pattern="x", classification=DataClass.PII)])
        _reset_classification_for_tests()
        assert pii_mod._policy_hook is None

    def test_no_double_masking_already_redacted_value(self) -> None:
        """F5: _REDACTED guard prevents double-masking."""
        replace_pii_rules([PIIRule(path=("email",), mode="redact")])
        register_classification_rules([ClassificationRule(pattern="email", classification=DataClass.PII)])
        # PII default = "redact" — but value is already "***" from the PII rule
        result = sanitize_payload({"email": "alice@example.com"}, enabled=True)
        assert result["email"] == "***"


# ── F6: receipt_hook uses full dotted path ───────────────────────────────────


class TestF6ReceiptHookDottedPath:
    """F6: receipt_hook receives dotted full path for dict key redactions."""

    def test_top_level_key_path_is_just_key(self) -> None:
        receipts: list[str] = []

        def hook(path: str, mode: str, value: object) -> None:
            receipts.append(path)

        node: dict[str, Any] = {"password": "secret"}
        _apply_default_sensitive_key_redaction(node, node, receipt_hook=hook)
        assert "password" in receipts

    def test_nested_key_path_is_dotted(self) -> None:
        receipts: list[str] = []

        def hook(path: str, mode: str, value: object) -> None:
            receipts.append(path)

        node: dict[str, Any] = {"outer": {"token": "val"}}
        _apply_default_sensitive_key_redaction(node, node, receipt_hook=hook)
        assert "outer.token" in receipts

    def test_list_item_path_stays_as_list_item_literal(self) -> None:
        """List items that are secrets use '(list_item)' key."""
        receipts: list[str] = []

        def hook(path: str, mode: str, value: object) -> None:
            receipts.append(path)

        secret = "a" * 40  # matches long_hex pattern
        _apply_default_sensitive_key_redaction([secret], [secret], receipt_hook=hook)
        assert "(list_item)" in receipts

    def test_nested_key_in_list_item_uses_wildcard_dotted_path(self) -> None:
        """Dict keys inside list items use '*.key' dotted path."""
        receipts: list[str] = []

        def hook(path: str, mode: str, value: object) -> None:
            receipts.append(path)

        node = [{"password": "secret"}]  # pragma: allowlist secret
        _apply_default_sensitive_key_redaction(node, node, receipt_hook=hook)
        assert "*.password" in receipts

    def test_receipts_integration_uses_dotted_path(self) -> None:
        """Receipts module receives full dotted path via the receipt_hook."""
        from provide.telemetry.receipts import (
            _reset_receipts_for_tests,
            enable_receipts,
            get_emitted_receipts_for_tests,
        )

        _reset_receipts_for_tests()
        enable_receipts(enabled=True, signing_key=None, service_name="test-svc")
        sanitize_payload({"outer": {"password": "s3cr3t"}}, enabled=True)  # pragma: allowlist secret
        receipts = get_emitted_receipts_for_tests()
        assert any(r.field_path == "outer.password" for r in receipts)
        _reset_receipts_for_tests()


# ── Review #2: Python-only parity fixes ───────────────────────────────────────


class TestLoggingIsColdReloadOnly:
    """Logging must be cold-reload (matches docs and Go/Rust/TS behavior)."""

    def test_runtime_overrides_has_no_logging_field(self) -> None:
        """RuntimeOverrides must NOT expose logging — prevents provider leak."""
        assert not hasattr(RuntimeOverrides(), "logging")


class TestFallbackMetricsRetryAfterSetup:
    """Counter/Gauge/Histogram must retry _resolve_otel after setup installs meter."""

    def test_counter_retries_after_meter_becomes_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from unittest.mock import Mock

        from provide.telemetry.metrics.fallback import Counter

        c = Counter("test.lazy.counter")
        # 1st call: no meter
        monkeypatch.setattr("provide.telemetry.metrics.provider.get_meter", lambda: None)
        assert c._resolve_otel() is None
        assert c._resolved is False  # critical: must stay False to allow retry
        # 2nd call: meter now available — must successfully re-bind
        fake_meter = Mock()
        fake_meter.create_counter.return_value = "otel-counter"
        monkeypatch.setattr("provide.telemetry.metrics.provider.get_meter", lambda: fake_meter)
        assert c._resolve_otel() == "otel-counter"
        assert c._resolved is True


class TestExecutorSaturationRaises:
    """Saturation must raise ExecutorSaturated so fail_open=False propagates."""

    def test_saturation_raises_executor_saturated(self) -> None:
        from provide.telemetry import resilience as resilience_mod
        from provide.telemetry.resilience import ExecutorSaturated, _get_executor_semaphore, _run_attempt_with_timeout

        sem = _get_executor_semaphore("logs")
        permits = [sem.acquire(blocking=False) for _ in range(resilience_mod._EXECUTOR_MAX_PENDING)]
        try:
            with pytest.raises(ExecutorSaturated):
                _run_attempt_with_timeout("logs", lambda: "unreachable", timeout_seconds=5.0)
        finally:
            for ok in permits:
                if ok:
                    sem.release()


class TestLazyGetLoggerAppliesSampling:
    """get_logger() lazy-init must apply the logs sampling policy from env."""

    def test_lazy_get_logger_installs_logs_sampling_rate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from provide.telemetry.logger import core as logger_core
        from provide.telemetry.sampling import get_sampling_policy

        monkeypatch.setenv("PROVIDE_SAMPLING_LOGS_RATE", "0.25")
        logger_core._reset_logging_for_tests()
        try:
            logger_core.get_logger("lazy-test")
            assert get_sampling_policy("logs").default_rate == 0.25
        finally:
            logger_core._reset_logging_for_tests()

    def test_lazy_get_logger_does_not_touch_exporter_policy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Narrow fix: must NOT overwrite exporter policy — that belongs to setup_telemetry."""
        from provide.telemetry import resilience as resilience_mod_local
        from provide.telemetry.logger import core as logger_core

        logger_core._reset_logging_for_tests()
        # Install a custom exporter policy; lazy get_logger must not clobber it.
        custom = resilience_mod_local.ExporterPolicy(retries=7, backoff_seconds=3.14, fail_open=False)
        resilience_mod_local.set_exporter_policy("logs", custom)
        try:
            logger_core.get_logger("lazy-test-2")
            assert resilience_mod_local.get_exporter_policy("logs").retries == 7
        finally:
            logger_core._reset_logging_for_tests()
