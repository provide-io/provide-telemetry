# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Data classification engine — strippable governance module.

Registers a classification hook on the PII engine when rules are configured.
If this file is deleted, the PII engine runs unchanged (hook stays None).
"""

from __future__ import annotations

__all__ = [
    "ClassificationPolicy",
    "ClassificationRule",
    "DataClass",
    "classify_key",
    "get_classification_policy",
    "register_classification_rule",
    "register_classification_rules",
    "set_classification_policy",
]

import enum
import fnmatch
import threading
from dataclasses import dataclass
from typing import Any

from provide.telemetry import pii as pii_mod


class DataClass(enum.Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    PII = "PII"
    PHI = "PHI"
    PCI = "PCI"
    SECRET = "SECRET"  # pragma: allowlist secret  # noqa: S105


@dataclass(frozen=True, slots=True)
class ClassificationRule:
    pattern: str
    classification: DataClass


@dataclass(slots=True)
class ClassificationPolicy:
    PUBLIC: str = "pass"
    INTERNAL: str = "pass"
    PII: str = "redact"
    PHI: str = "drop"
    PCI: str = "hash"
    SECRET: str = "drop"  # pragma: allowlist secret  # noqa: S105


_lock = threading.Lock()
_rules: list[ClassificationRule] = []
_policy: ClassificationPolicy = ClassificationPolicy()


def _lookup_policy_action(label: str) -> str:
    """Return the action string for the given label from the active policy."""
    with _lock:
        return str(getattr(_policy, label, "pass"))


def register_classification_rules(rules: list[ClassificationRule]) -> None:
    """Add rules and install the classification hook on the PII engine."""
    with _lock:
        _rules.extend(rules)
    pii_mod._classification_hook = _classify_field
    pii_mod._policy_hook = _lookup_policy_action


def set_classification_policy(policy: ClassificationPolicy) -> None:
    """Replace the current classification policy."""
    global _policy
    with _lock:
        _policy = policy


def get_classification_policy() -> ClassificationPolicy:
    """Return the current classification policy."""
    with _lock:
        return _policy


def _classify_field(key: str, _value: Any) -> str | None:
    """Return the DataClass label for key if a rule matches, else None."""
    with _lock:
        for rule in _rules:
            if fnmatch.fnmatch(key, rule.pattern):
                return rule.classification.value
    return None


def classify_key(key: str, value: Any | None = None) -> DataClass | None:
    """Return the DataClass member for key if a rule matches, else None."""
    # `_classify_field` currently ignores the value (the `_value` underscore-
    # prefixed parameter is reserved for future value-sensitive rules). A
    # mutation that replaces `value` with `None` here is therefore observably
    # equivalent — pin the line so mutmut skips the equivalent variants.
    label = _classify_field(key, value)  # pragma: no mutate
    return DataClass(label) if label is not None else None


def _reset_classification_for_tests() -> None:
    """Reset all classification state and remove the hook (test helper)."""
    global _policy
    with _lock:
        _rules.clear()
        _policy = ClassificationPolicy()
    pii_mod._classification_hook = None
    pii_mod._policy_hook = None
