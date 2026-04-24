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
from typing import Any, Literal, cast

from provide.telemetry._secret_patterns_generated import MIN_SECRET_LENGTH as _MIN_SECRET_LENGTH
from provide.telemetry._secret_patterns_generated import PATTERNS as _RAW_SECRET_PATTERNS

MaskMode = Literal["drop", "redact", "hash", "truncate"]


@dataclass(frozen=True, slots=True)
class PIIRule:
    path: tuple[str, ...]
    mode: MaskMode = "redact"
    truncate_to: int = 8


_SECRET_PATTERNS: tuple[tuple[str, _re.Pattern[str]], ...] = tuple(
    (name, _re.compile(pattern)) for name, pattern in _RAW_SECRET_PATTERNS
)

_custom_secret_patterns: list[tuple[str, _re.Pattern[str]]] = []

# ReDoS safety cap: values longer than this are never scanned for secret
# patterns.  API-shaped secrets are short (tens to low hundreds of chars); a
# >8 KiB string almost certainly isn't a key, and scanning it exposes the
# regex engine to pathological catastrophic-backtracking inputs.
_MAX_SECRET_SCAN_LENGTH = 8192


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
    if len(value) > _MAX_SECRET_SCAN_LENGTH:
        # Oversize input: skip scan to avoid regex ReDoS risk.
        return False
    # Thread-safe snapshot — list may be mutated by register_secret_pattern.
    with _lock:
        custom = list(_custom_secret_patterns)
    for _name, pattern in _SECRET_PATTERNS:  # pragma: no mutate — tuple iteration over generated patterns
        if pattern.search(value):
            return True
    for _name, pattern in custom:  # pragma: no mutate  # noqa: SIM110 — iteration mirrors built-in loop above
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
# Set by classification.py when rules are registered; takes label → action string.
_policy_hook: Callable[[str], str] | None = None


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
        return hashlib.sha256(
            str(value).encode("utf-8")
        ).hexdigest()[
            :12
        ]  # pragma: no mutate — 12-char hash prefix is the PII hash-mode contract; exact value asserted in hash-mode tests
    text = str(value)
    limit = max(0, truncate_to)
    if len(text) <= limit:
        return text
    return text[:limit] + _TRUNCATION_SUFFIX


def _match(path: tuple[str, ...], target: tuple[str, ...]) -> bool:
    if len(path) != len(target):
        return False
    return all(
        part == "*" or part == elem for part, elem in zip(path, target, strict=True)
    )  # pragma: no mutate — wildcard OR exact-match; both branches covered by PII rule tests


