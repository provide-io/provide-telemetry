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


# A slash-separated segment count and word shape that says "filesystem path".
# The long_base64 pattern is [A-Za-z0-9+/]{40,}, and "/" is in the base64
# alphabet, so any deep path of unpunctuated segments matches it:
# /home/deploy/apps/production/current/lib/service is 48 characters of pure
# base64 alphabet and contains no secret at all. Narrowing the charset is not
# the fix -- measured, dropping "/" costs 44% of detections on 32-byte secrets,
# the most common size there is, because a 44-char base64 string containing one
# slash is indistinguishable from a path BY CHARSET.
#
# Shape distinguishes them. A path has several short all-lowercase words (usr,
# local, lib); random base64 essentially never does -- a 20-character
# all-lowercase run has probability (26/64)^20, about 1e-8. Measured over 20k
# random secrets per size: detection stays 100% and 0.00-0.06% are suppressed.
_PATH_MIN_SEGMENTS = 3

# Token boundaries for _expand_to_token. `\S` is the exact complement of
# str.isspace() across the whole BMP, so switching from a hand-rolled
# character walk to these changed no behaviour.
_RUN_BEFORE_END = _re.compile(r"\S*\Z")
_RUN_FROM_POS = _re.compile(r"\S*")


def _looks_like_path(span: str) -> bool:
    """Return True if *span* has the shape of a filesystem path, not a secret."""
    segments = [segment for segment in span.split("/") if segment]
    if len(segments) < _PATH_MIN_SEGMENTS:
        return False
    wordy = sum(1 for segment in segments if segment.isalpha() and segment.islower())
    return wordy * 2 >= len(segments)


