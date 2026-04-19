// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// coverage_pii_test.go exercises PII/sanitize delegate code paths.
package logger_test

import (
	"testing"

	"github.com/provide-io/provide-telemetry/go/logger"
)

// ---- PII: remaining branches ----

func TestPIIDropMode(t *testing.T) {
	defer logger.ResetPIIRules()
	logger.SetPIIRules([]logger.PIIRule{
		{Path: []string{"ssn"}, Mode: logger.PIIModeDrop},
	})
	payload := map[string]any{"ssn": "123-45-6789"}
	result := logger.SanitizePayload(payload, true, 0)
	if _, ok := result["ssn"]; ok {
		t.Fatal("ssn should be dropped")
	}
}

func TestPIITruncateMode(t *testing.T) {
	defer logger.ResetPIIRules()
	logger.SetPIIRules([]logger.PIIRule{
		{Path: []string{"note"}, Mode: logger.PIIModeTruncate, TruncateTo: 5},
	})
	payload := map[string]any{"note": "this is a long note"}
	result := logger.SanitizePayload(payload, true, 0)
	s, ok := result["note"].(string)
	if !ok {
		t.Fatalf("note = %T %v", result["note"], result["note"])
	}
	if len([]rune(s)) > 8 { // 5 chars + "..."
		t.Fatalf("note should be truncated, got %q", s)
	}
}

func TestPIITruncateShort(t *testing.T) {
	defer logger.ResetPIIRules()
	logger.SetPIIRules([]logger.PIIRule{
		{Path: []string{"note"}, Mode: logger.PIIModeTruncate, TruncateTo: 100},
	})
	payload := map[string]any{"note": "short"}
	result := logger.SanitizePayload(payload, true, 0)
	if result["note"] != "short" {
		t.Fatalf("short string should not be truncated, got %v", result["note"])
	}
}

func TestPIIHashMode(t *testing.T) {
	defer logger.ResetPIIRules()
	logger.SetPIIRules([]logger.PIIRule{
		{Path: []string{"id"}, Mode: logger.PIIModeHash},
	})
	payload := map[string]any{"id": "user-123"}
	result := logger.SanitizePayload(payload, true, 0)
	s, ok := result["id"].(string)
	if !ok || len(s) != 12 {
		t.Fatalf("id hash = %v", result["id"])
	}
}

func TestPIINestedMap(t *testing.T) {
	payload := map[string]any{
		"user": map[string]any{
			"password": "s3cr3t",
			"name":     "alice",
		},
	}
	result := logger.SanitizePayload(payload, true, 4)
	user, ok := result["user"].(map[string]any)
	if !ok {
		t.Fatalf("user field should be a map, got %T", result["user"])
	}
	if user["password"] == "s3cr3t" { // pragma: allowlist secret
		t.Fatal("nested password should be redacted")
	}
}

func TestPIISliceSanitization(t *testing.T) {
	payload := map[string]any{
		"items": []any{
			map[string]any{"token": "secret-value"}, //nolint // pragma: allowlist secret
			"plain-string",
		},
	}
	result := logger.SanitizePayload(payload, true, 4)
	items, ok := result["items"].([]any)
	if !ok {
		t.Fatalf("items should be []any, got %T", result["items"])
	}
	first, ok := items[0].(map[string]any)
	if !ok {
		t.Fatalf("first item should be map, got %T", items[0])
	}
	if first["token"] == "secret-value" {
		t.Fatal("token in slice should be redacted")
	}
}

func TestPIIClassificationHook(t *testing.T) {
	defer logger.ResetPIIRules()
	logger.SetClassificationHook(func(key string, value any) string {
		if key == "email" {
			return "PII"
		}
		return ""
	})

	payload := map[string]any{"email": "user@example.com", "name": "alice"}
	result := logger.SanitizePayload(payload, true, 0)
	if result["__email__class"] != "PII" {
		t.Fatalf("classification hook should add __email__class, got: %v", result)
	}
}

func TestPIIReceiptHook(t *testing.T) {
	defer logger.ResetPIIRules()
	var receipts []string
	logger.SetReceiptHook(func(path, action string, _ any) {
		receipts = append(receipts, path+":"+action)
	})

	payload := map[string]any{"password": "s3cr3t"}
	logger.SanitizePayload(payload, true, 0)
	if len(receipts) == 0 {
		t.Fatal("receipt hook should have been called")
	}
}

