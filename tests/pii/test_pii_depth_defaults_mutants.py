# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests killing surviving mutants around PII traversal depth and node typing.

Depth defaults look cosmetic — every production call site passes an explicit
value — but they set how deep redaction reaches when a caller relies on the
default. A default that is off by one silently leaves the deepest level of a
payload unredacted, which is a data-leak, not a style issue.

Covers:
  _apply_rule:                            depth default of 0 (32-level safety limit)
  _apply_default_sensitive_key_redaction: max_depth default of 8
  sanitize_payload:                       max_depth default of 8
  _apply_default_sensitive_key_redaction: the list/list dual isinstance guard
"""

from __future__ import annotations

from typing import Any

from provide.telemetry import pii as pii_mod
from provide.telemetry.pii import PIIRule, sanitize_payload


def _nest(depth: int, leaf: Any) -> dict[str, Any]:
    """Build {"k": {"k": ... {"k": leaf}}} nested *depth* levels deep."""
    node: Any = leaf
    for _ in range(depth):
        node = {"k": node}
    return node  # type: ignore[no-any-return]


def _leaf(node: Any, depth: int) -> Any:
    for _ in range(depth):
        node = node["k"]
    return node


def test_apply_rule_depth_default_starts_at_zero() -> None:
    """The hard limit is `depth >= 32`, so the default must be 0, not 1.

    A default of 1 spends one level of the budget before traversal begins, which
    moves the cut-off from 31 levels to 30 and leaves the deepest rule-targeted
    value unredacted.
    """
    rule = PIIRule(path=("k",) * 31 + ("secret",), mode="redact")
    payload = _nest(31, {"secret": "v"})

    redacted = pii_mod._apply_rule(payload, rule)

    assert _leaf(redacted, 31)["secret"] != "v", "31 levels is inside the safety limit"


def test_apply_rule_stops_at_the_hard_safety_limit() -> None:
    rule = PIIRule(path=("k",) * 32 + ("secret",), mode="redact")
    payload = _nest(32, {"secret": "v"})

    redacted = pii_mod._apply_rule(payload, rule)

    assert _leaf(redacted, 32)["secret"] == "v", "32 levels is beyond the safety limit"


def test_sanitize_payload_max_depth_default_is_eight() -> None:
    """A default of 9 would reach one level deeper than the documented budget.

    Redaction at exactly the 8th level must happen; the 9th must not, which is
    what separates a default of 8 from a default of 9.
    """
    inside = sanitize_payload(_nest(7, {"password": "s3cret"}), enabled=True)
    beyond = sanitize_payload(_nest(8, {"password": "s3cret"}), enabled=True)

    assert _leaf(inside, 7)["password"] != "s3cret", "7 levels down is inside the budget"
    assert _leaf(beyond, 8)["password"] == "s3cret", "8 levels down is beyond the budget"


def test_default_sensitive_key_redaction_max_depth_default_is_eight() -> None:
    node = _nest(8, {"password": "s3cret"})
    original = _nest(8, {"password": "s3cret"})

    result = pii_mod._apply_default_sensitive_key_redaction(node, original)

    assert _leaf(result, 8)["password"] == "s3cret", "8 levels down is beyond the default budget"

    shallow = pii_mod._apply_default_sensitive_key_redaction(
        _nest(7, {"password": "s3cret"}), _nest(7, {"password": "s3cret"})
    )
    assert _leaf(shallow, 7)["password"] != "s3cret", "7 levels down is inside the budget"


def test_list_branch_requires_both_node_and_original_to_be_lists() -> None:
    """The guard is `and`, not `or`.

    With `or`, a list node paired with a non-list original enters the list branch
    and zips the list against the other value's iteration order, pairing entries
    that have nothing to do with each other. Requiring both keeps the mismatched
    pair out of that branch entirely.
    """
    node = ["alpha", "beta"]
    original = {"unrelated": "mapping"}

    result = pii_mod._apply_default_sensitive_key_redaction(node, original)

    assert result == node, "a mismatched node/original pair must pass through untouched"
