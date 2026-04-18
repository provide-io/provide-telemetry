# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for the strippable data classification module."""

from __future__ import annotations

from collections.abc import Generator

import pytest

from provide.telemetry import pii as pii_mod
from provide.telemetry.classification import (
    ClassificationPolicy,
    ClassificationRule,
    DataClass,
    _classify_field,
    _reset_classification_for_tests,
    classify_key,
    get_classification_policy,
    register_classification_rule,
    register_classification_rules,
    set_classification_policy,
)


@pytest.fixture(autouse=True)
def _reset() -> Generator[None, None, None]:
    _reset_classification_for_tests()
    pii_mod.reset_pii_rules_for_tests()
    yield
    _reset_classification_for_tests()
    pii_mod.reset_pii_rules_for_tests()


# ── DataClass enum ────────────────────────────────────────────────────────────


def test_dataclass_enum_values() -> None:
    assert DataClass.PUBLIC.value == "PUBLIC"
    assert DataClass.INTERNAL.value == "INTERNAL"
    assert DataClass.PII.value == "PII"
    assert DataClass.PHI.value == "PHI"
    assert DataClass.PCI.value == "PCI"
    assert DataClass.SECRET.value == "SECRET"  # pragma: allowlist secret


def test_dataclass_enum_members_count() -> None:
    assert len(DataClass) == 6


# ── ClassificationPolicy defaults ────────────────────────────────────────────


def test_default_policy_values() -> None:
    policy = ClassificationPolicy()
    assert policy.PUBLIC == "pass"
    assert policy.INTERNAL == "pass"
    assert policy.PII == "redact"
    assert policy.PHI == "drop"
    assert policy.PCI == "hash"
    assert policy.SECRET == "drop"  # pragma: allowlist secret


# ── register_classification_rules installs hook ───────────────────────────────


def test_no_rules_hook_is_none() -> None:
    """Before any rules are registered, the hook is not installed."""
    assert pii_mod._classification_hook is None


def test_register_rules_installs_hook() -> None:
    rule = ClassificationRule(pattern="email", classification=DataClass.PII)
    register_classification_rules([rule])
    assert pii_mod._classification_hook is not None


def test_register_single_rule_wrapper_installs_hook() -> None:
    rule = ClassificationRule(pattern="email", classification=DataClass.PII)
    register_classification_rule(rule)
    assert pii_mod._classification_hook is not None


def test_register_empty_list_still_installs_hook() -> None:
    """Even registering an empty list installs the hook."""
    register_classification_rules([])
    assert pii_mod._classification_hook is not None


# ── Classification tags appear in sanitized payloads ─────────────────────────


def test_classification_tag_added_to_payload() -> None:
    register_classification_rules([ClassificationRule(pattern="email", classification=DataClass.PII)])
    result = pii_mod.sanitize_payload({"email": "alice@example.com", "name": "Alice"}, enabled=True)
    assert result.get("__email__class") == "PII"
    assert "__name__class" not in result


def test_phi_classification_tag() -> None:
    register_classification_rules([ClassificationRule(pattern="dob", classification=DataClass.PHI)])
    result = pii_mod.sanitize_payload({"dob": "1990-01-01", "name": "Bob"}, enabled=True)
    # PHI default action is "drop" — field is removed, no class tag added
    assert "dob" not in result
    assert "__dob__class" not in result


def test_pci_classification_tag() -> None:
    register_classification_rules([ClassificationRule(pattern="card_num", classification=DataClass.PCI)])
    result = pii_mod.sanitize_payload({"card_num": "4111111111111111"}, enabled=True)
    assert result.get("__card_num__class") == "PCI"


# ── First-match wins ──────────────────────────────────────────────────────────


def test_first_matching_rule_wins() -> None:
    rules = [
        ClassificationRule(pattern="email", classification=DataClass.PII),
        ClassificationRule(pattern="email", classification=DataClass.PHI),
    ]
    register_classification_rules(rules)
    label = _classify_field("email", "alice@example.com")
    assert label == "PII"


# ── Wildcard patterns ─────────────────────────────────────────────────────────


