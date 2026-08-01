# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Injection tests for every surface that accepts untrusted input.

There is no SQL anywhere in this library, so the injection class that matters is
not SQLi but the set below: an attacker who controls a log attribute, an inbound
W3C header, or a config value must not be able to forge a log record, smuggle an
HTTP header, redirect telemetry, or stall the process.

Log-line forging deserves a note. ``harden_input``'s control-character filter
deliberately preserves TAB/LF/CR (``[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f\\x7f]``
skips them) so genuine multi-line payloads such as stack traces survive. What
actually prevents forging is the *renderers* quoting values — pretty via a repr
that escapes newlines, JSON via the encoder. That is an emergent property of two
independent components, so it is pinned here: if either renderer stops quoting,
a single attacker-controlled attribute becomes a fabricated log line.

Surfaces:
  log attributes      — record forging, ANSI escapes, NUL
  OTLP headers        — CRLF header smuggling
  endpoint URLs       — scheme confusion, credential and CRLF smuggling
  W3C traceparent     — malformed and oversized headers
  W3C baggage         — oversized headers and property smuggling
  PII/secret scanning — ReDoS via pathological inputs
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest
import structlog

from provide.telemetry._endpoint import validate_otlp_endpoint
from provide.telemetry.logger import processors as proc_mod
from provide.telemetry.logger.pretty import PrettyRenderer
from provide.telemetry.propagation import extract_w3c_context, parse_baggage

# A payload that, unescaped, reads as a complete second log record.
_FORGED_RECORD = "x\n2026-01-01T00:00:00Z [critical ] security.breach user=admin"
_ANSI_CLEAR = "\x1b[2J\x1b[1;1Hspoofed"
_CRLF = "value\r\nX-Smuggled: injected"


@pytest.fixture(autouse=True)
def _no_live_config(monkeypatch: Any) -> Any:
    monkeypatch.setattr(proc_mod, "_get_active_config", lambda: None)
    yield


def _harden(event: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = proc_mod.harden_input(4096, 64, 8)(None, "info", event)
    return result


# ── log attributes ──────────────────────────────────────────────────────────


def test_ansi_escapes_are_stripped_from_attributes() -> None:
    """ANSI escapes let an attacker clear the operator's terminal or repaint it."""
    cleaned = _harden({"v": _ANSI_CLEAR})["v"]

    assert "\x1b" not in cleaned
    assert cleaned == "[2J[1;1Hspoofed"


def test_nul_and_c0_controls_are_stripped_from_attributes() -> None:
    cleaned = _harden({"v": "a\x00b\x07c\x1fd\x7fe"})["v"]

    assert cleaned == "abcde"


def test_newlines_survive_hardening_by_design() -> None:
    """Pinning the deliberate carve-out, so a change to it is a conscious one."""
    cleaned = _harden({"v": "line1\nline2\ttabbed\rcr"})["v"]

    assert cleaned == "line1\nline2\ttabbed\rcr"


def test_pretty_renderer_escapes_newlines_so_records_cannot_be_forged() -> None:
    line = PrettyRenderer(colors=False)(None, "info", {"level": "info", "event": "real", "v": _FORGED_RECORD})

    assert "\n" not in line, f"a single record must render as a single line: {line!r}"
    assert "\\n" in line, "the newline must survive as an escape, not vanish"
    assert "security.breach" in line, "the payload is preserved, just neutralised"


def test_json_renderer_escapes_newlines_so_records_cannot_be_forged() -> None:
    rendered = structlog.processors.JSONRenderer()(None, "info", {"event": "real", "v": _FORGED_RECORD})

    assert "\n" not in rendered
    assert json.loads(rendered)["v"] == _FORGED_RECORD, "round-trip must be lossless"


def test_attribute_keys_are_also_hardened() -> None:
    """A hostile key is as dangerous as a hostile value."""
    cleaned = _harden({"k\x00ey": "v"})

    assert all("\x00" not in k for k in cleaned)


# ── endpoint URLs ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "endpoint",
    [
        "file:///etc/passwd",
        "javascript:alert(1)",
        "gopher://evil/_x",
        "data:text/plain,x",
        "ftp://evil/x",
        "http://host\r\nX-Smuggled: 1",
        "http://host\nX-Smuggled: 1",
        "http://[::1]:99999",
        "http://host:notaport",
        "http://host:",
    ],
    ids=lambda e: e[:28],
)
def test_hostile_endpoints_are_rejected(endpoint: str) -> None:
    """Only http/https may reach the exporter, and never with embedded CRLF.

    A non-HTTP scheme redirects telemetry to a local file or a foreign protocol;
    an embedded CRLF smuggles a header into the OTLP request.
    """
    with pytest.raises(ValueError):
        validate_otlp_endpoint(endpoint)


