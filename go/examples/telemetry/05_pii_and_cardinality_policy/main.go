// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// 05_pii_and_cardinality_policy — PII masking and cardinality guardrails.
//
// Demonstrates:
//   - RegisterPIIRule / ReplacePIIRules / GetPIIRules
//   - All four PII modes: hash, truncate, drop, redact
//   - Wildcard path matching for list items
//   - RegisterCardinalityLimit with TTL and OVERFLOW_VALUE
//   - GetCardinalityLimits / ClearCardinalityLimits
//   - GuardAttributes for cardinality enforcement
package main

import (
	"context"
	"fmt"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

// overflowValue is the sentinel returned by GuardAttributes when a cardinality
// limit is exceeded. It matches the Python OVERFLOW_VALUE constant.
const overflowValue = "__overflow__"

func main() {
	fmt.Println("PII & Cardinality Policy Demo\n")

	_, err := telemetry.SetupTelemetry()
	if err != nil {
		telemetry.Logger.Error("setup failed", "err", err)
		return
	}
	defer func() { _ = telemetry.ShutdownTelemetry(context.Background()) }()

	ctx := context.Background()
	log := telemetry.GetLogger(ctx, "examples.policy")

	// Register PII rules — hash, truncate, drop modes
	fmt.Println("Registering PII rules...")
	telemetry.RegisterPIIRule(telemetry.PIIRule{
		Path: []string{"user", "email"},
		Mode: telemetry.PIIModeHash,
	})
	telemetry.RegisterPIIRule(telemetry.PIIRule{
		Path:       []string{"user", "full_name"},
		Mode:       telemetry.PIIModeTruncate,
		TruncateTo: 3,
	})
	telemetry.RegisterPIIRule(telemetry.PIIRule{
		Path: []string{"credit_card"},
		Mode: telemetry.PIIModeDrop,
	})
	fmt.Printf("  Active rules: %d\n", len(telemetry.GetPIIRules()))

	// Log with PII fields — processor chain applies the rules
	piiEvt, _ := telemetry.Event("example", "policy", "pii")
	log.InfoContext(ctx, piiEvt,
		"user_email", "dev@example.com",
		"user_full_name", "Casey Developer",
		"credit_card", "4111111111111111",
	)

	// Wildcard path matching for nested list items
	fmt.Println("\nWildcard path matching on list items...")
	telemetry.ReplacePIIRules([]telemetry.PIIRule{
		{Path: []string{"players", "*", "secret"}, Mode: telemetry.PIIModeRedact},
	})
	payload := map[string]any{
		"players": []any{
			map[string]any{"secret": "key-aaa", "name": "Alice"},
			map[string]any{"secret": "key-bbb", "name": "Bob"},
		},
	}
	cleaned := telemetry.SanitizePayload(payload, true, 0)
	if players, ok := cleaned["players"].([]any); ok {
		for _, p := range players {
			if player, ok := p.(map[string]any); ok {
				fmt.Printf("  %s: secret=%v\n", player["name"], player["secret"])
			}
		}
	}
	fmt.Printf("  Rules after replace: %d\n", len(telemetry.GetPIIRules()))

	// Custom rule precedence over default redaction
	fmt.Println("\nCustom rule vs. default 'password' redaction...")
	telemetry.ReplacePIIRules([]telemetry.PIIRule{
		{Path: []string{"password"}, Mode: telemetry.PIIModeTruncate, TruncateTo: 4},
	})
	result := telemetry.SanitizePayload(map[string]any{"password": "hunter2"}, true, 0)
	fmt.Printf("  password -> %v  (custom truncate, not '***')\n", result["password"])

	resultShort := telemetry.SanitizePayload(map[string]any{"password": "ab"}, true, 0)
	fmt.Printf("  short password -> %v  (no-op truncate preserved)\n", resultShort["password"])

	// Cardinality limits with overflow
	fmt.Println("\nCardinality guard (max_values=2)...")
	telemetry.ReplacePIIRules([]telemetry.PIIRule{})
	telemetry.RegisterCardinalityLimit("user_id", telemetry.CardinalityLimit{
		MaxValues:  2,
		TTLSeconds: 60,
	})

	metric := telemetry.NewCounter("example.policy.requests")
	for _, userID := range []string{"u1", "u2", "u3", "u4"} {
		attrs := telemetry.GuardAttributes(map[string]string{"user_id": userID})
		metric.Add(ctx, 1)
		isOverflow := attrs["user_id"] == overflowValue
		mark := "OK"
		if isOverflow {
			mark = "OVERFLOW"
		}
		fmt.Printf("  user_id=%s -> guarded=%s  [%s]\n", userID, attrs["user_id"], mark)
	}

	limits := telemetry.GetCardinalityLimits()
	fmt.Printf("\n  Active cardinality limits: %v\n", keysOf(limits))

	// Clear cardinality state
	telemetry.ClearCardinalityLimits()
	fmt.Printf("  After clear: %v\n", telemetry.GetCardinalityLimits())

	fmt.Println("\nDone!")
}

// keysOf returns the keys of a CardinalityLimit map as a slice.
func keysOf(m map[string]telemetry.CardinalityLimit) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	return keys
}
