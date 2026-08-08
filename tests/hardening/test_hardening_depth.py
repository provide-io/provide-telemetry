# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""The nesting-depth ceiling in the hardening processor.

Split from ``test_input_hardening.py``, which is at the 500-line ceiling.

The rule these tests pin is a cross-language contract, not a local preference:
a dict or list that *reaches* ``max_nesting_depth`` collapses to the redaction
marker. TypeScript (``typescript/src/harden.ts``), Go (``go/harden.go``) and
Rust (``rust/src/harden.rs``) all do the same, to the same marker, so relaxing
it here would leave Python alone in handing an unbounded value out of the stage
whose whole job is to bound one — hardening that returns the caller's original
composite at its own limit has hardened nothing, and the renderer and the OTel
exporter downstream would walk every level of it.
"""

from __future__ import annotations

from typing import Any

import pytest

from provide.telemetry import pii as pii_mod
from provide.telemetry import runtime as runtime_mod
from provide.telemetry.logger.processors import _HARDENED_PLACEHOLDER as HARDEN_MARKER
from provide.telemetry.logger.processors import harden_input


@pytest.fixture(autouse=True)
def _reset() -> None:
    pii_mod.reset_pii_rules_for_tests()
    runtime_mod.reset_runtime_for_tests()


def test_caps_nesting_depth() -> None:
    processor = harden_input(1024, 64, 1)
    deep = {"level1": {"level2": {"level3": "deep_value\x00evil"}}}
    result = processor(None, "", deep)
    # level1 sits below the ceiling and expands; level2 reaches it and is refused,
    # so level3 — and the poisoned string under it — never appear in the output.
    assert result["level1"] == {"level2": HARDEN_MARKER}


def test_dict_at_max_depth_collapses_to_the_marker() -> None:
    """Kills: depth >= max_depth -> depth > max_depth for dicts.

    At the ceiling the composite is refused rather than handed back. That is the
    only version of the ceiling that bounds what leaves the processor.
    """
    # _processor starts every value at depth 0, so a ceiling of 1 expands this
    # dict and its string is cleaned one level down.
    result = harden_input(1024, 64, 1)(None, "", {"a": {"b": "dirty\x01value"}})
    assert result["a"]["b"] == "dirtyvalue"

    # A ceiling of 0 puts that same dict at the limit: it becomes the marker,
    # rather than being passed through with its control character intact.
    result0 = harden_input(1024, 64, 0)(None, "", {"a": {"b": "dirty\x01value"}})
    assert result0["a"] == HARDEN_MARKER


def test_dict_just_below_max_depth_is_recursed() -> None:
    """Complement: below max_depth, dicts ARE expanded and their values cleaned."""
    result = harden_input(1024, 64, 1)(None, "", {"a": "dirty\x01value"})
    assert result["a"] == "dirtyvalue"


def test_list_at_max_depth_collapses_to_the_marker() -> None:
    """Kills: depth >= max_depth -> depth > max_depth for lists.

    A list at the ceiling is refused exactly as a dict is: an unbounded sequence
    is as unbounded as an unbounded mapping, and the exporter walks both.
    """
    result = harden_input(1024, 64, 1)(None, "", {"items": ["dirty\x01value"]})
    assert result["items"] == ["dirtyvalue"]

    result0 = harden_input(1024, 64, 0)(None, "", {"items": ["dirty\x01value"]})
    assert result0["items"] == HARDEN_MARKER


def test_composite_past_max_depth_never_reaches_the_renderer() -> None:
    """The regression the old pass-through allowed: 50 levels handed back whole.

    A caller could previously hand in a structure far deeper than the ceiling
    and get it back verbatim, so the renderer and the OTel exporter both walked
    the whole of it. Depth is a budget the output has to respect, not just a
    point at which traversal gives up.
    """
    payload: dict[str, Any] = {"leaf": "x\x01y"}
    for _ in range(50):
        payload = {"nest": payload}
    result = harden_input(1024, 64, 2)(None, "", {"deep": payload})
    # Depths 0 and 1 expand; the composite at depth 2 is the marker, so the 48
    # levels beneath it are never walked and never emitted.
    assert result["deep"]["nest"]["nest"] == HARDEN_MARKER


def test_depth_increment_in_dict_recursion() -> None:
    """Kills: depth + 1 -> depth + 2 or depth - 1 in dict recursion.

    With max_depth=3 a string at depth 3 must still be cleaned. Incrementing by
    two skips the level that would have cleaned it; decrementing never reaches
    the ceiling at all, so nothing ever collapses.
    """
    processor = harden_input(1024, 64, 3)
    result = processor(None, "", {"a": {"b": {"c": "val\x01ue"}}})
    # depths 0, 1 and 2 are all below 3, so c's value is reached and cleaned.
    assert result["a"]["b"]["c"] == "value"


def test_depth_increment_in_list_recursion() -> None:
    """Kills: depth + 1 -> depth + 2 or depth - 1 in list recursion."""
    processor = harden_input(1024, 64, 3)
    result = processor(None, "", {"items": [{"nested": "val\x01ue"}]})
    assert result["items"][0]["nested"] == "value"
