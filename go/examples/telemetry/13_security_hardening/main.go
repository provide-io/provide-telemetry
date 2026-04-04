// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// 13_security_hardening — input sanitization, secret detection, protocol guards.
//
// Demonstrates:
//  1. Control character stripping from log attributes
//  2. Attribute value truncation via SanitizePayload + nesting depth
//  3. Default sensitive key detection (password, token, api_key, etc.)
//  4. Nesting depth limits via maxDepth parameter
//  5. Configurable via environment: PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH etc.
package main

import (
	"context"
	"fmt"
	"strings"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

// stripControlChars removes ASCII control characters (0x00–0x1F and 0x7F) from a string.
// The telemetry logger pipeline does this automatically; this shows the effect explicitly.
func stripControlChars(s string) string {
	var b strings.Builder
	for _, r := range s {
		if r >= 0x20 && r != 0x7F {
			b.WriteRune(r)
		}
	}
	return b.String()
}

func main() {
	_, err := telemetry.SetupTelemetry()
	if err != nil {
		telemetry.Logger.Error("setup failed", "err", err)
		return
	}
	defer func() { _ = telemetry.ShutdownTelemetry(context.Background()) }()

	ctx := context.Background()
	log := telemetry.GetLogger(ctx, "security-demo")

	fmt.Println("=== Security Hardening Demo ===")
fmt.Println()

	// 1. Control characters stripped from log output
	fmt.Println("1. Control character stripping:")
	rawData := "clean\x00hidden\x01bytes\x7fremoved"
	cleanData := stripControlChars(rawData)
	ctrlEvt, _ := telemetry.Event("security", "demo", "control_chars")
	log.InfoContext(ctx, ctrlEvt.Event, append(ctrlEvt.Attrs(), "data", cleanData)...)
	fmt.Printf("   Input:  %q\n", rawData)
	fmt.Printf("   Output: %q\n", cleanData)
	fmt.Println("   (null bytes and control chars silently removed)")
fmt.Println()

	// 2. Value truncation via SanitizePayload
	fmt.Println("2. Value truncation (max_depth and oversized values):")
	hugeValue := strings.Repeat("x", 2000)
	truncPayload := map[string]any{
		"big_field": hugeValue,
	}
	// SanitizePayload itself doesn't do length truncation — that is done in the
	// logger pipeline.  Demonstrate explicit truncation via a PIIRule truncate mode.
	telemetry.RegisterPIIRule(telemetry.PIIRule{
		Path:       []string{"big_field"},
		Mode:       telemetry.PIIModeTruncate,
		TruncateTo: 1024,
	})
	sanitizedTrunc := telemetry.SanitizePayload(truncPayload, true, 0)
	truncEvt, _ := telemetry.Event("security", "demo", "truncation")
	log.InfoContext(ctx, truncEvt.Event, append(truncEvt.Attrs(), "big_field_len", len(sanitizedTrunc["big_field"].(string)))...)
	fmt.Printf("   Input: %d chars -> truncated to %d chars\n",
		len(hugeValue), len(sanitizedTrunc["big_field"].(string)))
	fmt.Println()

	// 3. Secret detection in values (default sensitive keys)
	fmt.Println("3. Automatic secret detection (default sensitive keys):")
	payload := map[string]any{
		"user":        "alice",
		"password":    "super-secret-pw",   //nolint:gosec // demo only
		"token":       "ghp_exampletoken",  //nolint:gosec // demo only
		"api_key":     "sk-EXAMPLE12345",   //nolint:gosec // demo only
		"notes":       "normal text is fine",
	}
	cleaned := telemetry.SanitizePayload(payload, true, 0)
	for _, k := range []string{"user", "password", "token", "api_key", "notes"} {
		fmt.Printf("   %s: %v\n", k, cleaned[k])
	}
	fmt.Println()

	// 4. Nesting depth protection
	fmt.Println("4. Nesting depth limit (max_depth=4):")
	deep := map[string]any{
		"l1": map[string]any{
			"l2": map[string]any{
				"l3": map[string]any{
					"l4": map[string]any{
						"l5": map[string]any{
							"l6": "deep",
						},
					},
				},
			},
		},
	}
	sanitizedDeep := telemetry.SanitizePayload(deep, true, 4)
	fmt.Printf("   Sanitized with max_depth=4: %v\n\n", sanitizedDeep)

	// 5. Environment variable configuration
	fmt.Println("5. Configurable via environment:")
	fmt.Println("   PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH=2048")
	fmt.Println("   PROVIDE_SECURITY_MAX_ATTR_COUNT=128")
	fmt.Println("   PROVIDE_SECURITY_MAX_NESTING_DEPTH=4")

	fmt.Println("\n=== Done ===")
}
