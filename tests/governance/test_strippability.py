# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Strippability contract: governance modules must not affect core when absent."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Generator

import pytest

from provide.telemetry import pii as pii_mod

_GOVERNANCE_MODULES = frozenset(
    {
        "provide.telemetry.classification",
        "provide.telemetry.consent",
        "provide.telemetry.receipts",
    }
)


@pytest.fixture(autouse=True)
def _reset_hooks() -> Generator[None, None, None]:
    """Reset PII hooks before and after each test."""
    pii_mod.reset_pii_rules_for_tests()
    yield
    pii_mod.reset_pii_rules_for_tests()


def test_pii_works_without_classification_hook() -> None:
    """With _classification_hook = None, sanitize_payload produces no __*__class tags."""
    assert pii_mod._classification_hook is None
    result = pii_mod.sanitize_payload(
        {"username": "alice", "email": "a@b.com", "password": "s3cr3t"},  # pragma: allowlist secret
        enabled=True,
    )
    assert result["username"] == "alice"
    assert result["password"] == "***"
    class_tags = [k for k in result if k.endswith("__class")]
    assert not class_tags, f"Unexpected classification tags found: {class_tags}"


def test_pii_works_without_receipt_hook() -> None:
    """With _receipt_hook = None, sanitize_payload doesn't raise and core redaction works."""
    assert pii_mod._receipt_hook is None
    result = pii_mod.sanitize_payload(
        {"password": "s3cr3t", "name": "Bob"},  # pragma: allowlist secret
        enabled=True,
    )
    assert result["password"] == "***"
    assert result["name"] == "Bob"


def _fresh_import_modules() -> set[str]:
    """Import provide.telemetry in a fresh state and return newly loaded module names."""
    import provide

    to_remove = [k for k in sys.modules if k.startswith("provide.telemetry")]
    saved = {k: sys.modules.pop(k) for k in to_remove}
    old_telemetry_attr = getattr(provide, "telemetry", None)
    try:
        before = set(sys.modules.keys())
        importlib.import_module("provide.telemetry")
        after = set(sys.modules.keys())
        return {m for m in (after - before) if m.startswith("provide.telemetry")}
    finally:
        for k in list(sys.modules):
            if k.startswith("provide.telemetry"):
                del sys.modules[k]
        sys.modules.update(saved)
        if old_telemetry_attr is not None:
            provide.telemetry = old_telemetry_attr


def test_classification_module_not_auto_imported() -> None:
    """Importing provide.telemetry must NOT load provide.telemetry.classification."""
    loaded = _fresh_import_modules()
    assert "provide.telemetry.classification" not in loaded


def test_consent_module_not_auto_imported() -> None:
    """Importing provide.telemetry must NOT load provide.telemetry.consent."""
    loaded = _fresh_import_modules()
    assert "provide.telemetry.consent" not in loaded


def test_receipts_module_not_auto_imported() -> None:
    """Importing provide.telemetry must NOT load provide.telemetry.receipts."""
    loaded = _fresh_import_modules()
    assert "provide.telemetry.receipts" not in loaded


def test_governance_modules_absent_from_lazy_registry_until_accessed() -> None:
    """Governance module symbols are in _LAZY_REGISTRY (opt-in) and not loaded on bare import."""
    from provide.telemetry import _LAZY_REGISTRY

    # Verify governance symbols ARE registered (they're opt-in, not absent)
    assert "register_classification_rule" in _LAZY_REGISTRY
    assert "register_classification_rules" in _LAZY_REGISTRY
    assert "classify_key" in _LAZY_REGISTRY
    assert "get_consent_level" in _LAZY_REGISTRY
    assert "enable_receipts" in _LAZY_REGISTRY

    # Verify governance modules are NOT eagerly loaded by a fresh provide.telemetry import
    loaded_on_fresh_import = _fresh_import_modules()
    for mod_name in _GOVERNANCE_MODULES:
        assert mod_name not in loaded_on_fresh_import, (
            f"{mod_name} was eagerly loaded on bare import of provide.telemetry"
        )


def test_identical_output_without_governance() -> None:
    """sanitize_payload output is identical regardless of whether governance modules are imported.

    Without classification hook: no __*__class tags appear.
    The redacted fields must be identical.
    """
    payload = {
        "username": "alice",
        "email": "a@b.com",
        "password": "s3cr3t",  # pragma: allowlist secret
        "note": "hello",
    }

    # Run without any hook (governance not loaded)
    assert pii_mod._classification_hook is None
    assert pii_mod._receipt_hook is None
    result_without = pii_mod.sanitize_payload(payload, enabled=True)

    # Simulate what classification hook adds (classification tag), then compare core fields
    pii_mod._classification_hook = lambda k, v: "PII" if k == "email" else None
    result_with = pii_mod.sanitize_payload(payload, enabled=True)

    # Core redacted fields must be identical
    core_keys = {k for k in result_without if not k.startswith("__")}
    for key in core_keys:
        assert result_without[key] == result_with[key], (
            f"Key {key!r} differs: {result_without[key]!r} vs {result_with[key]!r}"
        )

    # Without classification hook, no __*__class tags
    assert not any(k.endswith("__class") for k in result_without)

    # With classification hook, class tag appears
    assert result_with.get("__email__class") == "PII"
