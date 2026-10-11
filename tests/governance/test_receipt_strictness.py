# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Receipt delivery is accepted only on ``True``, and hostile keys stay contained.

Three gaps, each a way an audit trail looked healthier than it was or a log
call could be taken down by caller data:

* a sink returning a truthy non-bool counted as delivered;
* a sink without a callable ``emit`` was accepted at enable time and then
  failed on every redaction;
* a mapping key whose ``__str__`` raised escaped canonicalization (and the log
  processors), and two keys rendering to one name produced a JSON object with
  a duplicated member -- a digest over an ambiguous document.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from provide.telemetry import pii as pii_mod
from provide.telemetry import receipts as receipts_mod
from provide.telemetry.exceptions import ConfigurationError
from provide.telemetry.health import get_health_snapshot, reset_health_for_tests
from provide.telemetry.logger.processors import _harden_keys, harden_input
from provide.telemetry.receipts import RedactionReceipt, canonical_json, emit_receipt, enable_receipts


class _Unprintable:
    def __str__(self) -> str:
        raise RuntimeError("str escaped")


class _NotAString:
    def __str__(self) -> Any:
        return 42


class _Returns:
    def __init__(self, value: object) -> None:
        self.value = value

    def emit(self, _receipt: RedactionReceipt, /) -> Any:
        return self.value


_RECEIPT = RedactionReceipt("i", "t", "s", "f", "redact", "h", "m")


@pytest.fixture(autouse=True)
def _reset() -> None:
    pii_mod.reset_pii_rules_for_tests()
    receipts_mod._reset_receipts_for_tests()
    reset_health_for_tests()


# ── acceptance ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("returned", [1, "yes", [1], _RECEIPT, None, False, 0])
def test_anything_but_true_counts_a_failure(returned: object) -> None:
    emit_receipt(_RECEIPT, _Returns(returned))
    assert get_health_snapshot().receipt_failures == 1


def test_true_counts_no_failure() -> None:
    emit_receipt(_RECEIPT, _Returns(True))
    assert get_health_snapshot().receipt_failures == 0


# ── enable-time sink validation ───────────────────────────────────────────────


class _NoEmit:
    pass


class _EmitNotCallable:
    emit = "not callable"


class _EmitPropertyRaises:
    @property
    def emit(self) -> Any:
        raise RuntimeError("property escaped")


@pytest.mark.parametrize("sink", [_NoEmit(), _EmitNotCallable(), _EmitPropertyRaises()])
def test_a_sink_without_a_callable_emit_is_refused(sink: object) -> None:
    with pytest.raises(ConfigurationError, match="callable emit"):
        enable_receipts(enabled=True, sink=cast(Any, sink))
    assert pii_mod._receipt_hook is None


def test_a_sink_with_a_callable_emit_is_accepted() -> None:
    enable_receipts(enabled=True, sink=_Returns(True))
    try:
        assert pii_mod._receipt_hook is not None
    finally:
        enable_receipts(enabled=False)


def test_disabling_never_inspects_the_sink() -> None:
    enable_receipts(enabled=False, sink=cast(Any, _NoEmit()))
    assert pii_mod._receipt_hook is None


# ── canonicalization: keys ────────────────────────────────────────────────────


def test_keys_rendering_to_one_name_canonicalize_to_null() -> None:
    assert canonical_json({1: "int", "1": "str"}) == "null"
    assert canonical_json({"outer": {1: "a", "1": "b"}, "ok": 1}) == '{"ok":1,"outer":null}'


def test_a_key_whose_str_raises_canonicalizes_to_null() -> None:
    assert canonical_json({_Unprintable(): "x"}) == "null"
    assert canonical_json({_NotAString(): "x"}) == "null"


def test_a_mapping_whose_items_raise_canonicalizes_to_null() -> None:
    class _Broken(dict[str, Any]):
        def items(self) -> Any:
            raise RuntimeError("items escaped")

    assert canonical_json({"inner": _Broken(a=1)}) == '{"inner":null}'


def test_distinct_keys_still_canonicalize_sorted() -> None:
    assert canonical_json({2: "a", 10: "b", "x": None}) == '{"10":"b","2":"a","x":null}'


# ── log processors: keys ──────────────────────────────────────────────────────


def test_harden_keys_contains_a_key_whose_str_raises() -> None:
    first: dict[Any, Any] = {_Unprintable(): "secret", "ok": 1}
    second: dict[Any, Any] = {_NotAString(): "secret"}
    assert _harden_keys(first) == {"***": "***", "ok": 1}
    assert _harden_keys(second) == {"***": "***"}


def test_a_verbatim_placeholder_key_keeps_its_slot_over_an_unprintable_one() -> None:
    after: dict[Any, Any] = {_Unprintable(): "x", "***": "real"}
    before: dict[Any, Any] = {"***": "real", _Unprintable(): "x"}
    assert _harden_keys(after) == {"***": "real"}
    assert _harden_keys(before) == {"***": "real"}


def test_harden_input_survives_a_hostile_nested_key() -> None:
    processor = harden_input(1024, 64, 8)
    result = processor(None, "info", {"event": "e", "payload": {_Unprintable(): "secret", "fine": "v"}})
    assert result == {"event": "e", "payload": {"***": "***", "fine": "v"}}
