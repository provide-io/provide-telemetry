// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"regexp"
	"strings"
	"sync"
	"testing"
)

// ── Concurrency ───────────────────────────────────────────────────────────────

func TestSanitizePayload_Concurrent(t *testing.T) {
	resetPII(t)
	SetPIIRules([]PIIRule{
		{Path: []string{"uid"}, Mode: PIIModeHash},
	})
	payload := map[string]any{"uid": "user-1", "password": "s3cr3t", "name": _testAlice} // pragma: allowlist secret

	var wg sync.WaitGroup
	for i := 0; i < 50; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			result := SanitizePayload(payload, true, 32)
			if result["password"] != _piiRedacted { // pragma: allowlist secret
				t.Errorf("concurrent: expected password redacted")
			}
		}()
	}
	wg.Wait()
}

// ── Input not mutated ─────────────────────────────────────────────────────────

func TestSanitizePayload_DoesNotMutateInput(t *testing.T) {
	resetPII(t)
	SetPIIRules([]PIIRule{
		{Path: []string{"card"}, Mode: PIIModeDrop},
	})
	payload := map[string]any{
		"card":  "4111-1111",
		"extra": "keep",
	}
	_ = SanitizePayload(payload, true, 32)
	if _, ok := payload["card"]; !ok {
		t.Error("input map was mutated: card key was removed")
	}
}

// ── Slice with non-map items ──────────────────────────────────────────────────

func TestSanitizePayload_SliceWithNonMapItems(t *testing.T) {
	resetPII(t)
	payload := map[string]any{
		"tags": []any{"alpha", "beta", 123},
	}
	result := SanitizePayload(payload, true, 32)
	tags, _ := result["tags"].([]any)
	if len(tags) != 3 {
		t.Fatalf("expected 3 tags, got %d", len(tags))
	}
	if tags[0] != "alpha" || tags[1] != "beta" || tags[2] != 123 {
		t.Errorf("unexpected tags: %v", tags)
	}
}

// ── _isDefaultSensitiveKey case-insensitive ───────────────────────────────────

func TestIsDefaultSensitiveKey_CaseInsensitive(t *testing.T) {
	cases := []struct {
		key      string
		expected bool
	}{
		{"PASSWORD", true},
		{"UserPassword", false},
		{"Api_Key", true},
		{"APIKEY", true},
		{"Authorization", true},
		{"username", false},
		{"email", false},
	}
	for _, tc := range cases {
		got := _isDefaultSensitiveKey(tc.key)
		if got != tc.expected {
			t.Errorf("_isDefaultSensitiveKey(%q): want %v, got %v", tc.key, tc.expected, got)
		}
	}
}

// ── pii.go:177 truncate: string of truncateTo-1 runes must NOT be truncated. ──

func TestSanitizePayload_Truncate_OneBelowLimit_Unchanged(t *testing.T) {
	resetPII(t)
	SetPIIRules([]PIIRule{
		{Path: []string{"note"}, Mode: PIIModeTruncate, TruncateTo: 5},
	})
	payload := map[string]any{"note": "abcd"} // 4 runes = truncateTo-1
	result := SanitizePayload(payload, true, 32)
	if result["note"] != "abcd" {
		t.Errorf("string shorter than truncateTo should be unchanged, got %v", result["note"])
	}
}

// ── pii.go:177 truncate: string of truncateTo+1 runes MUST be truncated ──────

func TestSanitizePayload_Truncate_OneOverLimit_Truncated(t *testing.T) {
	resetPII(t)
	const limit = 5
	SetPIIRules([]PIIRule{
		{Path: []string{"note"}, Mode: PIIModeTruncate, TruncateTo: limit},
	})
	// "abcdef" has 6 runes (truncateTo+1) — must be truncated to 5.
	payload := map[string]any{"note": "abcdef"}
	result := SanitizePayload(payload, true, 32)
	if result["note"] != "abcde..." {
		t.Errorf("string one over limit should be truncated to %d runes + suffix, got %v", limit, result["note"])
	}
}

// ── pii.go:177 truncate boundary: exactly truncateTo runes must NOT truncate ──

func TestSanitizePayload_Truncate_ExactlyAtLimit_NotTruncated(t *testing.T) {
	resetPII(t)
	const limit = 5
	SetPIIRules([]PIIRule{
		{Path: []string{"note"}, Mode: PIIModeTruncate, TruncateTo: limit},
	})
	// "hello" has exactly 5 runes — must NOT be truncated (> not >=)
	payload := map[string]any{"note": "hello"}
	result := SanitizePayload(payload, true, 32)
	if result["note"] != "hello" {
		t.Errorf("string of exactly %d runes should not be truncated, got %v", limit, result["note"])
	}
}

// ── Secret Pattern Registration ──────────────────────────────────────────────

func TestRegisterSecretPattern_CustomPatternDetectsSecret(t *testing.T) {
	resetPII(t)
	// Register a pattern that matches "CUSTOM-" followed by 20+ alphanumerics.
	RegisterSecretPattern("custom-token", regexp.MustCompile(`CUSTOM-[A-Za-z0-9]{20,}`))

	payload := map[string]any{
		"message": "here is CUSTOM-abcdefghijklmnopqrstuvwxyz in the value",
	}
	result := SanitizePayload(payload, true, 32)
	if result["message"] != _piiRedacted {
		t.Errorf("expected custom secret pattern to redact, got %v", result["message"])
	}
}

