#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Data governance: consent levels, data classification, and redaction receipts.

Demonstrates:
  1. ConsentLevel — gate signal collection per user consent tier
  2. Data classification — label fields by sensitivity class; pair with PIIRules for enforcement
  3. RedactionReceipts — cryptographic audit trail for every PII redaction
"""

from __future__ import annotations

from provide.telemetry import (
    event,
    get_logger,
    register_pii_rule,
    setup_telemetry,
    shutdown_telemetry,
)
from provide.telemetry.classification import (
    ClassificationRule,
    DataClass,
    register_classification_rules,
)
from provide.telemetry.consent import ConsentLevel, set_consent_level, should_allow
from provide.telemetry.pii import PIIRule, sanitize_payload
from provide.telemetry.receipts import enable_receipts, get_emitted_receipts_for_tests


def demo_consent() -> None:
    print("── 1. Consent Levels ──────────────────────────────────────")
    for level in ConsentLevel:
        set_consent_level(level)
        logs_debug = should_allow("logs", "DEBUG")
        logs_error = should_allow("logs", "ERROR")
        traces = should_allow("traces")
        metrics = should_allow("metrics")
        ctx = should_allow("context")
        print(
            f"  {level.value:<12} "
            f"logs(DEBUG)={logs_debug!s:<5} "
            f"logs(ERROR)={logs_error!s:<5} "
            f"traces={traces!s:<5} "
            f"metrics={metrics!s:<5} "
            f"context={ctx}"
        )
    set_consent_level(ConsentLevel.FULL)
    print()


def demo_classification() -> None:
    print("── 2. Data Classification ─────────────────────────────────")
    # Register rules: pattern → DataClass label
    register_classification_rules(
        [
            ClassificationRule(pattern="ssn", classification=DataClass.PII),
            ClassificationRule(pattern="card_number", classification=DataClass.PCI),
            ClassificationRule(pattern="diagnosis", classification=DataClass.PHI),
            ClassificationRule(pattern="api_*", classification=DataClass.SECRET),
        ]
    )
    # Classification adds __key__class labels to sanitized output.
    # Enforcement (drop, hash, redact) is applied by registering PIIRules per class.
    register_pii_rule(PIIRule(path=("ssn",), mode="redact"))
    register_pii_rule(PIIRule(path=("card_number",), mode="hash"))
    register_pii_rule(PIIRule(path=("diagnosis",), mode="drop"))
    register_pii_rule(PIIRule(path=("api_key",), mode="drop"))

    payload = {
        "user": "alice",
        "ssn": "123-45-6789",
        "card_number": "4111111111111111",
        "diagnosis": "hypertension",
        "api_key": "sk-prod-abc123",  # pragma: allowlist secret
    }
    cleaned = sanitize_payload(payload, enabled=True)

    print("  Field values after sanitization:")
    for k in payload:
        print(f"    {k}: {cleaned.get(k, '<dropped>')!r}")

    print("\n  Classification labels added to output:")
    for k, v in cleaned.items():
        if k.endswith("__class"):
            print(f"    {k}: {v!r}")
    print()


def demo_receipts() -> None:
    print("── 3. Redaction Receipts ──────────────────────────────────")
    # Enable test-mode receipt collection (in production, receipts are logged/forwarded)
    from provide.telemetry import receipts as _r

    _r._reset_receipts_for_tests()  # type: ignore[attr-defined]
    _r._test_mode = True  # type: ignore[attr-defined]
    enable_receipts(
        enabled=True,
        signing_key="demo-hmac-key",  # pragma: allowlist secret
        service_name="governance-demo",
    )

    register_pii_rule(PIIRule(path=("password",), mode="redact"))
    sanitize_payload({"user": "bob", "password": "s3cr3t"}, enabled=True)  # pragma: allowlist secret

    receipts = get_emitted_receipts_for_tests()
    if receipts:
        r = receipts[-1]
        print(f"  receipt_id:    {r.receipt_id}")
        print(f"  field_path:    {r.field_path}")
        print(f"  action:        {r.action}")
        print(f"  original_hash: {r.original_hash[:16]}...")
        print(f"  hmac:          {r.hmac[:16]}..." if r.hmac else "  hmac:          (unsigned)")
    enable_receipts(enabled=False)
    print()


def main() -> None:
    setup_telemetry()
    log = get_logger("governance-demo")
    log.info(event("governance", "demo", "start"))

    print("=== Data Governance Demo ===\n")
    demo_consent()
    demo_classification()
    demo_receipts()

    shutdown_telemetry()
    print("=== Done ===")


if __name__ == "__main__":
    main()
