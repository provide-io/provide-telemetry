# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for PII engine hook slots."""

from __future__ import annotations

from collections.abc import Generator

import pytest

from provide.telemetry import pii as pii_mod


@pytest.fixture(autouse=True)
def _reset() -> Generator[None, None, None]:
    pii_mod.reset_pii_rules_for_tests()
    yield
    pii_mod.reset_pii_rules_for_tests()


def test_classification_hook_defaults_to_none() -> None:
    assert pii_mod._classification_hook is None


def test_receipt_hook_defaults_to_none() -> None:
    assert pii_mod._receipt_hook is None


def test_classification_hook_called_per_key() -> None:
    calls: list[str] = []

    def _hook(k: str, v: object) -> str | None:
        calls.append(k)
        return None

    pii_mod._classification_hook = _hook
    pii_mod.sanitize_payload({"username": "alice", "email": "a@b.com"}, enabled=True)
    assert "username" in calls
    assert "email" in calls


def test_classification_hook_adds_class_tag() -> None:
    pii_mod._classification_hook = lambda k, v: "PII" if k == "email" else None
    result = pii_mod.sanitize_payload({"email": "a@b.com", "name": "Alice"}, enabled=True)
    assert result.get("__email__class") == "PII"
    assert "__name__class" not in result


def test_receipt_hook_called_on_default_sensitive_key() -> None:
    receipts: list[tuple[str, str, object]] = []
    pii_mod._receipt_hook = lambda path, action, orig: receipts.append((path, action, orig))
    pii_mod.sanitize_payload({"password": "s3cr3t"}, enabled=True)  # pragma: allowlist secret
    assert any(path == "password" and action == "redact" for path, action, _ in receipts)


def test_receipt_hook_called_on_custom_rule() -> None:
    from provide.telemetry.pii import PIIRule

    pii_mod.register_pii_rule(PIIRule(path=("email",), mode="hash"))
    receipts: list[tuple[str, str, object]] = []
    pii_mod._receipt_hook = lambda path, action, orig: receipts.append((path, action, orig))
    pii_mod.sanitize_payload({"email": "a@b.com"}, enabled=True)
    assert any("email" in path and action == "hash" for path, action, _ in receipts)


def test_receipt_hook_receives_original_value() -> None:
    originals: list[object] = []
    pii_mod._receipt_hook = lambda path, action, orig: originals.append(orig)
    pii_mod.sanitize_payload({"password": "my-secret-value"}, enabled=True)  # pragma: allowlist secret
    assert "my-secret-value" in originals


def test_receipt_hook_called_on_secret_detection() -> None:
    """Receipt hook fires when a value matches a secret pattern (not a key name match)."""
    receipts: list[tuple[str, str, object]] = []
    pii_mod._receipt_hook = lambda path, action, orig: receipts.append((path, action, orig))
    # Long hex string (40+ chars) triggers secret detection.
    secret_val = "a" * 40
    pii_mod.sanitize_payload({"log_entry": secret_val}, enabled=True)
    assert any(path == "log_entry" and action == "redact" for path, action, _ in receipts)


def test_hooks_reset_by_reset_pii_rules() -> None:
    pii_mod._classification_hook = lambda k, v: "PII"
    pii_mod._receipt_hook = lambda p, a, _: None
    pii_mod.reset_pii_rules_for_tests()
    assert pii_mod._classification_hook is None
    assert pii_mod._receipt_hook is None


def test_no_hooks_no_overhead() -> None:
    """With no hooks registered, sanitize_payload behaves identically to before."""
    result = pii_mod.sanitize_payload({"password": "secret", "name": "Alice"}, enabled=True)
    assert result["password"] == "***"
    assert result["name"] == "Alice"
    assert not any(k.startswith("__") for k in result)


def test_receipt_hook_custom_rule_receives_original_value() -> None:
    """Verify custom rule receipt hook receives the original (pre-mask) value, not None."""
    from provide.telemetry.pii import PIIRule

    pii_mod.register_pii_rule(PIIRule(path=("email",), mode="hash"))
    receipts: list[tuple[str, str, object]] = []
    pii_mod._receipt_hook = lambda path, action, orig: receipts.append((path, action, orig))
    pii_mod.sanitize_payload({"email": "alice@example.com"}, enabled=True)
    matched = [r for r in receipts if "email" in r[0] and r[1] == "hash"]
    assert len(matched) >= 1
    assert matched[0][2] == "alice@example.com"


def test_receipt_hook_custom_rule_path_uses_dot_separator() -> None:
    """Verify receipt hook path joins segments with dots, not other separators."""
    from provide.telemetry.pii import PIIRule

    pii_mod.register_pii_rule(PIIRule(path=("user", "email"), mode="redact"))
    receipts: list[tuple[str, str, object]] = []
    pii_mod._receipt_hook = lambda path, action, orig: receipts.append((path, action, orig))
    pii_mod.sanitize_payload({"user": {"email": "alice@example.com"}}, enabled=True)
    matched = [r for r in receipts if r[1] == "redact"]
    assert len(matched) >= 1
    assert matched[0][0] == "user.email"


def test_receipt_hook_secret_detection_receives_original_value() -> None:
    """Verify secret-detection receipt hook receives the original value, not None."""
    receipts: list[tuple[str, str, object]] = []
    pii_mod._receipt_hook = lambda path, action, orig: receipts.append((path, action, orig))
    secret_val = "a" * 40  # triggers long_hex secret detection
    pii_mod.sanitize_payload({"log_entry": secret_val}, enabled=True)
    matched = [r for r in receipts if r[0] == "log_entry" and r[1] == "redact"]
    assert len(matched) >= 1
    assert matched[0][2] == secret_val


def test_classification_hook_receives_actual_value() -> None:
    """Verify classification hook receives the actual value, not None."""
    calls: list[tuple[str, object]] = []

    def _hook(k: str, v: object) -> str | None:
        calls.append((k, v))
        return None

    pii_mod._classification_hook = _hook
    pii_mod.sanitize_payload({"username": "alice"}, enabled=True)
    matched = [c for c in calls if c[0] == "username"]
    assert len(matched) >= 1
    assert matched[0][1] == "alice"
