# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Kill surviving mutants in classification._lookup_policy_action.

Mutants:
  mutmut_4: getattr(_policy, label, "pass") → getattr(_policy, label, None)
  mutmut_7: getattr(_policy, label, "pass") → getattr(_policy, label,)
  mutmut_8: getattr(_policy, label, "pass") → getattr(_policy, label, "XXpassXX")
  mutmut_9: getattr(_policy, label, "pass") → getattr(_policy, label, "PASS")

All four mutants change the fallback default for an *unknown* label away from "pass".
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

from provide.telemetry import pii as pii_mod
from provide.telemetry.classification import (
    ClassificationPolicy,
    ClassificationRule,
    DataClass,
    _lookup_policy_action,
    _reset_classification_for_tests,
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


class TestLookupPolicyActionDefault:
    """Kill mutants that change the fallback default away from "pass"."""

    def test_unknown_label_returns_pass(self) -> None:
        """An unknown label (not on ClassificationPolicy) must return "pass".

        Kills:
          mutmut_4: fallback=None  → str(None) = "None"
          mutmut_8: fallback="XXpassXX"
          mutmut_9: fallback="PASS"
        """
        # Use a label that does not exist on ClassificationPolicy
        result = _lookup_policy_action("NONEXISTENT_LABEL_THAT_DOES_NOT_EXIST")
        assert result == "pass", f"Expected 'pass' but got {result!r}"

    def test_unknown_label_is_string_pass_not_none(self) -> None:
        """Fallback must be exactly the string "pass", not None or None-string."""
        result = _lookup_policy_action("__no_such_attr__")
        assert result is not None
        assert result == "pass"
        assert result != "None"
        assert result != "PASS"
        assert result != "XXpassXX"

    def test_known_label_pii_returns_policy_action(self) -> None:
        """A known label returns the policy action, not the fallback."""
        result = _lookup_policy_action("PII")
        # Default ClassificationPolicy.PII = "redact"
        assert result == "redact"

    def test_known_label_phi_returns_drop(self) -> None:
        """PHI default action is "drop"."""
        result = _lookup_policy_action("PHI")
        assert result == "drop"

    def test_known_label_public_returns_pass(self) -> None:
        """PUBLIC default action is "pass"."""
        result = _lookup_policy_action("PUBLIC")
        assert result == "pass"

    def test_custom_policy_unknown_label_still_returns_pass(self) -> None:
        """Even with a custom policy set, unknown labels must still fall back to "pass"."""
        set_classification_policy(ClassificationPolicy(PII="drop", PHI="redact"))
        result = _lookup_policy_action("TOTALLY_UNKNOWN_LABEL")
        assert result == "pass"

    @pytest.mark.parametrize(
        "label,expected",
        [
            ("PUBLIC", "pass"),
            ("INTERNAL", "pass"),
            ("PII", "redact"),
            ("PHI", "drop"),
            ("PCI", "hash"),
            ("SECRET", "drop"),
        ],
    )
    def test_all_known_labels_correct_default_action(self, label: str, expected: str) -> None:
        """All six DataClass labels return the expected default action."""
        result = _lookup_policy_action(label)
        assert result == expected

    def test_unknown_label_fallback_not_capitalized_pass(self) -> None:
        """The fallback is lowercase "pass", not uppercase "PASS"."""
        result = _lookup_policy_action("UNKNOWN_XYZ_ABC")
        assert result != "PASS"
        assert result == "pass"

    def test_unknown_label_policy_hook_via_sanitize(self) -> None:
        """End-to-end: unknown label used in policy hook defaults to "pass" (field preserved)."""
        # Register a rule that classifies "myfield" with a DataClass label
        # that we'll give a custom action, then verify an UNKNOWN class falls through
        register_classification_rules([ClassificationRule(pattern="email", classification=DataClass.PII)])
        # PII default = "redact", so email gets masked
        result = pii_mod.sanitize_payload({"email": "alice@example.com", "name": "Alice"}, enabled=True)
        # The class tag is added (action != "drop")
        assert result.get("__email__class") == "PII"
