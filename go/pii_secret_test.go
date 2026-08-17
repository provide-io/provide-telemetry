// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"regexp"
	"strings"
	"sync"
	"testing"

	"github.com/provide-io/provide-telemetry/go/internal/piicore"
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
	// Span-scoped since 2026-08-16: the credential token is replaced and the
	// words around it survive. What this test defends is that the secret does
	// not reach the log; blanking the whole value was the old mechanism.
	if result["message"] != "here is *** in the value" {
		t.Errorf("expected custom secret pattern to redact, got %v", result["message"])
	}
	if strings.Contains(result["message"].(string), "abcdefghijklmnopqrstuvwxyz") {
		t.Errorf("custom secret survived redaction: %v", result["message"])
	}
}

func TestRedactSecretSpans_RemovesWholeCredentialOnPartialMatch(t *testing.T) {
	// The jwt pattern matches header.payload; a JWT has THREE dot-separated
	// parts, so redacting the literal match alone would publish the signature.
	jwt := "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" + // pragma: allowlist secret
		".eyJzdWIiOiIxMjM0NTY3ODkwIn0" +
		".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
	signature := jwt[strings.LastIndex(jwt, ".")+1:]

	out := piicore.RedactSecretSpans("auth header "+jwt+" rejected", nil)

	if strings.Contains(out, signature) {
		t.Errorf("JWT signature survived redaction: %s", out)
	}
	if out != "auth header *** rejected" {
		t.Errorf("unexpected redaction: %s", out)
	}
}

func TestRedactSecretSpans_LeavesFilesystemPathsAlone(t *testing.T) {
	// [A-Za-z0-9+/]{40,} includes the slash, so a deep path used to match and
	// the whole field became "***".
	for _, line := range []string{
		"/home/deploy/apps/production/current/lib/service",
		"/var/lib/docker/overlay2/abcdef0123456789/merged/app",
		"make -C /home/deploy/apps/production/current/native/capture install",
	} {
		if got := piicore.RedactSecretSpans(line, nil); got != line {
			t.Errorf("path was redacted:\n  in:  %s\n  out: %s", line, got)
		}
	}
}

func TestRedactSecretSpans_RedactsEverySecretInAValue(t *testing.T) {
	// Whole-value blanking covered every credential in a field for free.
	// Scoping redaction to one token dropped that guarantee silently: the
	// field is still flagged, but only the first secret goes.
	const first = "AKIAIOSFODNN7EXAMPLE"  // pragma: allowlist secret
	const second = "AKIAIOSFODNN7EXAMPLB" // pragma: allowlist secret
	if !piicore.DetectSecretInValue(first, nil) || !piicore.DetectSecretInValue(second, nil) {
		t.Fatal("both constants must be secrets on their own")
	}

	out := piicore.RedactSecretSpans("first "+first+" second "+second, nil)

	if strings.Contains(out, first) || strings.Contains(out, second) {
		t.Errorf("a secret survived redaction: %s", out)
	}
	if out != "first *** second ***" {
		t.Errorf("unexpected redaction: %s", out)
	}
}

func TestRedactSecretSpans_PathDoesNotShadowLaterSecret(t *testing.T) {
	// long_base64 matches the path first. Suppressing that match as
	// path-shaped moved the scan on to the next pattern, and long_base64 is
	// the last one, so the real secret behind the path was never looked for.
	// A path prefix must not be a redaction bypass.
	const path = "/home/deploy/apps/production/current/lib/service"
	const secret = "c2VjcmV0a2V5MTIzNDU2Nzg5MGFiY2RlZmdoaWprbG1ub3A" // pragma: allowlist secret
	if piicore.DetectSecretInValue(path, nil) {
		t.Fatal("path must be suppressed on its own")
	}
	if !piicore.DetectSecretInValue(secret, nil) {
		t.Fatal("secret must be caught on its own")
	}

	out := piicore.RedactSecretSpans(path+" "+secret, nil)

	if strings.Contains(out, secret) {
		t.Errorf("secret survived behind a path: %s", out)
	}
	if out != path+" ***" {
		t.Errorf("unexpected redaction: %s", out)
	}
}

func TestRedactSecretSpans_CustomPatternOrderDoesNotChangeOutput(t *testing.T) {
	// customPatterns is a map, and Go randomises map iteration order. While
	// detection returned a bool that did not matter; now the iteration order
	// picks WHICH span is redacted, so with two matching patterns the output
	// varied between runs and diverged from the other four runtimes.
	// Redacting every match is what makes this deterministic.
	custom := map[string]*regexp.Regexp{
		"alpha": regexp.MustCompile(`ALPHA-[A-Z0-9]{12}`),
		"beta":  regexp.MustCompile(`BETA-[A-Z0-9]{12}`),
	}
	const line = "a ALPHA-AAAABBBBCCCC b BETA-DDDDEEEEFFFF c"

	for i := range 32 {
		if got := piicore.RedactSecretSpans(line, custom); got != "a *** b *** c" {
			t.Fatalf("run %d: map order changed the output: %s", i, got)
		}
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

func TestRedactSecretSpans_EmptyMatchingPatternRedactsNothing(t *testing.T) {
	// Scanning every match means a pattern that can match the empty string
	// yields one at every position. Without a guard the walk widens a
	// zero-length match to whatever token it landed in, blanking a word that
	// holds no secret.
	custom := map[string]*regexp.Regexp{"empty": regexp.MustCompile(`Z*`)}
	const clean = "the quick brown fox jumps over it"

	if got := piicore.RedactSecretSpans(clean, custom); got != clean {
		t.Errorf("empty-matching pattern redacted an innocent word: %s", got)
	}
}

func TestRedactSecretSpans_WidensLeftwardToTheTokenStart(t *testing.T) {
	// The credential is glued to a prefix, so the match begins mid-token and
	// redaction has to walk left to the token's first byte. Every other test
	// puts the secret at a token boundary, where that walk never runs — and a
	// missing walk would leave the prefix behind with the secret's leading
	// bytes still attached to it.
	const secret = "AKIAIOSFODNN7EXAMPLE" // pragma: allowlist secret

	out := piicore.RedactSecretSpans("prefix"+secret+" tail", nil)

	if strings.Contains(out, secret) {
		t.Errorf("secret survived redaction: %s", out)
	}
	if out != "*** tail" {
		t.Errorf("unexpected redaction: %s", out)
	}
}
