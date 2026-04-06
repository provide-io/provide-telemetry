# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Integration tests for governance modules working together."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Generator

import pytest

from provide.telemetry import pii as pii_mod
from provide.telemetry.classification import (
    ClassificationRule,
    DataClass,
    _reset_classification_for_tests,
    register_classification_rules,
)
from provide.telemetry.consent import (
    ConsentLevel,
    _load_consent_from_env,
    _reset_consent_for_tests,
    set_consent_level,
    should_allow,
)
from provide.telemetry.receipts import (
    _reset_receipts_for_tests,
    enable_receipts,
    get_emitted_receipts_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_all() -> Generator[None, None, None]:
    """Reset PII rules, classification, consent, and receipts before each test."""
    pii_mod.reset_pii_rules_for_tests()
    _reset_classification_for_tests()
    _reset_consent_for_tests()
    _reset_receipts_for_tests()
    yield
    pii_mod.reset_pii_rules_for_tests()
    _reset_classification_for_tests()
    _reset_consent_for_tests()
    _reset_receipts_for_tests()


# ── Classification + PII integration ─────────────────────────────────────────


@pytest.mark.integration
def test_classification_hook_registers_and_tags_email_as_pii() -> None:
    """Register a classification rule for 'email' → PII and verify tag appears."""
    register_classification_rules([ClassificationRule(pattern="email", classification=DataClass.PII)])
    result = pii_mod.sanitize_payload({"email": "alice@example.com", "name": "Alice"}, enabled=True)
    assert result.get("__email__class") == "PII"
    assert "__name__class" not in result


@pytest.mark.integration
def test_wildcard_classification_tags_user_fields() -> None:
    """Register 'user_*' → PII. Verify user_id and user_name both get tagged."""
    register_classification_rules([ClassificationRule(pattern="user_*", classification=DataClass.PII)])
    result = pii_mod.sanitize_payload({"user_id": 42, "user_name": "Alice", "status": "ok"}, enabled=True)
    assert result.get("__user_id__class") == "PII"
    assert result.get("__user_name__class") == "PII"
    assert "__status__class" not in result


@pytest.mark.integration
def test_multiple_rules_first_match_wins() -> None:
    """First matching rule wins for overlapping patterns."""
    register_classification_rules(
        [
            ClassificationRule(pattern="email", classification=DataClass.PII),
            ClassificationRule(pattern="email", classification=DataClass.PHI),
        ]
    )
    result = pii_mod.sanitize_payload({"email": "alice@example.com"}, enabled=True)
    assert result.get("__email__class") == "PII"


# ── Consent integration ───────────────────────────────────────────────────────


@pytest.mark.integration
def test_consent_none_blocks_all_signals() -> None:
    """Set consent to NONE. Verify should_allow('logs', 'ERROR') is False."""
    set_consent_level(ConsentLevel.NONE)
    assert should_allow("logs", "ERROR") is False


@pytest.mark.integration
def test_consent_functional_allows_warning_blocks_info() -> None:
    """Set consent to FUNCTIONAL. WARNING passes, INFO does not."""
    set_consent_level(ConsentLevel.FUNCTIONAL)
    assert should_allow("logs", "WARNING") is True
    assert should_allow("logs", "INFO") is False


@pytest.mark.integration
def test_env_var_loads_minimal_consent(monkeypatch: pytest.MonkeyPatch) -> None:
    """PROVIDE_CONSENT_LEVEL=MINIMAL → level is MINIMAL after _load_consent_from_env."""
    monkeypatch.setenv("PROVIDE_CONSENT_LEVEL", "MINIMAL")
    _load_consent_from_env()
    from provide.telemetry.consent import get_consent_level

    assert get_consent_level() == ConsentLevel.MINIMAL


# ── Receipts + PII integration ────────────────────────────────────────────────


@pytest.mark.integration
def test_receipt_emitted_with_correct_field_and_action() -> None:
    """Enable receipts (test mode). Sanitize payload with 'password'. Receipt has correct field_path and action."""
    enable_receipts(enabled=True, signing_key=None, service_name="test-svc")
    pii_mod.sanitize_payload({"password": "s3cr3t"}, enabled=True)  # pragma: allowlist secret
    receipts = get_emitted_receipts_for_tests()
    assert any(r.field_path == "password" and r.action == "redact" for r in receipts)


@pytest.mark.integration
def test_receipt_original_hash_matches_sha256() -> None:
    """Receipt original_hash matches hashlib.sha256('value'.encode()).hexdigest()."""
    enable_receipts(enabled=True, signing_key=None)
    pii_mod.sanitize_payload({"password": "value"}, enabled=True)  # pragma: allowlist secret
    receipts = get_emitted_receipts_for_tests()
    assert len(receipts) == 1
    expected = hashlib.sha256(b"value").hexdigest()
    assert receipts[0].original_hash == expected


@pytest.mark.integration
def test_receipt_hmac_verification_with_signing_key() -> None:
    """HMAC verification succeeds with the correct signing key."""
    signing_key = "integration-test-key"  # pragma: allowlist secret
    enable_receipts(enabled=True, signing_key=signing_key)
    pii_mod.sanitize_payload({"password": "secret123"}, enabled=True)  # pragma: allowlist secret
    receipts = get_emitted_receipts_for_tests()
    assert len(receipts) == 1
    r = receipts[0]
    assert r.hmac != ""
    payload_str = f"{r.receipt_id}|{r.timestamp}|{r.field_path}|{r.action}|{r.original_hash}"
    expected_hmac = hmac.new(signing_key.encode("utf-8"), payload_str.encode("utf-8"), hashlib.sha256).hexdigest()
    assert r.hmac == expected_hmac


# ── Config masking integration ────────────────────────────────────────────────


@pytest.mark.integration
def test_config_repr_hides_otlp_header_secret() -> None:
    """TelemetryConfig repr() does not expose the OTLP header secret."""
    from provide.telemetry.config import LoggingConfig, TelemetryConfig

    secret = "super-secret-bearer-token"  # pragma: allowlist secret
    cfg = TelemetryConfig(
        logging=LoggingConfig(otlp_headers={"Authorization": f"Bearer {secret}"}),
    )
    text = repr(cfg)
    assert secret not in text
    assert "****" in text


@pytest.mark.integration
def test_config_repr_masks_metrics_header_secret() -> None:
    """TelemetryConfig repr() masks secrets in metrics OTLP headers."""
    from provide.telemetry.config import MetricsConfig, TelemetryConfig

    secret = "another-long-secret-value"  # pragma: allowlist secret
    cfg = TelemetryConfig(
        metrics=MetricsConfig(otlp_headers={"X-Api-Key": secret}),
    )
    text = repr(cfg)
    assert secret not in text
    assert "****" in text


# ── Strippability ─────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_core_functions_work_without_governance_modules() -> None:
    """Core imports (get_logger, setup_telemetry) work when governance modules not imported."""
    from provide.telemetry import get_logger, setup_telemetry

    log = get_logger("strippability-test")
    assert log is not None
    assert callable(setup_telemetry)


@pytest.mark.integration
def test_pii_engine_runs_without_governance_hooks() -> None:
    """PII engine sanitizes correctly when classification/consent/receipts not initialized."""
    # All hooks are None after reset (autouse fixture already reset them)
    assert pii_mod._classification_hook is None
    assert pii_mod._receipt_hook is None
    result = pii_mod.sanitize_payload({"password": "s3cr3t", "name": "Alice"}, enabled=True)  # pragma: allowlist secret
    assert result["password"] == "***"
    assert result["name"] == "Alice"
    assert not any(k.startswith("__") for k in result)