func TestPIIDetectSecretInValue(t *testing.T) {
	// A JWT-like string should be detected and redacted.
	jwt := "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxw" // pragma: allowlist secret
	payload := map[string]any{"data": jwt}
	result := logger.SanitizePayload(payload, true, 0)
	if result["data"] == jwt {
		t.Fatal("JWT-like value should be detected and redacted")
	}
}

func TestPIIShortValueNotRedacted(t *testing.T) {
	payload := map[string]any{"data": "short"}
	result := logger.SanitizePayload(payload, true, 0)
	if result["data"] != "short" {
		t.Fatal("short non-sensitive value should not be redacted")
	}
}

func TestGetPIIRules(t *testing.T) {
	defer logger.ResetPIIRules()
	logger.SetPIIRules([]logger.PIIRule{
		{Path: []string{"x"}, Mode: logger.PIIModeRedact},
	})
	rules := logger.GetPIIRules()
	if len(rules) != 1 {
		t.Fatalf("expected 1 rule, got %d", len(rules))
	}
}

// ---- SetSanitizePayloadFunc (Fix 1: delegate / PII engine unification) ----

// TestSetSanitizePayloadFunc_DelegateTakesPrecedence verifies that when a delegate
// is registered, SanitizePayload calls the delegate instead of its own rule set.
func TestSetSanitizePayloadFunc_DelegateTakesPrecedence(t *testing.T) {
	logger.ResetPIIRules()
	t.Cleanup(logger.ResetPIIRules)

	// Local rule would redact "user", but the delegate returns the value unchanged.
	logger.SetPIIRules([]logger.PIIRule{
		{Path: []string{"user"}, Mode: logger.PIIModeRedact},
	})

	called := false
	logger.SetSanitizePayloadFunc(func(payload map[string]any, enabled bool, maxDepth int) map[string]any {
		called = true
		out := make(map[string]any, len(payload))
		for k, v := range payload {
			out[k] = v
		}
		return out
	})

	payload := map[string]any{"user": "alice"}
	result := logger.SanitizePayload(payload, true, 8)

	if !called {
		t.Error("expected delegate to be called")
	}
	// Delegate does not apply local rules; user should be alice, not redacted.
	if result["user"] != "alice" {
		t.Errorf("delegate does not apply local rules; user should be alice, got %v", result["user"])
	}
}

// TestSetSanitizePayloadFunc_NilDeregisters verifies that passing nil to
// SetSanitizePayloadFunc reverts to the local rule set.
func TestSetSanitizePayloadFunc_NilDeregisters(t *testing.T) {
	logger.ResetPIIRules()
	t.Cleanup(logger.ResetPIIRules)

	logger.SetPIIRules([]logger.PIIRule{
		{Path: []string{"user"}, Mode: logger.PIIModeRedact},
	})

	// Register a delegate, then remove it.
	logger.SetSanitizePayloadFunc(func(payload map[string]any, enabled bool, maxDepth int) map[string]any {
		return payload
	})
	logger.SetSanitizePayloadFunc(nil)

	payload := map[string]any{"user": "alice"}
	result := logger.SanitizePayload(payload, true, 8)

	if result["user"] != "***" {
		t.Errorf("after nil deregister, local rules should apply; want ***, got %v", result["user"])
	}
}

// TestSetSanitizePayloadFunc_LoggingPipelineUsesDelegate verifies that a delegate
// wired into the logger sub-package correctly sanitizes a log field.
func TestSetSanitizePayloadFunc_LoggingPipelineUsesDelegate(t *testing.T) {
	logger.ResetPIIRules()
	t.Cleanup(logger.ResetPIIRules)

	// Delegate redacts the "secret" key regardless of local rules.
	logger.SetSanitizePayloadFunc(func(payload map[string]any, enabled bool, maxDepth int) map[string]any {
		out := make(map[string]any, len(payload))
		for k, v := range payload {
			if k == "secret" {
				out[k] = "***"
			} else {
				out[k] = v
			}
		}
		return out
	})

	payload := map[string]any{"secret": "top-secret-value", "name": "bob"}
	result := logger.SanitizePayload(payload, true, 8)

	if result["secret"] != "***" {
		t.Errorf("delegate should redact secret; got %v", result["secret"])
	}
	if result["name"] != "bob" {
		t.Errorf("delegate should preserve name; got %v", result["name"])
	}
}
