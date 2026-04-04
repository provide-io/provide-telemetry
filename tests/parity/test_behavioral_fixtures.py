# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Cross-language behavioral parity tests.

Validates Python against spec/behavioral_fixtures.yaml.
Go and TypeScript have equivalent test suites validating the same fixtures.
"""

from __future__ import annotations

import re

import pytest

from provide.telemetry.backpressure import reset_queues_for_tests
from provide.telemetry.config import _parse_otlp_headers
from provide.telemetry.pii import PIIRule, _mask, replace_pii_rules, sanitize_payload
from provide.telemetry.propagation import extract_w3c_context
from provide.telemetry.sampling import (
    SamplingPolicy,
    reset_sampling_for_tests,
    set_sampling_policy,
    should_sample,
)
from provide.telemetry.schema.events import EventSchemaError, event
from provide.telemetry.slo import _reset_slo_for_tests, classify_error

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    reset_sampling_for_tests()
    reset_queues_for_tests()
    replace_pii_rules([])
    _reset_slo_for_tests()


# ── Helpers ──────────────────────────────────────────────────────────────────

_VALID_TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
_VALID_SPAN_ID = "b7ad6b7169203331"


def _make_scope(headers: list[tuple[bytes, bytes]]) -> dict[str, object]:
    return {"type": "http", "headers": headers}


def _valid_traceparent() -> str:
    return f"00-{_VALID_TRACE_ID}-{_VALID_SPAN_ID}-01"


# ── Sampling ─────────────────────────────────────────────────────────────────


def test_parity_sampling_rate_zero_always_drops() -> None:
    set_sampling_policy("logs", SamplingPolicy(default_rate=0.0))
    for _ in range(100):
        assert not should_sample("logs", "evt")


def test_parity_sampling_rate_one_always_keeps() -> None:
    set_sampling_policy("logs", SamplingPolicy(default_rate=1.0))
    for _ in range(100):
        assert should_sample("logs", "evt")


def test_parity_sampling_rate_half_statistical() -> None:
    set_sampling_policy("logs", SamplingPolicy(default_rate=0.5))
    n = 10_000
    count = sum(1 for _ in range(n) if should_sample("logs", "evt"))
    pct = count / n * 100
    assert 40 <= pct <= 60, f"rate=0.5: expected 40-60%, got {pct:.1f}%"


def test_parity_sampling_rate_099_statistical() -> None:
    set_sampling_policy("logs", SamplingPolicy(default_rate=0.99))
    n = 10_000
    count = sum(1 for _ in range(n) if should_sample("logs", "evt"))
    pct = count / n * 100
    assert 95 <= pct <= 100, f"rate=0.99: expected 95-100%, got {pct:.1f}%"


def test_parity_sampling_rate_0001_statistical() -> None:
    set_sampling_policy("logs", SamplingPolicy(default_rate=0.001))
    n = 100_000
    count = sum(1 for _ in range(n) if should_sample("logs", "evt"))
    pct = count / n * 100
    assert 0 <= pct <= 1, f"rate=0.001: expected 0-1%, got {pct:.1f}%"


# ── PII Hash ────────────────────────────────────────────────────────────────


def test_parity_pii_hash_format() -> None:
    result = _mask("user-42", "hash", truncate_to=0)
    assert len(result) == 12
    assert re.match(r"^[0-9a-f]{12}$", result)


def test_parity_pii_hash_deterministic() -> None:
    replace_pii_rules([PIIRule(path=("uid",), mode="hash")])
    r = sanitize_payload({"uid": "same-input"}, enabled=True, max_depth=32)
    assert r["uid"] == "f52c2013103b"


def test_parity_pii_hash_integer() -> None:
    replace_pii_rules([PIIRule(path=("n",), mode="hash")])
    r = sanitize_payload({"n": 42}, enabled=True, max_depth=32)
    assert r["n"] == "73475cb40a56"  # pragma: allowlist secret


# ── PII Truncate ─────────────────────────────────────────────────────────────


def test_parity_pii_truncate_longer_than_limit() -> None:
    replace_pii_rules([PIIRule(path=("note",), mode="truncate", truncate_to=5)])
    r = sanitize_payload({"note": "hello world"}, enabled=True, max_depth=32)
    assert r["note"] == "hello..."


def test_parity_pii_truncate_at_limit_unchanged() -> None:
    replace_pii_rules([PIIRule(path=("note",), mode="truncate", truncate_to=5)])
    r = sanitize_payload({"note": "hello"}, enabled=True, max_depth=32)
    assert r["note"] == "hello"


def test_parity_pii_truncate_shorter_than_limit_unchanged() -> None:
    replace_pii_rules([PIIRule(path=("note",), mode="truncate", truncate_to=5)])
    r = sanitize_payload({"note": "hi"}, enabled=True, max_depth=32)
    assert r["note"] == "hi"


def test_parity_pii_truncate_non_string_converted() -> None:
    replace_pii_rules([PIIRule(path=("n",), mode="truncate", truncate_to=5)])
    r = sanitize_payload({"n": 1234567890}, enabled=True, max_depth=32)
    assert r["n"] == "12345..."


# ── PII Redact ───────────────────────────────────────────────────────────────


def test_parity_pii_redact_sensitive_key() -> None:
    r = sanitize_payload({"password": "s3cret"}, enabled=True, max_depth=32)  # pragma: allowlist secret
    assert r["password"] == "***"  # pragma: allowlist secret


def test_parity_pii_redact_case_insensitive() -> None:
    r = sanitize_payload({"API_KEY": "abc123"}, enabled=True, max_depth=32)
    assert r["API_KEY"] == "***"


# ── PII Drop ────────────────────────────────────────────────────────────────


def test_parity_pii_drop_removes_key() -> None:
    replace_pii_rules([PIIRule(path=("card_number",), mode="drop")])
    r = sanitize_payload({"card_number": "4111-1111"}, enabled=True, max_depth=32)
    assert "card_number" not in r


# ── Event DARS ───────────────────────────────────────────────────────────────


def test_parity_event_das_3_segments() -> None:
    evt = event("user", "login", "ok")
    assert str(evt) == "user.login.ok"
    assert evt.domain == "user"
    assert evt.action == "login"
    assert evt.resource is None
    assert evt.status == "ok"


def test_parity_event_dars_4_segments() -> None:
    evt = event("db", "query", "users", "ok")
    assert str(evt) == "db.query.users.ok"
    assert evt.domain == "db"
    assert evt.action == "query"
    assert evt.resource == "users"
    assert evt.status == "ok"


def test_parity_event_2_segments_error() -> None:
    with pytest.raises(EventSchemaError):
        event("too", "few")


def test_parity_event_5_segments_error() -> None:
    with pytest.raises(EventSchemaError):
        event("a", "b", "c", "d", "e")


# ── Propagation Guards ──────────────────────────────────────────────────────


def test_parity_propagation_traceparent_at_limit_accepted() -> None:
    tp = _valid_traceparent()
    scope = _make_scope([(b"traceparent", tp.encode())])
    ctx = extract_w3c_context(scope)
    assert ctx.traceparent is not None


def test_parity_propagation_traceparent_over_limit_discarded() -> None:
    long_tp = "x" * 513
    scope = _make_scope([(b"traceparent", long_tp.encode())])
    ctx = extract_w3c_context(scope)
    assert ctx.traceparent is None


def test_parity_propagation_tracestate_32_pairs_accepted() -> None:
    tp = _valid_traceparent()
    ts = ",".join(["k=v"] * 32)
    scope = _make_scope(
        [
            (b"traceparent", tp.encode()),
            (b"tracestate", ts.encode()),
        ]
    )
    ctx = extract_w3c_context(scope)
    assert ctx.tracestate is not None


def test_parity_propagation_tracestate_33_pairs_discarded() -> None:
    tp = _valid_traceparent()
    ts = ",".join(["k=v"] * 33)
    scope = _make_scope(
        [
            (b"traceparent", tp.encode()),
            (b"tracestate", ts.encode()),
        ]
    )
    ctx = extract_w3c_context(scope)
    assert ctx.tracestate is None


def test_parity_propagation_baggage_at_limit_accepted() -> None:
    tp = _valid_traceparent()
    baggage = "k=" + "v" * (8192 - 2)  # "k=" is 2 bytes, total = 8192
    scope = _make_scope(
        [
            (b"traceparent", tp.encode()),
            (b"baggage", baggage.encode()),
        ]
    )
    ctx = extract_w3c_context(scope)
    assert ctx.baggage is not None


def test_parity_propagation_baggage_over_limit_discarded() -> None:
    tp = _valid_traceparent()
    baggage = "k=" + "v" * (8193 - 2)  # total = 8193
    scope = _make_scope(
        [
            (b"traceparent", tp.encode()),
            (b"baggage", baggage.encode()),
        ]
    )
    ctx = extract_w3c_context(scope)
    assert ctx.baggage is None


# ── Config Headers ───────────────────────────────────────────────────────────


def test_parity_config_headers_normal() -> None:
    assert _parse_otlp_headers("Authorization=Bearer+token") == {"Authorization": "Bearer token"}


def test_parity_config_headers_url_encoded() -> None:
    assert _parse_otlp_headers("my%20key=my%20value") == {"my key": "my value"}


def test_parity_config_headers_empty_key_skipped() -> None:
    assert _parse_otlp_headers("=value,key=val") == {"key": "val"}


def test_parity_config_headers_no_equals_skipped() -> None:
    assert _parse_otlp_headers("malformed,key=val") == {"key": "val"}


def test_parity_config_headers_value_containing_equals() -> None:
    assert _parse_otlp_headers("Authorization=Bearer token=xyz") == {
        "Authorization": "Bearer token=xyz",
    }


def test_parity_config_headers_empty_string() -> None:
    assert _parse_otlp_headers("") == {}


# ── SLO Classify ─────────────────────────────────────────────────────────────


def test_parity_classify_error_400() -> None:
    result = classify_error("BadRequest", status_code=400)
    assert result["error.category"] == "client_error"


def test_parity_classify_error_500() -> None:
    result = classify_error("InternalServerError", status_code=500)
    assert result["error.category"] == "server_error"


def test_parity_classify_error_429() -> None:
    result = classify_error("TooManyRequests", status_code=429)
    assert result["error.category"] == "client_error"
    assert result["error.severity"] == "critical"


def test_parity_classify_error_0_timeout() -> None:
    result = classify_error("ConnectionError", status_code=0)
    assert result["error.category"] == "timeout"


# ── PII Default Sensitive Keys (canonical 17) ────────────────────────────────


def test_parity_default_sensitive_keys_cookie() -> None:
    """cookie is in the canonical 17-key default sensitive list."""
    payload = {"cookie": "session=abc123"}
    result = sanitize_payload(payload, enabled=True)
    assert result["cookie"] == "***"


def test_parity_default_sensitive_keys_cvv() -> None:
    """cvv is in the canonical 17-key default sensitive list."""
    payload = {"cvv": "123"}
    result = sanitize_payload(payload, enabled=True)
    assert result["cvv"] == "***"


def test_parity_default_sensitive_keys_pin() -> None:
    """pin is in the canonical 17-key default sensitive list."""
    payload = {"pin": "9876"}
    result = sanitize_payload(payload, enabled=True)
    assert result["pin"] == "***"
