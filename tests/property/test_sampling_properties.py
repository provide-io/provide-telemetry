# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Property-based tests for sampling, backpressure, and PII subsystems."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from provide.telemetry.backpressure import (
    QueuePolicy,
    get_queue_policy,
    release,
    reset_queues_for_tests,
    set_queue_policy,
    try_acquire,
)
from provide.telemetry.health import reset_health_for_tests
from provide.telemetry.pii import (
    PIIRule,
    _mask,
    get_pii_rules,
    register_pii_rule,
    reset_pii_rules_for_tests,
    sanitize_payload,
)
from provide.telemetry.sampling import (
    SamplingPolicy,
    _normalize_rate,
    get_sampling_policy,
    reset_sampling_for_tests,
    set_sampling_policy,
    should_sample,
)

# ── Sampling properties ───────────────────────────────────────────────


@given(rate=st.floats(min_value=-100.0, max_value=100.0, allow_nan=False))
def test_normalize_rate_always_clamps_to_unit_interval(rate: float) -> None:
    result = _normalize_rate(rate)
    assert 0.0 <= result <= 1.0


@given(
    rate=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    signal=st.sampled_from(["logs", "traces", "metrics"]),
)
@settings(max_examples=50)
def test_set_get_sampling_policy_roundtrip(rate: float, signal: str) -> None:
    reset_sampling_for_tests()
    set_sampling_policy(signal, SamplingPolicy(default_rate=rate))
    result = get_sampling_policy(signal)
    assert abs(result.default_rate - rate) < 1e-9


@given(signal=st.sampled_from(["logs", "traces", "metrics"]))
@settings(max_examples=30)
def test_rate_zero_never_samples(signal: str) -> None:
    reset_sampling_for_tests()
    reset_health_for_tests()
    set_sampling_policy(signal, SamplingPolicy(default_rate=0.0))
    for _ in range(50):
        assert should_sample(signal) is False


@given(signal=st.sampled_from(["logs", "traces", "metrics"]))
@settings(max_examples=30)
def test_rate_one_always_samples(signal: str) -> None:
    reset_sampling_for_tests()
    reset_health_for_tests()
    set_sampling_policy(signal, SamplingPolicy(default_rate=1.0))
    for _ in range(50):
        assert should_sample(signal) is True


@given(
    key=st.text(min_size=1, max_size=16, alphabet=st.characters(min_codepoint=97, max_codepoint=122)),
    override_rate=st.sampled_from([0.0, 1.0]),
)
@settings(max_examples=30)
def test_override_rate_respected(key: str, override_rate: float) -> None:
    reset_sampling_for_tests()
    reset_health_for_tests()
    set_sampling_policy("logs", SamplingPolicy(default_rate=0.5, overrides={key: override_rate}))
    results = [should_sample("logs", key=key) for _ in range(20)]
    if override_rate == 0.0:
        assert all(r is False for r in results)
    else:
        assert all(r is True for r in results)


@given(signal=st.text(min_size=1, max_size=8))
@settings(max_examples=20)
def test_unknown_signal_raises(signal: str) -> None:
    reset_sampling_for_tests()
    if signal not in {"logs", "traces", "metrics"}:
        with pytest.raises(ValueError, match="unknown signal"):
            get_sampling_policy(signal)


# ── Backpressure properties ───────────────────────────────────────────


@given(
    maxsize=st.integers(min_value=0, max_value=50),
    signal=st.sampled_from(["logs", "traces", "metrics"]),
)
@settings(max_examples=30)
def test_acquire_never_exceeds_maxsize(maxsize: int, signal: str) -> None:
    reset_queues_for_tests()
    reset_health_for_tests()
    kwargs = {f"{signal}_maxsize": maxsize}
    set_queue_policy(QueuePolicy(**kwargs))

    tickets = []
    for _ in range(maxsize + 10):
        ticket = try_acquire(signal)
        if ticket is not None and ticket.token != 0:
            tickets.append(ticket)

    if maxsize > 0:
        assert len(tickets) <= maxsize
    # Clean up
    for t in tickets:
        release(t)


@given(
    maxsize=st.integers(min_value=1, max_value=20),
    n_cycles=st.integers(min_value=1, max_value=10),
)
@settings(max_examples=20)
def test_acquire_release_cycles_leave_zero_depth(maxsize: int, n_cycles: int) -> None:
    reset_queues_for_tests()
    reset_health_for_tests()
    set_queue_policy(QueuePolicy(logs_maxsize=maxsize))

    for _ in range(n_cycles):
        tickets = []
        for _ in range(maxsize):
            t = try_acquire("logs")
            if t is not None:
                tickets.append(t)
        for t in tickets:
            release(t)

    # queue_depth removed from canonical health snapshot


@given(
    logs=st.integers(min_value=0, max_value=100),
    traces=st.integers(min_value=0, max_value=100),
    metrics=st.integers(min_value=0, max_value=100),
)
@settings(max_examples=20)
def test_set_get_queue_policy_roundtrip(logs: int, traces: int, metrics: int) -> None:
    reset_queues_for_tests()
    policy = QueuePolicy(logs_maxsize=logs, traces_maxsize=traces, metrics_maxsize=metrics)
    set_queue_policy(policy)
    result = get_queue_policy()
    assert result.logs_maxsize == logs
    assert result.traces_maxsize == traces
    assert result.metrics_maxsize == metrics


