# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests killing surviving mutants in propagation.py: parse_baggage and _baggage_keys."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from provide.telemetry import propagation as propagation_mod
from provide.telemetry.logger import context as logger_context_mod
from provide.telemetry.logger.context import clear_context
from provide.telemetry.tracing.context import set_trace_context


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    clear_context()
    set_trace_context(None, None)


# ---------------------------------------------------------------------------
# parse_baggage survivors
# ---------------------------------------------------------------------------


class TestParseBaggage:
    """Kill mutants in parse_baggage."""

    def test_multiple_semicolons_strips_all_properties(self) -> None:
        """Baggage with multiple properties after ';': split(";",1)[0] keeps only kv.

        Kills mutmut_9: split->rsplit. With "k=v;p1;p2":
          split(";",1)[0] = "k=v"   (correct)
          rsplit(";",1)[0] = "k=v;p1" (wrong -- includes property as part of value)
        """
        result = propagation_mod.parse_baggage("key=value;prop1;prop2")
        assert result == {"key": "value"}

    def test_value_with_equals_sign_uses_partition(self) -> None:
        """Value containing '=' must be preserved whole via partition.

        Kills mutmut_18: partition->rpartition. With "key=a=b":
          partition("=")  -> key="key", value="a=b" (correct)
          rpartition("=") -> key="key=a", value="b" (wrong)
        """
        result = propagation_mod.parse_baggage("key=a=b")
        assert result == {"key": "a=b"}

    def test_basic_parsing(self) -> None:
        """Baseline: comma-separated key=value pairs."""
        result = propagation_mod.parse_baggage("k1=v1,k2=v2")
        assert result == {"k1": "v1", "k2": "v2"}

    def test_whitespace_stripped(self) -> None:
        """Keys and values must be stripped of whitespace."""
        result = propagation_mod.parse_baggage("  key  = value ")
        assert result == {"key": "value"}

    def test_empty_key_skipped(self) -> None:
        """Members with empty key (after strip) are skipped."""
        result = propagation_mod.parse_baggage("=value,k=v")
        assert result == {"k": "v"}


# ---------------------------------------------------------------------------
# bind/clear_propagation_context: _baggage_keys key name
# ---------------------------------------------------------------------------


class TestBaggageKeysKeyName:
    """Kill mutmut_45/46 in bind and mutmut_34/36 in clear."""

    def test_baggage_keys_unbound_on_clear(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Baggage entries bound during bind must be unbound during clear.

        Kills mutmut_45: "_baggage_keys" -> "XX_baggage_keysXX" in bind.
        Kills mutmut_46: "_baggage_keys" -> "_BAGGAGE_KEYS" in bind.
        If the key name is wrong in bind, clear's get("_baggage_keys", []) returns
        the default [] and baggage.* keys are never unbound.
        """
        mock_attach = MagicMock(return_value="token")
        monkeypatch.setattr(propagation_mod, "attach_w3c_context", mock_attach)
        monkeypatch.setattr(propagation_mod, "detach_w3c_context", lambda t: None)

        unbound_keys: list[str] = []
        original_unbind = logger_context_mod.unbind_context

        def _tracking_unbind(*keys: str) -> None:
            unbound_keys.extend(keys)
            original_unbind(*keys)

        monkeypatch.setattr("provide.telemetry.propagation.unbind_context", _tracking_unbind)

        ctx = propagation_mod.PropagationContext(
            traceparent="00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
            tracestate=None,
            baggage="user_id=abc,session=xyz",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            span_id="00f067aa0ba902b7",
        )
        propagation_mod.bind_propagation_context(ctx)
        propagation_mod.clear_propagation_context()

        # baggage.user_id and baggage.session must have been unbound
        assert "baggage.user_id" in unbound_keys, f"Expected 'baggage.user_id' to be unbound, got: {unbound_keys}"
        assert "baggage.session" in unbound_keys, f"Expected 'baggage.session' to be unbound, got: {unbound_keys}"
