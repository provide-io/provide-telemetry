# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Cycle and shared-subtree masking in the hardening processor.

Split from ``test_input_hardening.py``, which is at the 500-line ceiling.

Hardening is the first structural stage of the signal pipeline: it runs ahead
of the capture buffers, the renderers, receipt construction and the OTel
handler, so anything it refuses to expand here is something none of them ever
meet. A cycle is an infinite serializer and an n-times-shared subtree is an
n-fold blowup, and both arrive from caller-supplied data.
"""

from __future__ import annotations

from typing import Any

import pytest

from provide.telemetry import pii as pii_mod
from provide.telemetry import runtime as runtime_mod
from provide.telemetry.logger.processors import harden_input


@pytest.fixture(autouse=True)
def _reset() -> None:
    pii_mod.reset_pii_rules_for_tests()
    runtime_mod.reset_runtime_for_tests()


def test_a_self_referential_dict_is_masked_before_it_is_captured() -> None:
    processor = harden_input(1024, 64, 8)
    payload: dict[str, Any] = {}
    payload["self"] = payload
    result = processor(None, "", {"payload": payload})
    assert result["payload"] == {"self": "***"}


def test_a_self_referential_list_is_masked() -> None:
    processor = harden_input(1024, 64, 8)
    items: list[Any] = []
    items.append(items)
    result = processor(None, "", {"payload": items})
    assert result["payload"] == ["***"]


def test_mutual_recursion_between_a_dict_and_a_list_is_masked() -> None:
    processor = harden_input(1024, 64, 8)
    holder: dict[str, Any] = {}
    items: list[Any] = [holder]
    holder["items"] = items
    result = processor(None, "", {"payload": holder})
    assert result["payload"] == {"items": ["***"]}


def test_a_subtree_shared_between_two_keys_is_expanded_once() -> None:
    """Matches TypeScript's harden(), which carries the same set in a WeakSet."""
    processor = harden_input(1024, 64, 8)
    shared = {"k": "v"}
    result = processor(None, "", {"a": shared, "b": shared})
    assert result == {"a": {"k": "v"}, "b": "***"}


def test_cycle_masking_is_per_record_not_per_processor() -> None:
    """The identity set must not leak between records built by one processor."""
    processor = harden_input(1024, 64, 8)
    shared = {"k": "v"}
    first = processor(None, "", {"a": shared})
    second = processor(None, "", {"a": shared})
    assert first == second == {"a": {"k": "v"}}


def test_masking_does_not_fire_for_equal_but_distinct_subtrees() -> None:
    """Identity, not equality: two payloads that merely look alike both survive."""
    processor = harden_input(1024, 64, 8)
    result = processor(None, "", {"a": {"k": "v"}, "b": {"k": "v"}})
    assert result == {"a": {"k": "v"}, "b": {"k": "v"}}