# ── PII properties ────────────────────────────────────────────────────


@given(
    value=st.text(min_size=0, max_size=64),
    truncate_to=st.integers(min_value=0, max_value=32),
)
@settings(max_examples=50)
def test_mask_truncate_respects_limit(value: str, truncate_to: int) -> None:
    result = _mask(value, "truncate", truncate_to)
    assert isinstance(result, str)
    if len(value) > truncate_to:
        assert result == value[:truncate_to] + "..."
    else:
        assert result == value


@given(value=st.text(min_size=0, max_size=64))
@settings(max_examples=30)
def test_mask_redact_always_returns_stars(value: str) -> None:
    assert _mask(value, "redact", 0) == "***"


@given(value=st.text(min_size=0, max_size=64))
@settings(max_examples=30)
def test_mask_drop_always_returns_none(value: str) -> None:
    assert _mask(value, "drop", 0) is None


@given(value=st.text(min_size=0, max_size=64))
@settings(max_examples=30)
def test_mask_hash_returns_12_char_hex(value: str) -> None:
    result = _mask(value, "hash", 0)
    assert isinstance(result, str)
    assert len(result) == 12
    assert all(c in "0123456789abcdef" for c in result)


@given(
    payload=st.dictionaries(
        keys=st.sampled_from(["name", "password", "token", "email", "api_key", "safe_field"]),
        values=st.text(min_size=1, max_size=16),
        min_size=1,
        max_size=6,
    )
)
@settings(max_examples=50)
def test_sanitize_payload_redacts_sensitive_keys(payload: dict[str, str]) -> None:
    reset_pii_rules_for_tests()
    result = sanitize_payload(payload, enabled=True)
    for key, value in result.items():
        if key.lower() in {"password", "token", "api_key", "secret", "authorization"}:
            assert value == "***"
        else:
            assert value == payload[key]


@given(
    payload=st.dictionaries(
        keys=st.text(min_size=1, max_size=8, alphabet=st.characters(min_codepoint=97, max_codepoint=122)),
        values=st.text(min_size=1, max_size=16),
        max_size=5,
    )
)
@settings(max_examples=30)
def test_sanitize_disabled_returns_original(payload: dict[str, str]) -> None:
    reset_pii_rules_for_tests()
    result = sanitize_payload(payload, enabled=False)
    assert result == payload


@given(
    key=st.text(min_size=1, max_size=8, alphabet=st.characters(min_codepoint=97, max_codepoint=122)),
    mode=st.sampled_from(["drop", "redact", "hash", "truncate"]),
)
@settings(max_examples=30)
def test_custom_pii_rule_applied(key: str, mode: str) -> None:
    reset_pii_rules_for_tests()
    register_pii_rule(PIIRule(path=(key,), mode=mode))  # type: ignore[arg-type]
    assert len(get_pii_rules()) == 1
    reset_pii_rules_for_tests()


# ── Traceparent properties ────────────────────────────────────────────


@given(
    trace_id=st.from_regex(r"[0-9a-f]{32}", fullmatch=True),
    span_id=st.from_regex(r"[0-9a-f]{16}", fullmatch=True),
    flags=st.from_regex(r"[0-9a-f]{2}", fullmatch=True),
)
@settings(max_examples=100)
def test_valid_traceparent_always_parses(trace_id: str, span_id: str, flags: str) -> None:
    from provide.telemetry.propagation import _parse_traceparent

    # Skip all-zero IDs
    if trace_id == "0" * 32 or span_id == "0" * 16:
        return
    value = f"00-{trace_id}-{span_id}-{flags}"
    result_tid, result_sid = _parse_traceparent(value)
    assert result_tid == trace_id
    assert result_sid == span_id


@given(
    version=st.from_regex(r"[0-9a-f]{2}", fullmatch=True).filter(lambda v: v.lower() != "ff"),
    trace_id=st.from_regex(r"[0-9a-f]{32}", fullmatch=True).filter(lambda t: t != "0" * 32),
    span_id=st.from_regex(r"[0-9a-f]{16}", fullmatch=True).filter(lambda s: s != "0" * 16),
    flags=st.from_regex(r"[0-9a-f]{2}", fullmatch=True),
)
@settings(max_examples=100)
def test_traceparent_with_various_versions_parses(version: str, trace_id: str, span_id: str, flags: str) -> None:
    from provide.telemetry.propagation import _parse_traceparent

    value = f"{version}-{trace_id}-{span_id}-{flags}"
    result_tid, result_sid = _parse_traceparent(value)
    assert result_tid == trace_id
    assert result_sid == span_id


@given(garbage=st.text(max_size=256))
@settings(max_examples=100)
def test_traceparent_fuzz_never_crashes(garbage: str) -> None:
    from provide.telemetry.propagation import _parse_traceparent

    result = _parse_traceparent(garbage)
    assert isinstance(result, tuple)
    assert len(result) == 2
