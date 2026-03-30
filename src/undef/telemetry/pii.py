# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""PII policy engine with nested traversal support."""

from __future__ import annotations

import copy
import hashlib
import re as _re
import threading
from dataclasses import dataclass
from typing import Any, Literal

MaskMode = Literal["drop", "redact", "hash", "truncate"]


@dataclass(frozen=True, slots=True)
class PIIRule:
    path: tuple[str, ...]
    mode: MaskMode = "redact"
    truncate_to: int = 8


_SECRET_PATTERNS: tuple[tuple[str, _re.Pattern[str]], ...] = (
    ("aws_key", _re.compile(r"AKIA[0-9A-Z]{16}")),
    ("jwt", _re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("github_token", _re.compile(r"gh[pos]_[A-Za-z0-9_]{36,}")),
    ("long_hex", _re.compile(r"[0-9a-fA-F]{40,}")),
    ("long_base64", _re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")),
)


def _detect_secret_in_value(value: str) -> bool:
    """Return True if value matches a known secret pattern."""
    return any(pattern.search(value) for _name, pattern in _SECRET_PATTERNS)


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


def _apply_rule(node: Any, rule: PIIRule, current_path: tuple[str, ...] = (), depth: int = 0) -> Any:
    if depth >= 32:  # hard safety limit
        return node
    if isinstance(node, dict):
        output: dict[str, Any] = {}
        for key, value in node.items():
            child_path = (*current_path, key)
            if _match(rule.path, child_path):
                masked = _mask(value, rule.mode, rule.truncate_to)
                if masked is not None:
                    output[key] = masked
            else:
                output[key] = _apply_rule(value, rule, child_path, depth=depth + 1)
        return output
    if isinstance(node, list):
        return [_apply_rule(item, rule, (*current_path, "*"), depth=depth + 1) for item in node]  # pragma: no mutate
    return node


def _apply_default_sensitive_key_redaction(
    node: Any,
    original: Any,
    rule_targeted_keys: frozenset[str] | None = None,
    depth: int = 0,
    max_depth: int = 8,
) -> Any:
    if depth >= max_depth:
        return node
    if rule_targeted_keys is None:
        rule_targeted_keys = frozenset()
    if isinstance(node, dict) and isinstance(original, dict):
        output: dict[str, Any] = {}
        for key, value in node.items():
            if key.lower() in _DEFAULT_SENSITIVE_KEYS:
                if key in rule_targeted_keys or value != orig_value:
                    output[key] = value
                else:
                    output[key] = _REDACTED
            elif isinstance(value, str) and _detect_secret_in_value(value):
                output[key] = _REDACTED
            else:
                output[key] = _apply_default_sensitive_key_redaction(
                    value, orig_value, rule_targeted_keys, depth=depth + 1, max_depth=max_depth
                )
        return output
    if isinstance(node, list) and isinstance(original, list):  # pragma: no mutate
        return [
            _apply_default_sensitive_key_redaction(item, orig, rule_targeted_keys, depth=depth + 1, max_depth=max_depth)
            for item, orig in zip(node, original, strict=False)  # pragma: no mutate
        ]
    return node


def _collect_rule_leaf_keys(rules: tuple[PIIRule, ...]) -> frozenset[str]:
    """Collect the leaf key names that custom rules target."""
    return frozenset(rule.path[-1] for rule in rules if rule.path)


def _needs_deep_copy(rules: tuple[PIIRule, ...]) -> bool:  # pragma: no mutate
    """Return True if any rule targets a nested path (depth > 1)."""
    return any(len(rule.path) > 1 for rule in rules)  # pragma: no mutate


def sanitize_payload(payload: dict[str, Any], enabled: bool, max_depth: int = 8) -> dict[str, Any]:
    if not enabled:
        return dict(payload)
    rules = get_pii_rules()
    cleaned: Any = copy.deepcopy(payload) if _needs_deep_copy(rules) else dict(payload)  # pragma: no mutate
    for rule in rules:
        cleaned = _apply_rule(cleaned, rule)
    rule_targeted_keys = _collect_rule_leaf_keys(rules)
    cleaned = _apply_default_sensitive_key_redaction(cleaned, payload, rule_targeted_keys, max_depth=max_depth)
    if isinstance(cleaned, dict):
        return cleaned
    return {}


def reset_pii_rules_for_tests() -> None:
    replace_pii_rules([])
