# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""PII policy engine with nested traversal support."""

from __future__ import annotations

import copy
import hashlib
import threading
from dataclasses import dataclass
from typing import Any, Literal

MaskMode = Literal["drop", "redact", "hash", "truncate"]


@dataclass(frozen=True, slots=True)
class PIIRule:
    path: tuple[str, ...]
    mode: MaskMode = "redact"
    truncate_to: int = 8


_DEFAULT_SENSITIVE_KEYS = {"password", "token", "authorization", "api_key", "secret"}
_lock = threading.Lock()
_rules: list[PIIRule] = []


def replace_pii_rules(rules: list[PIIRule]) -> None:
    with _lock:
        _rules.clear()
        _rules.extend(rules)


def register_pii_rule(rule: PIIRule) -> None:
    with _lock:
        _rules.append(rule)


def get_pii_rules() -> tuple[PIIRule, ...]:
    with _lock:
        return tuple(_rules)


_REDACTED = "***"
_TRUNCATION_SUFFIX = "..."


def _mask(value: Any, mode: MaskMode, truncate_to: int) -> Any:
    if mode == "drop":
        return None
    if mode == "redact":
        return _REDACTED
    if mode == "hash":
        return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
    text = str(value)
    limit = max(0, truncate_to)
    if len(text) <= limit:
        return text
    return text[:limit] + _TRUNCATION_SUFFIX


def _match(path: tuple[str, ...], target: tuple[str, ...]) -> bool:
    if len(path) != len(target):
        return False
    return all(part == "*" or part == elem for part, elem in zip(path, target, strict=True))


def _apply_rule(node: Any, rule: PIIRule, current_path: tuple[str, ...] = ()) -> Any:
    if isinstance(node, dict):
        output: dict[str, Any] = {}
        for key, value in node.items():
            child_path = (*current_path, key)
            if _match(rule.path, child_path):
                masked = _mask(value, rule.mode, rule.truncate_to)
                if masked is not None:
                    output[key] = masked
            else:
                output[key] = _apply_rule(value, rule, child_path)
        return output
    if isinstance(node, list):
        return [_apply_rule(item, rule, (*current_path, "*")) for item in node]
    return node


def _apply_default_sensitive_key_redaction(node: Any) -> Any:
    if isinstance(node, dict):
        output: dict[str, Any] = {}
        for key, value in node.items():
            if key.lower() in _DEFAULT_SENSITIVE_KEYS:
                if key in rule_targeted_keys or value != orig_value:
                    output[key] = value
                else:
                    output[key] = _REDACTED
            else:
                output[key] = _apply_default_sensitive_key_redaction(value)
        return output
    if isinstance(node, list):
        return [_apply_default_sensitive_key_redaction(item) for item in node]
    return node


def _collect_rule_leaf_keys(rules: tuple[PIIRule, ...]) -> frozenset[str]:
    """Collect the leaf key names that custom rules target."""
    return frozenset(rule.path[-1] for rule in rules if rule.path)


def _needs_deep_copy(rules: tuple[PIIRule, ...]) -> bool:  # pragma: no mutate
    """Return True if any rule targets a nested path (depth > 1)."""
    return any(len(rule.path) > 1 for rule in rules)  # pragma: no mutate


def sanitize_payload(payload: dict[str, Any], enabled: bool) -> dict[str, Any]:
    if not enabled:
        return dict(payload)
    rules = get_pii_rules()
    cleaned: Any = copy.deepcopy(payload) if _needs_deep_copy(rules) else dict(payload)  # pragma: no mutate
    for rule in rules:
        cleaned = _apply_rule(cleaned, rule)
    if isinstance(cleaned, dict):
        return cleaned
    return {}


def reset_pii_rules_for_tests() -> None:
    replace_pii_rules([])
