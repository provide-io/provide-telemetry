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
from provide.telemetry.config import LoggingConfig, RuntimeOverrides, SecurityConfig, SLOConfig, TelemetryConfig
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


class TestF2LoggingHotReload:
    """F2: logging config must be a hot-reloadable field in RuntimeOverrides."""

    def test_runtime_overrides_accepts_logging_field(self) -> None:
        overrides = RuntimeOverrides(logging=LoggingConfig(level="DEBUG"))
        assert overrides.logging is not None
        assert overrides.logging.level == "DEBUG"

    def test_runtime_overrides_logging_defaults_to_none(self) -> None:
        overrides = RuntimeOverrides()
        assert overrides.logging is None

    def test_overrides_from_config_includes_logging(self) -> None:
        """_overrides_from_config must extract logging from full TelemetryConfig."""
        cfg = TelemetryConfig(logging=LoggingConfig(level="WARNING"))
        overrides = runtime_mod._overrides_from_config(cfg)
        assert overrides.logging is not None
        assert overrides.logging.level == "WARNING"

    def test_apply_overrides_merges_logging(self) -> None:
        """_apply_overrides must merge logging when set."""
        base = TelemetryConfig(logging=LoggingConfig(level="INFO"))
        overrides = RuntimeOverrides(logging=LoggingConfig(level="DEBUG"))
        merged = runtime_mod._apply_overrides(base, overrides)
        assert merged.logging.level == "DEBUG"

    def test_apply_overrides_preserves_logging_when_not_set(self) -> None:
        """_apply_overrides must keep base logging when override.logging is None."""
        base = TelemetryConfig(logging=LoggingConfig(level="ERROR"))
        overrides = RuntimeOverrides()  # logging=None
        merged = runtime_mod._apply_overrides(base, overrides)
        assert merged.logging.level == "ERROR"

    def test_update_runtime_config_with_logging_calls_configure(self) -> None:
        """update_runtime_config triggers configure_logging(force=True) when logging is set."""
        import importlib

        logger_core = importlib.import_module("provide.telemetry.logger.core")
        calls: list[tuple[object, bool]] = []
        original = logger_core.configure_logging

        def _spy(cfg: object, *, force: bool = False) -> None:
            calls.append((cfg, force))

        logger_core.configure_logging = _spy  # type: ignore[attr-defined]
        try:
            overrides = RuntimeOverrides(logging=LoggingConfig(level="DEBUG"))
            runtime_mod.update_runtime_config(overrides)
        finally:
            logger_core.configure_logging = original  # type: ignore[attr-defined]

        assert len(calls) == 1
        assert calls[0][1] is True  # force=True

    def test_update_runtime_config_without_logging_skips_configure(self) -> None:
        """update_runtime_config does NOT call configure_logging when logging is None."""
        import importlib

        logger_core = importlib.import_module("provide.telemetry.logger.core")
        calls: list[tuple[object, bool]] = []
        original = logger_core.configure_logging

        def _spy(cfg: object, *, force: bool = False) -> None:
            calls.append((cfg, force))

        logger_core.configure_logging = _spy  # type: ignore[attr-defined]
        try:
            overrides = RuntimeOverrides(security=SecurityConfig(max_attr_count=32))
            runtime_mod.update_runtime_config(overrides)
        finally:
            logger_core.configure_logging = original  # type: ignore[attr-defined]

        assert calls == []


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
        from provide.telemetry.schema.events import EventSchemaError

        cfg = TelemetryConfig(strict_schema=False)
        runtime_mod.apply_runtime_config(cfg)
        proc = enforce_event_schema(cfg)
        # Enable strict via runtime
        runtime_mod.update_runtime_config(RuntimeOverrides(strict_schema=True))
        with pytest.raises(EventSchemaError, match="invalid event name"):
            proc(None, "", {"event": "bad event name"})

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