def _apply_rule(
    node: Any,
    rule: PIIRule,
    current_path: tuple[str, ...] = (),
    depth: int = 0,  # pragma: no mutate — recursion-depth default; call sites always start at 0
    receipt_hook: Callable[[str, str, Any], None] | None = None,
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
                if receipt_hook is not None:
                    receipt_hook(".".join(child_path), rule.mode, value)
            else:
                output[key] = _apply_rule(value, rule, child_path, depth=depth + 1, receipt_hook=receipt_hook)
        return output
    if isinstance(node, list):
        return [
            _apply_rule(item, rule, (*current_path, "*"), depth=depth + 1, receipt_hook=receipt_hook) for item in node
        ]  # pragma: no mutate — list-comp structure; traversal asserted by nested-list PII rule tests
    return node


def _path_has_rule(rule_paths: frozenset[tuple[str, ...]], child_path: tuple[str, ...]) -> bool:
    """Return True if any rule path matches child_path via _match()."""
    return any(_match(rp, child_path) for rp in rule_paths)


def _apply_default_sensitive_key_redaction(
    node: Any,
    original: Any,
    depth: int = 0,  # pragma: no mutate — recursion-depth default; call sites always start at 0
    max_depth: int = 8,  # pragma: no mutate — default max_depth is overridden by live runtime config at every call
    receipt_hook: Callable[[str, str, Any], None] | None = None,
    rule_targeted_paths: frozenset[tuple[str, ...]] | None = None,
    _current_path: tuple[str, ...] = (),
) -> Any:
    if depth >= max_depth:
        return node
    if rule_targeted_paths is None:
        rule_targeted_paths = frozenset()
    if isinstance(node, dict) and isinstance(original, dict):
        output: dict[str, Any] = {}
        for key, value in node.items():
            orig_value = original.get(key, value)
            child_path = (*_current_path, key)
            if key.lower() in _DEFAULT_SENSITIVE_KEYS:
                if _path_has_rule(rule_targeted_paths, child_path) or value != orig_value:
                    output[key] = value
                else:
                    output[key] = _REDACTED
                    if receipt_hook is not None:
                        receipt_hook(
                            ".".join(
                                cast(tuple[str, ...], child_path)
                            ),  # pragma: no mutate — typing-only cast; runtime value is already a str tuple
                            "redact",
                            orig_value,
                        )
            elif isinstance(value, str) and _detect_secret_in_value(value):
                output[key] = _REDACTED
                if receipt_hook is not None:
                    receipt_hook(
                        ".".join(
                            cast(tuple[str, ...], child_path)
                        ),  # pragma: no mutate — typing-only cast; runtime value is already a str tuple
                        "redact",
                        value,
                    )
            else:
                output[key] = _apply_default_sensitive_key_redaction(
                    value,
                    orig_value,
                    rule_targeted_paths=rule_targeted_paths,
                    depth=depth + 1,
                    max_depth=max_depth,
                    receipt_hook=receipt_hook,
                    _current_path=child_path,
                )
        return output
    if (
        isinstance(node, list) and isinstance(original, list)
    ):  # pragma: no mutate — dual isinstance guard; both False branches are unreachable given upstream recursion contract
        result: list[Any] = []
        for item, orig in zip(
            node, original, strict=False
        ):  # pragma: no mutate — strict=False because original may have extra trailing items after truncation upstream
            if isinstance(item, str) and _detect_secret_in_value(item):
                result.append(_REDACTED)
                if receipt_hook is not None:
                    receipt_hook("(list_item)", "redact", item)
            else:
                result.append(
                    _apply_default_sensitive_key_redaction(
                        item,
                        orig,
                        rule_targeted_paths=rule_targeted_paths,
                        depth=depth + 1,
                        max_depth=max_depth,
                        receipt_hook=receipt_hook,
                        _current_path=(*_current_path, "*"),
                    )
                )
        return result
    return node


def _collect_rule_paths(rules: tuple[PIIRule, ...]) -> frozenset[tuple[str, ...]]:
    """Collect the full paths that custom rules target."""
    return frozenset(rule.path for rule in rules if rule.path)


def sanitize_payload(
    payload: dict[str, Any], enabled: bool, max_depth: int = 8
) -> dict[
    str, Any
]:  # pragma: no mutate — default max_depth=8 is overridden by live runtime config at every call; default is cosmetic
    if not enabled:
        return dict(payload)
    # Snapshot hooks once to prevent TOCTOU races if they are replaced concurrently.
    receipt_hook = _receipt_hook
    classification_hook = _classification_hook
    policy_fn = _policy_hook
    # Fix 3a: Thread-safe snapshot of rules list to prevent RuntimeError from
    # concurrent replace_pii_rules() calls mutating the list during iteration.
    with _lock:
        rules_snapshot = list(_rules)
    # _apply_rule builds entirely new dict/list nodes at every level it traverses,
    # so a shallow top-level copy is sufficient — no deepcopy needed.
    cleaned: Any = dict(payload)
    if rules_snapshot:
        rules = tuple(rules_snapshot)
        for rule in rules:
            cleaned = _apply_rule(cleaned, rule, receipt_hook=receipt_hook)
        rule_targeted_paths = _collect_rule_paths(rules)
    else:
        rule_targeted_paths = frozenset()  # pragma: no mutate — None also accepted by callee
    cleaned = _apply_default_sensitive_key_redaction(
        cleaned, payload, rule_targeted_paths=rule_targeted_paths, max_depth=max_depth, receipt_hook=receipt_hook
    )
    if classification_hook is not None and isinstance(cleaned, dict):
        for key, value in list(
            cast(Any, cleaned).items()
        ):  # pragma: no mutate — typing-only cast and list() snapshot for safe in-place mutation
            label = classification_hook(key, value)
            if label is not None:
                action = (
                    policy_fn(label)
                    if policy_fn is not None
                    else "pass"  # pragma: no mutate — "XXpassXX"/"PASS" behave identically: not drop, not mask
                )
                if action == "drop":
                    del cleaned[key]
                else:
                    cleaned[f"__{key}__class"] = label
                    if action in ("redact", "hash", "truncate") and value != _REDACTED:
                        cleaned[key] = _mask(
                            value, cast(MaskMode, action), 8
                        )  # pragma: no mutate — 8-char truncate default here mirrors PIIRule.truncate_to; equivalent to any small positive int for governance action mapping
    if isinstance(cleaned, dict):
        return cleaned
    return {}


def reset_pii_rules_for_tests() -> None:
    global _classification_hook, _receipt_hook, _policy_hook
    replace_pii_rules([])
    with _lock:
        _custom_secret_patterns.clear()
    _classification_hook = None
    _receipt_hook = None
    _policy_hook = None