func TestRegisterSecretPattern_SameNameReplacesPrevious(t *testing.T) {
	resetPII(t)
	// Register a pattern that won't match our test string.
	RegisterSecretPattern("mypattern", regexp.MustCompile(`NOMATCH-[A-Z]{30}`))

	payload := map[string]any{
		"data": "REPLACE-abcdefghijklmnopqrstuvwxyz", // pragma: allowlist secret
	}
	result := SanitizePayload(payload, true, 32)
	if result["data"] == _piiRedacted {
		t.Error("first pattern should NOT have matched")
	}

	// Replace with a pattern that matches.
	RegisterSecretPattern("mypattern", regexp.MustCompile(`REPLACE-[a-z]{20,}`))

	result2 := SanitizePayload(payload, true, 32)
	if result2["data"] != _piiRedacted {
		t.Errorf("replaced pattern should match, got %v", result2["data"])
	}

	// Verify only one custom pattern exists (deduplication).
	patterns := GetSecretPatterns()
	customCount := 0
	for _, p := range patterns {
		if p.Name == "mypattern" {
			customCount++
		}
	}
	if customCount != 1 {
		t.Errorf("expected 1 custom pattern named mypattern, got %d", customCount)
	}
}

func TestGetSecretPatterns_ReturnsBuiltinAndCustom(t *testing.T) {
	resetPII(t)
	builtinCount := len(_secretPatterns)

	// Before adding custom patterns.
	patterns := GetSecretPatterns()
	if len(patterns) != builtinCount {
		t.Errorf("expected %d built-in patterns, got %d", builtinCount, len(patterns))
	}

	// Add two custom patterns.
	RegisterSecretPattern("pat-a", regexp.MustCompile(`AAA`))
	RegisterSecretPattern("pat-b", regexp.MustCompile(`BBB`))

	patterns = GetSecretPatterns()
	if len(patterns) != builtinCount+2 {
		t.Errorf("expected %d total patterns, got %d", builtinCount+2, len(patterns))
	}

	// Verify built-in names start with "builtin-".
	for i := 0; i < builtinCount; i++ {
		if !strings.HasPrefix(patterns[i].Name, "builtin-") {
			t.Errorf("expected builtin pattern name prefix, got %q", patterns[i].Name)
		}
	}
}

func TestResetSecretPatterns_ClearsCustom(t *testing.T) {
	_resetPIIRules()
	_resetSecretPatterns()
	t.Cleanup(_resetPIIRules)
	t.Cleanup(_resetSecretPatterns)

	RegisterSecretPattern("temp", regexp.MustCompile(`TEMP`))
	_resetSecretPatterns()

	patterns := GetSecretPatterns()
	builtinCount := len(_secretPatterns)
	if len(patterns) != builtinCount {
		t.Errorf("expected only %d built-in patterns after reset, got %d", builtinCount, len(patterns))
	}
}

func TestRegisterSecretPattern_WorksInSanitizePayloadE2E(t *testing.T) {
	resetPII(t)
	RegisterSecretPattern("internal-key", regexp.MustCompile(`IKEY-[0-9a-f]{20,}`))

	payload := map[string]any{
		"config": map[string]any{
			"endpoint": "https://example.com",
			"key":      "IKEY-0123456789abcdef0123456789",
		},
		"name": "service-a",
	}
	result := SanitizePayload(payload, true, 32)

	config, _ := result["config"].(map[string]any)
	if config == nil {
		t.Fatal("expected config map")
	}
	if config["endpoint"] != "https://example.com" {
		t.Errorf("expected endpoint unchanged, got %v", config["endpoint"])
	}
	if config["key"] != _piiRedacted {
		t.Errorf("expected key redacted by custom pattern, got %v", config["key"])
	}
	if result["name"] != "service-a" {
		t.Errorf("expected name unchanged, got %v", result["name"])
	}
}

// TestSanitizePayload_DropMode_InSliceMaps verifies that a PIIRule with mode "drop"
// removes the matching key from map elements inside a slice.
func TestSanitizePayload_DropMode_InSliceMaps(t *testing.T) {
	_resetPIIRules()
	t.Cleanup(_resetPIIRules)

	SetPIIRules([]PIIRule{
		{Path: []string{"items", "token"}, Mode: PIIModeDrop},
	})

	payload := map[string]any{
		"items": []any{
			map[string]any{"token": "secret1", "id": "1"},
			map[string]any{"token": "other2", "id": "2"},
		},
	}
	result := SanitizePayload(payload, true, 8)

	items, ok := result["items"].([]any)
	if !ok {
		t.Fatal("expected items to be a slice")
	}
	for i, raw := range items {
		m, ok := raw.(map[string]any)
		if !ok {
			t.Fatalf("items[%d] is not a map", i)
		}
		if _, present := m["token"]; present {
			t.Errorf("items[%d]: expected token to be dropped, got %v", i, m["token"])
		}
	}
}

// TestSanitizePayload_DropMode_PrimitiveSliceNotDroppedWithoutMatch verifies that
// primitive values in a slice pass through unchanged when no rule matches them.
func TestSanitizePayload_DropMode_PrimitiveSliceNotDroppedWithoutMatch(t *testing.T) {
	_resetPIIRules()
	t.Cleanup(_resetPIIRules)

	SetPIIRules([]PIIRule{
		{Path: []string{"other"}, Mode: PIIModeDrop},
	})

	payload := map[string]any{
		"tags": []any{"alpha", "beta", "gamma"},
	}
	result := SanitizePayload(payload, true, 8)

	tags, ok := result["tags"].([]any)
	if !ok {
		t.Fatal("expected tags to be a slice")
	}
	if len(tags) != 3 {
		t.Errorf("expected 3 tags, got %d: %v", len(tags), tags)
	}
}
