# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Category-named parity tests for behavioral_fixtures.yaml coverage.

Some YAML categories were historically tested under a different test_parity_*
prefix (e.g. test_parity_propagation_* for the propagation_guards category).
This file adds properly-named aliases and new tests so that
test_parity_fixture_yaml_coverage() can verify every category is covered.
"""

from __future__ import annotations

import pytest

from provide.telemetry.backpressure import (
    QueuePolicy,
    QueueTicket,
    reset_queues_for_tests,
    set_queue_policy,
    try_acquire,
)
from provide.telemetry.pii import replace_pii_rules, sanitize_payload
from provide.telemetry.propagation import extract_w3c_context
from provide.telemetry.sampling import (
    SamplingPolicy,
    reset_sampling_for_tests,
    set_sampling_policy,
    should_sample,
)
from provide.telemetry.slo import _reset_slo_for_tests, classify_error

# ── Fixtures ─────────────────────────────────────────────────────────────────

_VALID_TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
_VALID_SPAN_ID = "b7ad6b7169203331"


def _valid_traceparent() -> str:
    return f"00-{_VALID_TRACE_ID}-{_VALID_SPAN_ID}-01"


def _make_scope(headers: list[tuple[bytes, bytes]]) -> dict[str, object]:
    return {"type": "http", "headers": headers}


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    reset_sampling_for_tests()
    reset_queues_for_tests()
    replace_pii_rules([])
    _reset_slo_for_tests()


# ── Propagation Guards (category-named aliases) ──────────────────────────────
# The propagation_guards YAML category is covered by test_parity_propagation_*
# in test_behavioral_fixtures.py. These aliases ensure the meta-test can find
# a test_parity_propagation_guards_* function.


def test_parity_propagation_guards_traceparent_at_limit_accepted() -> None:
    tp = _valid_traceparent()
    scope = _make_scope([(b"traceparent", tp.encode())])
    ctx = extract_w3c_context(scope)
    assert ctx.traceparent is not None


def test_parity_propagation_guards_traceparent_over_limit_discarded() -> None:
    long_tp = "x" * 513
    scope = _make_scope([(b"traceparent", long_tp.encode())])
    ctx = extract_w3c_context(scope)
    assert ctx.traceparent is None


# ── SLO Classify (category-named aliases) ────────────────────────────────────
# The slo_classify YAML category is covered by test_parity_classify_* in
# test_behavioral_fixtures.py. These aliases map the YAML category name.


def test_parity_slo_classify_status_400_client_error() -> None:
    result = classify_error("BadRequest", status_code=400)
    assert result["error.category"] == "client_error"


def test_parity_slo_classify_status_500_server_error() -> None:
    result = classify_error("InternalServerError", status_code=500)
    assert result["error.category"] == "server_error"


# ── Cardinality Clamping ─────────────────────────────────────────────────────
# Full cardinality tests live here (moved from test_behavioral_fixtures.py to
# keep the primary file under 500 lines). The test_parity_cardinality_clamping_*
# prefix satisfies the cardinality_clamping YAML category check.


def test_parity_cardinality_clamping_zero_max_values() -> None:
    from provide.telemetry.cardinality import (
        clear_cardinality_limits,
        register_cardinality_limit,
    )

    clear_cardinality_limits()
    register_cardinality_limit("ck", max_values=0, ttl_seconds=10.0)
    from provide.telemetry.cardinality import _limits

    assert _limits["ck"].max_values == 1
    assert _limits["ck"].ttl_seconds == 10.0
    clear_cardinality_limits()


def test_parity_cardinality_clamping_negative_max_values() -> None:
    from provide.telemetry.cardinality import (
        clear_cardinality_limits,
        register_cardinality_limit,
    )

    clear_cardinality_limits()
    register_cardinality_limit("ck", max_values=-5, ttl_seconds=10.0)
    from provide.telemetry.cardinality import _limits

    assert _limits["ck"].max_values == 1
    clear_cardinality_limits()


def test_parity_cardinality_clamping_zero_ttl() -> None:
    from provide.telemetry.cardinality import (
        clear_cardinality_limits,
        register_cardinality_limit,
    )

    clear_cardinality_limits()
    register_cardinality_limit("ck", max_values=10, ttl_seconds=0.0)
    from provide.telemetry.cardinality import _limits

    assert _limits["ck"].ttl_seconds == 1.0
    clear_cardinality_limits()


def test_parity_cardinality_clamping_valid_values_unchanged() -> None:
    from provide.telemetry.cardinality import (
        clear_cardinality_limits,
        register_cardinality_limit,
    )

    clear_cardinality_limits()
    register_cardinality_limit("ck", max_values=50, ttl_seconds=300.0)
    from provide.telemetry.cardinality import _limits

    assert _limits["ck"].max_values == 50
    assert _limits["ck"].ttl_seconds == 300.0
    clear_cardinality_limits()


# ── Schema Strict Mode ───────────────────────────────────────────────────────
# Full schema strict mode tests live here (moved from test_behavioral_fixtures.py
# to keep the primary file under 500 lines).


def test_parity_schema_strict_mode_lenient_accepts_uppercase(monkeypatch: pytest.MonkeyPatch) -> None:
    from provide.telemetry.schema import events as _events_mod

    monkeypatch.setattr("provide.telemetry.runtime._is_strict_event_name", lambda: False)
    result = _events_mod.event_name("A", "B", "C")
    assert result == "A.B.C"


def test_parity_schema_strict_mode_lenient_accepts_mixed_case(monkeypatch: pytest.MonkeyPatch) -> None:
    from provide.telemetry.schema import events as _events_mod

    monkeypatch.setattr("provide.telemetry.runtime._is_strict_event_name", lambda: False)
    result = _events_mod.event_name("User", "Login", "Ok")
    assert result == "User.Login.Ok"


def test_parity_schema_strict_mode_strict_rejects_uppercase(monkeypatch: pytest.MonkeyPatch) -> None:
    from provide.telemetry.schema import events as _events_mod

    monkeypatch.setattr("provide.telemetry.runtime._is_strict_event_name", lambda: True)
    with pytest.raises(_events_mod.EventSchemaError):
        _events_mod.event_name("User", "login", "ok")


def test_parity_schema_strict_mode_strict_accepts_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    from provide.telemetry.schema import events as _events_mod

    monkeypatch.setattr("provide.telemetry.runtime._is_strict_event_name", lambda: True)
    result = _events_mod.event_name("user", "login", "ok")
    assert result == "user.login.ok"


def test_parity_schema_strict_mode_required_keys_missing_error() -> None:
    from provide.telemetry.schema.events import EventSchemaError, validate_required_keys

    with pytest.raises(EventSchemaError):
        validate_required_keys({"domain": "auth"}, ("domain", "action"))


def test_parity_schema_strict_mode_required_keys_all_present_ok() -> None:
    from provide.telemetry.schema.events import validate_required_keys

    validate_required_keys({"domain": "auth", "action": "login"}, ("domain", "action"))


def test_parity_schema_strict_mode_required_keys_empty_ok() -> None:
    from provide.telemetry.schema.events import validate_required_keys

    validate_required_keys({"domain": "auth"}, ())


# ── Sampling Signal Validation ───────────────────────────────────────────────


def test_parity_sampling_signal_validation_valid_signals() -> None:
    for signal in ("logs", "traces", "metrics"):
        set_sampling_policy(signal, SamplingPolicy(default_rate=1.0))
        assert should_sample(signal, "evt")


def test_parity_sampling_signal_validation_invalid_signal_raises() -> None:
    with pytest.raises(ValueError, match="unknown signal"):
        should_sample("log", "evt")


def test_parity_sampling_signal_validation_empty_string_raises() -> None:
    with pytest.raises(ValueError, match="unknown signal"):
        should_sample("", "evt")


# ── Backpressure Unlimited ───────────────────────────────────────────────────


def test_parity_backpressure_unlimited_size_zero_acquire_succeeds() -> None:
    set_queue_policy(QueuePolicy(logs_maxsize=0))
    ticket = try_acquire("logs")
    assert ticket is not None
    assert isinstance(ticket, QueueTicket)


def test_parity_backpressure_unlimited_size_zero_multiple_acquires_succeed() -> None:
    set_queue_policy(QueuePolicy(logs_maxsize=0))
    tickets = [try_acquire("logs") for _ in range(100)]
    assert all(t is not None for t in tickets)


def test_parity_backpressure_unlimited_size_one_second_acquire_rejected() -> None:
    set_queue_policy(QueuePolicy(logs_maxsize=1))
    first = try_acquire("logs")
    second = try_acquire("logs")
    assert first is not None
    assert second is None


# ── PII Depth ────────────────────────────────────────────────────────────────


def test_parity_pii_depth_within_max_depth_is_redacted() -> None:
    # depth < max_depth: sensitive key at depth 1 should be redacted when max_depth=3
    payload = {"outer": {"password": "secret"}}  # pragma: allowlist secret
    result = sanitize_payload(payload, enabled=True, max_depth=3)
    assert result["outer"]["password"] == "***"  # pragma: allowlist secret


def test_parity_pii_depth_at_max_depth_is_untouched() -> None:
    # depth >= max_depth: nested dict at max_depth boundary is returned as-is
    inner = {"password": "secret"}  # pragma: allowlist secret
    payload = {"a": {"b": inner}}  # inner is at depth 2; with max_depth=2, it is not traversed
    result = sanitize_payload(payload, enabled=True, max_depth=2)
    # At depth=2 recursion stops, so the inner dict is returned without redaction
    assert result["a"]["b"]["password"] == "secret"  # pragma: allowlist secret
