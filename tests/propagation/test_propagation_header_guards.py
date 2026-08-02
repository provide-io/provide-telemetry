# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Inbound-header guards: accepted sizes, and what baggage parsing strips.

Split out of ``test_propagation_mutations.py`` to keep both modules inside the
500-line ceiling ``scripts/check_max_loc.py`` enforces.
"""

from __future__ import annotations

from typing import Any

from provide.telemetry import propagation as propagation_mod


class TestExtractW3cContextSizeGuards:
    def test_tracestate_512_accepted(self) -> None:
        ts = "v" * 512
        scope: dict[str, Any] = {"headers": [(b"tracestate", ts.encode())]}
        assert propagation_mod.extract_w3c_context(scope).tracestate == ts

    def test_tracestate_32_pairs_accepted(self) -> None:
        ts = ",".join(f"v{i}=x" for i in range(32))
        scope: dict[str, Any] = {"headers": [(b"tracestate", ts.encode())]}
        assert propagation_mod.extract_w3c_context(scope).tracestate == ts

    def test_baggage_8192_accepted(self) -> None:
        bg = "k=" + "v" * 8190
        scope: dict[str, Any] = {"headers": [(b"baggage", bg.encode())]}
        assert propagation_mod.extract_w3c_context(scope).baggage == bg


class TestParseBaggageControlStripping:
    """Control characters are *removed* from a baggage value, not replaced.

    The substitution is a security boundary — a baggage value becomes a log
    attribute, and the console renderer emits it into a line-oriented stream.
    Substituting anything other than the empty string would leave a marker in
    the operator's record and change the value the next hop propagates.
    """

    def test_control_characters_are_removed_leaving_nothing_behind(self) -> None:
        assert propagation_mod.parse_baggage("a=x\x00y") == {"a": "xy"}
        assert propagation_mod.parse_baggage("a=x\x1fy") == {"a": "xy"}
        assert propagation_mod.parse_baggage("a=x\x7fy") == {"a": "xy"}

    def test_a_value_that_is_only_control_characters_becomes_empty(self) -> None:
        assert propagation_mod.parse_baggage("a=\x00\x01\x02") == {"a": ""}

    def test_tab_survives(self) -> None:
        assert propagation_mod.parse_baggage("a=x\ty") == {"a": "x\ty"}
