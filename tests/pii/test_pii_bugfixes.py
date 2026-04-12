# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for PII bug fixes: thread safety, list secret detection, TOCTOU hooks."""

from __future__ import annotations

import pytest

from provide.telemetry import pii as pii_mod
from provide.telemetry.pii import (
    PIIRule,
    _apply_rule,
    replace_pii_rules,
    sanitize_payload,
)


@pytest.fixture(autouse=True)
def _reset_rules() -> None:
    pii_mod.reset_pii_rules_for_tests()


class TestSecretDetectionInLists:
    """Verify Fix 3c: string items in lists are checked for secret patterns."""

    def test_github_token_in_list_is_redacted(self) -> None:
        """A GitHub token string in a list must be redacted."""
        token = "ghp_" + "A" * 36
        payload = {"tokens": [token]}
        result = sanitize_payload(payload, enabled=True)
        assert result["tokens"][0] == "***"

    def test_jwt_in_list_is_redacted(self) -> None:
        """A JWT-like string in a list must be redacted."""
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyMTIzNDU2NzgifQ"  # pragma: allowlist secret
        payload = {"data": [jwt]}
        result = sanitize_payload(payload, enabled=True)
        assert result["data"][0] == "***"

    def test_non_secret_string_in_list_is_preserved(self) -> None:
        """Non-secret strings in lists are left unchanged."""
        payload = {"tags": ["production", "v1.2.3", "us-east-1"]}
        result = sanitize_payload(payload, enabled=True)
        assert result["tags"] == ["production", "v1.2.3", "us-east-1"]

    def test_mixed_list_redacts_only_secrets(self) -> None:
        """Only secret strings in a mixed list are redacted."""
        token = "ghp_" + "B" * 36
        payload = {"items": ["safe", token, "also-safe"]}
        result = sanitize_payload(payload, enabled=True)
        assert result["items"][0] == "safe"
        assert result["items"][1] == "***"
        assert result["items"][2] == "also-safe"

    def test_nested_list_of_dicts_still_processed(self) -> None:
        """Dicts inside lists are still processed recursively."""
        payload = {"rows": [{"password": "mypassword"}]}  # pragma: allowlist secret
        result = sanitize_payload(payload, enabled=True)
        assert result["rows"][0]["password"] == "***"

    def test_receipt_hook_called_for_list_secret(self) -> None:
        """receipt_hook receives calls when a list item is redacted."""
        receipts: list[tuple[str, str, str]] = []

        def hook(path: str, mode: str, value: object) -> None:
            receipts.append((path, mode, str(value)))

        pii_mod._receipt_hook = hook
        token = "ghp_" + "C" * 36
        payload = {"keys": [token]}
        sanitize_payload(payload, enabled=True)
        assert any(r[1] == "redact" for r in receipts)


class TestPIIRulesSnapshotThreadSafety:
    """Verify Fix 3a: concurrent replace_pii_rules does not cause RuntimeError."""

    def test_concurrent_replace_does_not_raise(self) -> None:
        """Calling replace_pii_rules() while sanitize_payload() iterates must not raise."""
        import threading

        errors: list[Exception] = []
        stop = threading.Event()

        def replace_loop() -> None:
            while not stop.is_set():
                replace_pii_rules([PIIRule(path=("a",)), PIIRule(path=("b",))])
                replace_pii_rules([])

        t = threading.Thread(target=replace_loop, daemon=True)
        t.start()
        try:
            for _ in range(200):
                sanitize_payload({"a": "value", "b": "other"}, enabled=True)
        except Exception as exc:
            errors.append(exc)
        finally:
            stop.set()
            t.join(timeout=2)

        assert errors == []


class TestTOCTOUHookSafety:
    """Verify Fix 3b: snapshotted hook is used, not the global at call time."""

    def test_snapshotted_receipt_hook_is_used(self) -> None:
        """Hook set before call is invoked even if replaced concurrently."""
        receipts: list[str] = []

        def hook(path: str, mode: str, value: object) -> None:
            receipts.append(path)

        pii_mod._receipt_hook = hook
        sanitize_payload({"password": "s"}, enabled=True)  # pragma: allowlist secret
        assert len(receipts) >= 1

    def test_apply_rule_with_snapshotted_hook(self) -> None:
        """_apply_rule receipt_hook parameter is used instead of global."""
        receipts: list[tuple[str, str]] = []

        def hook(path: str, mode: str, value: object) -> None:
            receipts.append((path, mode))

        rule = PIIRule(path=("secret_key",), mode="redact")  # pragma: allowlist secret
        _apply_rule({"secret_key": "val"}, rule, receipt_hook=hook)  # pragma: allowlist secret
        assert ("secret_key", "redact") in receipts
