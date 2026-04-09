# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""PII policy engine with nested traversal support."""

from __future__ import annotations

__all__ = [
    "MaskMode",
    "PIIRule",
    "get_pii_rules",
    "get_secret_patterns",
    "register_pii_rule",
    "register_secret_pattern",
    "replace_pii_rules",
    "sanitize_payload",
]

import hashlib
import re as _re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

MaskMode = Literal["drop", "redact", "hash", "truncate"]


@dataclass(frozen=True, slots=True)
class PIIRule:
    path: tuple[str, ...]
    mode: MaskMode = "redact"
    truncate_to: int = 8


_SECRET_PATTERNS: tuple[tuple[str, _re.Pattern[str]], ...] = (
    ("aws_key", _re.compile(r"(?:AKIA|ASIA)[A-Z0-9]{16}")),
    ("jwt", _re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("github_token", _re.compile(r"gh[pos]_[A-Za-z0-9_]{36,}")),
    ("long_hex", _re.compile(r"[0-9a-fA-F]{40,}")),
    ("long_base64", _re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")),
)


_MIN_SECRET_LENGTH = 20  # shortest pattern (AKIA + 16) is 20 chars

_custom_secret_patterns: list[tuple[str, _re.Pattern[str]]] = []


def register_secret_pattern(name: str, pattern: _re.Pattern[str]) -> None:
    """Register a custom secret detection pattern.

    If *name* already exists, the previous pattern is replaced (deduplication).
    The *name* is for diagnostics only and is not used during matching.
    """
    with _lock:
        for idx, (existing_name, _pat) in enumerate(_custom_secret_patterns):
            if existing_name == name:
                _custom_secret_patterns[idx] = (name, pattern)
                return
        _custom_secret_patterns.append((name, pattern))


def get_secret_patterns() -> tuple[tuple[str, _re.Pattern[str]], ...]:
    """Return all secret patterns (built-in and custom)."""
    with _lock:
        return _SECRET_PATTERNS + tuple(_custom_secret_patterns)


def _detect_secret_in_value(value: str) -> bool:
    """Return True if value matches a known secret pattern."""
    if len(value) < _MIN_SECRET_LENGTH:
        return False
    # GIL-safe snapshot of custom patterns list reference.
    custom = _custom_secret_patterns
    for _name, pattern in _SECRET_PATTERNS:  # pragma: no mutate
        if pattern.search(value):
            return True
    for _name, pattern in custom:  # pragma: no mutate  # noqa: SIM110
        if pattern.search(value):
            return True
    return False


_DEFAULT_SENSITIVE_KEYS = {
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "credential",
    "private_key",
    "ssn",
    "credit_card",
    "creditcard",
    "cvv",
    "pin",
    "account_number",
    "cookie",
}
_lock = threading.Lock()
_rules: list[PIIRule] = []

# Governance hooks — set by classification.py / receipts.py if present.
# None = feature not loaded (zero overhead).
_classification_hook: Callable[[str, Any], str | None] | None = None
_receipt_hook: Callable[[str, str, Any], None] | None = None


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
        return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]  # pragma: no mutate
    text = str(value)
    limit = max(0, truncate_to)
    if len(text) <= limit:
        return text
    return text[:limit] + _TRUNCATION_SUFFIX


def _match(path: tuple[str, ...], target: tuple[str, ...]) -> bool:
    if len(path) != len(target):
        return False
    return all(part == "*" or part == elem for part, elem in zip(path, target, strict=True))  # pragma: no mutate


def _apply_rule(
    node: Any,
    rule: PIIRule,
    current_path: tuple[str, ...] = (),
    depth: int = 0,  # pragma: no mutate
) -> Any:
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
                if _receipt_hook is not None:
                    _receipt_hook(".".join(child_path), rule.mode, value)
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
    depth: int = 0,  # pragma: no mutate
    max_depth: int = 8,  # pragma: no mutate
) -> Any:
    if depth >= max_depth:
        return node
    if rule_targeted_keys is None:
        rule_targeted_keys = frozenset()
    if isinstance(node, dict) and isinstance(original, dict):
        output: dict[str, Any] = {}
        for key, value in node.items():
            orig_value = original.get(key, value)
            if key.lower() in _DEFAULT_SENSITIVE_KEYS:
                if key in rule_targeted_keys or value != orig_value:
                    output[key] = value
                else:
                    output[key] = _REDACTED
                    if _receipt_hook is not None:
                        _receipt_hook(key, "redact", orig_value)
            elif isinstance(value, str) and _detect_secret_in_value(value):
                output[key] = _REDACTED
                if _receipt_hook is not None:
                    _receipt_hook(key, "redact", value)
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


def sanitize_payload(payload: dict[str, Any], enabled: bool, max_depth: int = 8) -> dict[str, Any]:  # pragma: no mutate
    if not enabled:
        return dict(payload)
    # GIL-safe snapshot: reading the list reference is atomic.  If no custom
    # rules are registered (common case), skip tuple copy + rule application.
    rules_snapshot = _rules
    # _apply_rule builds entirely new dict/list nodes at every level it traverses,
    # so a shallow top-level copy is sufficient — no deepcopy needed.
    cleaned: Any = dict(payload)
    if rules_snapshot:
        rules = tuple(rules_snapshot)
        for rule in rules:
            cleaned = _apply_rule(cleaned, rule)
        rule_targeted_keys = _collect_rule_leaf_keys(rules)
    else:
        rule_targeted_keys = frozenset()  # pragma: no mutate — None also accepted by callee
    cleaned = _apply_default_sensitive_key_redaction(cleaned, payload, rule_targeted_keys, max_depth=max_depth)
    if _classification_hook is not None and isinstance(cleaned, dict):
        for key, value in list(cleaned.items()):
            label = _classification_hook(key, value)
            if label is not None:
                cleaned[f"__{key}__class"] = label
    if isinstance(cleaned, dict):
        return cleaned
    return {}


def reset_pii_rules_for_tests() -> None:
    global _classification_hook, _receipt_hook
    replace_pii_rules([])
    with _lock:
        _custom_secret_patterns.clear()
    _classification_hook = None
    _receipt_hook = None