def test_wildcard_pattern_matches() -> None:
    register_classification_rules([ClassificationRule(pattern="user_*", classification=DataClass.INTERNAL)])
    label = _classify_field("user_id", 42)
    assert label == "INTERNAL"
    label2 = _classify_field("user_name", "Alice")
    assert label2 == "INTERNAL"


def test_wildcard_does_not_match_unrelated_key() -> None:
    register_classification_rules([ClassificationRule(pattern="user_*", classification=DataClass.INTERNAL)])
    label = _classify_field("email", "alice@example.com")
    assert label is None


# ── Unmatched key → no tag ────────────────────────────────────────────────────


def test_unmatched_key_no_tag() -> None:
    register_classification_rules([ClassificationRule(pattern="email", classification=DataClass.PII)])
    result = pii_mod.sanitize_payload({"name": "Alice"}, enabled=True)
    assert not any(k.endswith("__class") for k in result)


def test_classify_field_returns_none_when_no_rules() -> None:
    label = _classify_field("email", "alice@example.com")
    assert label is None


def test_classify_field_returns_none_when_no_match() -> None:
    register_classification_rules([ClassificationRule(pattern="dob", classification=DataClass.PHI)])
    label = _classify_field("email", "alice@example.com")
    assert label is None


def test_classify_key_returns_dataclass_member() -> None:
    register_classification_rule(ClassificationRule(pattern="email", classification=DataClass.PII))

    assert classify_key("email") is DataClass.PII
    assert classify_key("missing") is None


# ── set/get_classification_policy ────────────────────────────────────────────


def test_set_and_get_classification_policy() -> None:
    new_policy = ClassificationPolicy(PII="drop", PHI="redact")
    set_classification_policy(new_policy)
    policy = get_classification_policy()
    assert policy.PII == "drop"
    assert policy.PHI == "redact"


def test_get_classification_policy_returns_default() -> None:
    policy = get_classification_policy()
    assert policy.PUBLIC == "pass"
    assert policy.PII == "redact"


# ── _reset_classification_for_tests ──────────────────────────────────────────


def test_reset_clears_rules() -> None:
    register_classification_rules([ClassificationRule(pattern="email", classification=DataClass.PII)])
    _reset_classification_for_tests()
    label = _classify_field("email", "alice@example.com")
    assert label is None


def test_reset_removes_hook() -> None:
    register_classification_rules([ClassificationRule(pattern="email", classification=DataClass.PII)])
    _reset_classification_for_tests()
    assert pii_mod._classification_hook is None


def test_reset_restores_default_policy() -> None:
    set_classification_policy(ClassificationPolicy(PII="drop"))
    _reset_classification_for_tests()
    policy = get_classification_policy()
    assert policy.PII == "redact"


# ── Disabled payload — no tagging ────────────────────────────────────────────


def test_classification_disabled_payload_not_tagged() -> None:
    register_classification_rules([ClassificationRule(pattern="email", classification=DataClass.PII)])
    result = pii_mod.sanitize_payload({"email": "alice@example.com"}, enabled=False)
    assert "__email__class" not in result


# ── Multiple rules accumulate ─────────────────────────────────────────────────


def test_register_rules_called_twice_accumulates() -> None:
    register_classification_rules([ClassificationRule(pattern="email", classification=DataClass.PII)])
    register_classification_rules([ClassificationRule(pattern="dob", classification=DataClass.PHI)])
    assert _classify_field("email", "") == "PII"
    assert _classify_field("dob", "") == "PHI"


# ── Public/Internal/Secret class labels ──────────────────────────────────────


def test_public_classification_label() -> None:
    register_classification_rules([ClassificationRule(pattern="status", classification=DataClass.PUBLIC)])
    label = _classify_field("status", "ok")
    assert label == "PUBLIC"


def test_secret_classification_label() -> None:
    register_classification_rules(
        [ClassificationRule(pattern="api_token", classification=DataClass.SECRET)]  # pragma: allowlist secret
    )
    label = _classify_field("api_token", "xyz")
    assert label == "SECRET"  # pragma: allowlist secret
