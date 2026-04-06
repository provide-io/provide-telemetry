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
    "get_classification_policy",
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


def register_classification_rules(rules: list[ClassificationRule]) -> None:
    """Add rules and install the classification hook on the PII engine."""
    with _lock:
        _rules.extend(rules)
    pii_mod._classification_hook = _classify_field


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


def _reset_classification_for_tests() -> None:
    """Reset all classification state and remove the hook (test helper)."""
    global _policy
    with _lock:
        _rules.clear()
        _policy = ClassificationPolicy()
    pii_mod._classification_hook = None