@pytest.mark.parametrize("endpoint", ["http://collector:4318", "https://collector:4318/v1/logs"])
def test_legitimate_endpoints_are_accepted(endpoint: str) -> None:
    assert validate_otlp_endpoint(endpoint) == endpoint


# ── W3C propagation headers ────────────────────────────────────────────────


def _scope(**headers: str) -> dict[str, Any]:
    return {"type": "http", "headers": [(k.encode(), v.encode()) for k, v in headers.items()]}


@pytest.mark.parametrize(
    "traceparent",
    [
        "",
        "not-a-traceparent",
        "00-" + "0" * 32 + "-" + "b" * 16 + "-01",  # all-zero trace id
        "00-" + "a" * 32 + "-" + "0" * 16 + "-01",  # all-zero span id
        "ff-" + "a" * 32 + "-" + "b" * 16 + "-01",  # reserved version
        "00-" + "g" * 32 + "-" + "b" * 16 + "-01",  # non-hex
        "00-" + "a" * 31 + "-" + "b" * 16 + "-01",  # wrong length
        "00-" + "a" * 32 + "-" + "b" * 16,  # missing field
        "00-" + "a" * 5000 + "-" + "b" * 16 + "-01",  # oversized
    ],
    ids=lambda t: t[:20] or "empty",
)
def test_hostile_traceparents_yield_no_context(traceparent: str) -> None:
    """A rejected header must produce no ids AND not be forwarded onward."""
    ctx = extract_w3c_context(_scope(traceparent=traceparent))

    assert ctx.trace_id is None
    assert ctx.span_id is None
    assert ctx.traceparent is None


def test_oversized_tracestate_is_dropped() -> None:
    ctx = extract_w3c_context(
        _scope(traceparent="00-" + "a" * 32 + "-" + "b" * 16 + "-01", tracestate="k=" + "v" * 5000)
    )

    assert ctx.tracestate is None


def test_oversized_baggage_is_dropped() -> None:
    ctx = extract_w3c_context(_scope(baggage="k=" + "v" * 20000))

    assert ctx.baggage is None


def test_baggage_properties_are_not_smuggled_into_values() -> None:
    """Everything after ";" is metadata and must never reach the log record."""
    assert parse_baggage("tenant=acme;role=admin;scope=all") == {"tenant": "acme"}


def test_baggage_ignores_empty_and_malformed_members() -> None:
    assert parse_baggage("=novalue,,nokey,ok=1") == {"ok": "1"}


# ── ReDoS ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "payload",
    [
        "A" * 100_000,
        "aws_secret_access_key=" + "A" * 50_000,
        ("a" * 500 + "!") * 100,
        "-----BEGIN RSA PRIVATE KEY-----" + "A" * 50_000,
    ],
    ids=["long-plain", "long-keyish", "backtrack-bait", "long-pem"],
)
def test_secret_scanning_does_not_blow_up_on_pathological_input(payload: str) -> None:
    """Scanning must stay linear: a log call cannot become a denial of service."""
    from provide.telemetry.pii import sanitize_payload

    started = time.perf_counter()
    sanitize_payload({"v": payload}, enabled=True)
    elapsed = time.perf_counter() - started

    assert elapsed < 2.0, f"scanning took {elapsed:.2f}s — possible catastrophic backtracking"