def _secret_spans(value: str) -> list[tuple[int, int]]:
    """Return every secret-looking span in *value*, merged and in order.

    Every pattern is scanned across the WHOLE value, not stopped at its first
    match, and every pattern is tried even after one has hit. Both halves
    matter, and skipping either leaks:

    * Stopping a pattern at its first match let a path shadow a real secret.
      long_base64 matches a path first; suppressing that match as path-shaped
      moved the scan to the next pattern, and long_base64 is the last one, so
      the credential behind the path was never looked for at all.
    * Stopping at the first *pattern* to hit left a field's second and third
      secrets in the log, which whole-value blanking used to cover for free.

    The fast path is search(): a clean value -- nearly every log field -- pays
    one search() per pattern and allocates nothing, because finditer() is only
    entered once a pattern is known to match. Measured, that keeps the clean
    case at +0.3-10% rather than the +92% an unconditional finditer() costs.
    """
    if len(value) < _MIN_SECRET_LENGTH:
        return []
    if len(value) > _MAX_SECRET_SCAN_LENGTH:
        return []
    with _lock:
        custom = list(_custom_secret_patterns)
    # Two loops rather than one over (*builtin, *custom): a clean value is
    # nearly every log field, and building that tuple per call cost more than
    # the duplicated loop body. The span list is likewise only allocated once
    # something has actually matched.
    spans: list[tuple[int, int]] | None = None
    for patterns in (_SECRET_PATTERNS, custom):
        for _name, pattern in patterns:
            # search() is only a presence check -- it is what keeps a clean
            # value cheap. Once a pattern is known to match, finditer() walks
            # the whole value from the start so no later match is missed.
            if pattern.search(value) is None:
                continue
            if spans is None:
                spans = []
            for match in pattern.finditer(value):
                matched = match.group(0)
                # A registered pattern that can match the empty string carries
                # no secret; widening a zero-length match to its token would
                # redact a word for nothing.
                if not matched:
                    continue
                if not _looks_like_path(matched):
                    spans.append(_expand_to_token(value, *match.span()))
    if spans is None:
        return []
    return _merge_spans(spans)


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Sort and coalesce overlapping spans so each region is replaced once.

    Two patterns can match the same credential -- long_base64 and jwt both hit
    a JWT -- and after widening to the token they overlap exactly. Replacing
    each separately would emit "******".
    """
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        # `<` and `<=` are indistinguishable here, so the `<` mutant is
        # equivalent: every span has been widened to a whitespace-delimited
        # token, so one span's start is at least one whitespace character past
        # the previous span's end. start == previous end cannot occur.
        if merged and start <= merged[-1][1]:  # pragma: no mutate — see above
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return merged


def _expand_to_token(value: str, start: int, end: int) -> tuple[int, int]:
    """Widen a match to its whitespace-delimited token.

    Redacting only the literal match can leave part of a secret behind: the
    jwt pattern matches header.payload, and a JWT has THREE dot-separated
    parts, so the signature would survive untouched. Whitespace is the
    boundary a secret cannot cross without ceasing to be one token, so
    widening to it means a partial match still removes the whole credential
    while the words around it stay readable.

    The boundaries are found by anchored match rather than by walking an
    index. Index arithmetic here was the wrong tool twice over: a ``while``
    loop is one mutated assignment away from never terminating, and the
    ``range`` form that replaced it carried four separate constants whose
    off-by-one variants mostly cannot be told apart from the outside. The
    regexes say the thing directly -- the run of non-whitespace ending where
    the match begins, and the run starting where it ends.
    """
    # Both patterns can match empty, so neither call can return None -- but
    # nothing in the signature says so, and the repo runs two type checkers
    # that each need telling separately.
    return (
        _RUN_BEFORE_END.search(value, 0, start).start(),  # type: ignore[union-attr]  # ty: ignore[unresolved-attribute]
        _RUN_FROM_POS.match(value, end).end(),  # type: ignore[union-attr]  # ty: ignore[unresolved-attribute]
    )


def redact_secret_spans(value: str) -> str:
    """Replace every secret-looking SPAN of *value*, leaving the rest.

    Blanking the whole field destroys context that was never suspect: a
    remediation string that happened to contain a long path became "***" and
    stopped telling anyone what to run. For a value that IS a secret the span
    covers all of it, so that case is unchanged.

    Every span is replaced, not just the first. Whole-value blanking removed a
    field's second and third credentials for free, and scoping redaction to a
    token silently dropped that guarantee.
    """
    spans = _secret_spans(value)
    if not spans:
        return value
    return _replace_spans(value, spans)


def _replace_spans(value: str, spans: list[tuple[int, int]]) -> str:
    """Swap each span for the redaction sentinel.

    Walks the spans back to front so each replacement leaves the indices of
    the ones still to come untouched. Carrying a cursor forward instead needs
    a zero sentinel whose only wrong value, None, slices identically -- an
    unkillable mutant guarding nothing.
    """
    redacted = value
    for start, end in reversed(spans):
        redacted = redacted[:start] + _REDACTED + redacted[end:]
    return redacted


def _redact_if_secret(value: str) -> str | None:
    """Redacted form of *value*, or None when it holds no secret.

    One scan where the sanitize path used to do two. Asking
    _detect_secret_in_value and then redact_secret_spans ran the whole pattern
    sweep twice for every value carrying a credential, which got measurably
    worse once the sweep started collecting every match instead of stopping at
    the first.
    """
    spans = _secret_spans(value)
    if not spans:
        return None
    return _replace_spans(value, spans)


def _detect_secret_in_value(value: str) -> bool:
    """Return True if value holds a known secret.

    Shares _secret_spans with redaction rather than running its own loop. When
    the two disagreed the value was flagged and then not fully cleaned, which
    is exactly how a secret sitting behind a filesystem path escaped: this
    returned False because the only pattern that could match it had already
    been consumed by the path.

    The length guards and the ReDoS scan cap live in _secret_spans.
    """
    return bool(_secret_spans(value))


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
        if isinstance(value, str):
            text = value
        else:
            # Non-strings hash their RFC 8785 canonical JSON so every SDK spells
            # booleans, null, numbers and nested values identically. Imported
            # lazily: receipts imports this module.
            from provide.telemetry.receipts import canonical_json

            text = canonical_json(value)
        # Codec lookup is case-insensitive, so an "UTF-8" mutation is equivalent.
        encoded = text.encode("utf-8")  # pragma: no mutate — codec alias; 'UTF-8' selects the identical codec
        return hashlib.sha256(
            encoded
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
    # The length guard above means zip can never see a ragged pair, so every
    # mutation of `strict` here is provably equivalent. Kept as True to document
    # the invariant. The pragma needs a single-line statement to take effect.
    pairs = zip(path, target, strict=True)  # pragma: no mutate — length guard above means zip is never ragged
    return all(part == "*" or part == elem for part, elem in pairs)


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
                        joined = ".".join(cast(tuple[str, ...], child_path))  # pragma: no mutate — cast is identity
                        receipt_hook(
                            joined,
                            "redact",
                            orig_value,
                        )
            elif isinstance(value, str) and (redacted := _redact_if_secret(value)) is not None:
                # Span-scoped: only the secret-looking runs are replaced, so
                # the message around them survives.
                output[key] = redacted
                if receipt_hook is not None:
                    joined = ".".join(cast(tuple[str, ...], child_path))  # pragma: no mutate — cast is identity
                    receipt_hook(
                        joined,
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
            if isinstance(item, str) and (redacted := _redact_if_secret(item)) is not None:
                result.append(redacted)
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
        # typing.cast returns its second argument unchanged at runtime, so every
        # mutation of the type argument is provably equivalent.
        items = list(cast(Any, cleaned).items())  # pragma: no mutate — cast returns its argument unchanged at runtime
        for key, value in items:
            label = classification_hook(key, value)
            if label is not None:
                # The fallback is only ever compared against "drop" and the
                # mask actions, so any other string is provably equivalent.
                default_action = "pass"  # pragma: no mutate — only compared against 'drop' and the mask actions; any other string is equivalent
                action = policy_fn(label) if policy_fn is not None else default_action
                if action == "drop":
                    del cleaned[key]
                else:
                    cleaned[f"__{key}__class"] = label
                    if action in ("redact", "hash", "truncate") and value != _REDACTED:
                        mask_mode = cast(MaskMode, action)  # pragma: no mutate — runtime no-op
                        cleaned[key] = _mask(value, mask_mode, 8)
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
