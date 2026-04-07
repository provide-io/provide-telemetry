// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// 14_data_governance — consent levels, data classification, and redaction receipts.
//
// Demonstrates:
//  1. ConsentLevel — gate signal collection per user consent tier
//  2. Data classification — label fields by sensitivity class; pair with PIIRules for enforcement
//  3. RedactionReceipts — cryptographic audit trail for every PII redaction
package main

import (
	"context"
	"fmt"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

func demoConsent() {
	fmt.Println("── 1. Consent Levels ──────────────────────────────────────")
	levels := []struct {
		level telemetry.ConsentLevel
		name  string
	}{
		{telemetry.ConsentFull, "FULL"},
		{telemetry.ConsentFunctional, "FUNCTIONAL"},
		{telemetry.ConsentMinimal, "MINIMAL"},
		{telemetry.ConsentNone, "NONE"},
	}
	for _, l := range levels {
		telemetry.SetConsentLevel(l.level)
		logsDebug := telemetry.ShouldAllow("logs", "DEBUG")
		logsError := telemetry.ShouldAllow("logs", "ERROR")
		traces := telemetry.ShouldAllow("traces", "")
		metrics := telemetry.ShouldAllow("metrics", "")
		ctx := telemetry.ShouldAllow("context", "")
		fmt.Printf("  %-12s logs(DEBUG)=%-5v logs(ERROR)=%-5v traces=%-5v metrics=%-5v context=%v\n",
			l.name, logsDebug, logsError, traces, metrics, ctx)
	}
	telemetry.SetConsentLevel(telemetry.ConsentFull)
	fmt.Println()
}

func demoClassification() {
	fmt.Println("── 2. Data Classification ─────────────────────────────────")
	// Register rules: pattern → DataClass label
	telemetry.RegisterClassificationRules([]telemetry.ClassificationRule{
		{Pattern: "ssn", Classification: telemetry.DataClassPII},
		{Pattern: "card_number", Classification: telemetry.DataClassPCI},
		{Pattern: "diagnosis", Classification: telemetry.DataClassPHI},
		{Pattern: "api_*", Classification: telemetry.DataClassSecret},
	})
	// Classification adds __key__class labels to sanitized output.
	// Enforcement (drop, hash, redact) is applied by registering PIIRules per class.
	telemetry.RegisterPIIRule(telemetry.PIIRule{Path: []string{"ssn"}, Mode: telemetry.PIIModeRedact})
	telemetry.RegisterPIIRule(telemetry.PIIRule{Path: []string{"card_number"}, Mode: telemetry.PIIModeHash})
	telemetry.RegisterPIIRule(telemetry.PIIRule{Path: []string{"diagnosis"}, Mode: telemetry.PIIModeDrop})
	telemetry.RegisterPIIRule(telemetry.PIIRule{Path: []string{"api_key"}, Mode: telemetry.PIIModeDrop})

	payload := map[string]any{
		"user":        "alice",
		"ssn":         "123-45-6789",
		"card_number": "4111111111111111",
		"diagnosis":   "hypertension",
		"api_key":     "sk-prod-abc123", //nolint:gosec // demo only
	}
	cleaned := telemetry.SanitizePayload(payload, true, 0)

	fmt.Println("  Field values after sanitization:")
	for _, k := range []string{"user", "ssn", "card_number", "diagnosis", "api_key"} {
		if v, ok := cleaned[k]; ok {
			fmt.Printf("    %s: %q\n", k, fmt.Sprintf("%v", v))
		} else {
			fmt.Printf("    %s: <dropped>\n", k)
		}
	}

	fmt.Println("\n  Classification labels added to output:")
	for k, v := range cleaned {
		if len(k) > 7 && k[len(k)-7:] == "__class" {
			fmt.Printf("    %s: %q\n", k, v)
		}
	}
	fmt.Println()
}

func demoReceipts() {
	fmt.Println("── 3. Redaction Receipts ──────────────────────────────────")
	// ResetReceiptsForTests enables in-process receipt collection (test mode).
	telemetry.ResetReceiptsForTests()
	telemetry.EnableReceipts(true, "demo-hmac-key", "governance-demo") //nolint:gosec // demo only

	telemetry.RegisterPIIRule(telemetry.PIIRule{Path: []string{"password"}, Mode: telemetry.PIIModeRedact})
	telemetry.SanitizePayload(map[string]any{
		"user":     "bob",
		"password": "s3cr3t", //nolint:gosec // demo only
	}, true, 0)

	receipts := telemetry.GetEmittedReceiptsForTests()
	if len(receipts) > 0 {
		r := receipts[len(receipts)-1]
		fmt.Printf("  receipt_id:    %s\n", r.ReceiptID)
		fmt.Printf("  field_path:    %s\n", r.FieldPath)
		fmt.Printf("  action:        %s\n", r.Action)
		fmt.Printf("  original_hash: %s...\n", r.OriginalHash[:16])
		if r.HMAC != "" {
			fmt.Printf("  hmac:          %s...\n", r.HMAC[:16])
		} else {
			fmt.Println("  hmac:          (unsigned)")
		}
	} else {
		fmt.Println("  (no receipts captured)")
	}
	telemetry.EnableReceipts(false, "", "")
	fmt.Println()
}

func main() {
	_, err := telemetry.SetupTelemetry()
	if err != nil {
		telemetry.Logger.Error("setup failed", "err", err)
		return
	}
	defer func() { _ = telemetry.ShutdownTelemetry(context.Background()) }()

	ctx := context.Background()
	startEvt, _ := telemetry.Event("governance", "demo", "start")
	telemetry.GetLogger(ctx, "governance-demo").InfoContext(ctx, startEvt.Event, startEvt.Attrs()...)

	fmt.Println("=== Data Governance Demo ===")
	fmt.Println()
	demoConsent()
	demoClassification()
	demoReceipts()

	fmt.Println("=== Done ===")
}
