// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"strings"
	"testing"
)

const (
	_testAlice   = "alice"
	_testMutated = "mutated"
)

// ── helpers ──────────────────────────────────────────────────────────────────

func resetPII(t *testing.T) {
	t.Helper()
	_resetPIIRules()
	_resetSecretPatterns()
	t.Cleanup(_resetPIIRules)
	t.Cleanup(_resetSecretPatterns)
}

// ── Test 1: disabled returns shallow copy unchanged ───────────────────────────

func TestSanitizePayload_Disabled_ReturnsCopyUnchanged(t *testing.T) {
	resetPII(t)
	payload := map[string]any{
		"password": "notsecret", // pragma: allowlist secret
		"user":     _testAlice,
	}
	result := SanitizePayload(payload, false, 32)
	if result["password"] != "notsecret" { // pragma: allowlist secret
		t.Errorf("expected password unchanged, got %v", result["password"])
	}
	if result["user"] != _testAlice {
		t.Errorf("expected user unchanged, got %v", result["user"])
	}
	// Verify it's a copy, not the same map.
	result["user"] = _testMutated
	if payload["user"] != _testAlice {
		t.Error("expected original map to be unmodified")
	}
}

// ── Test 2: default sensitive key detection ───────────────────────────────────

func TestSanitizePayload_DefaultSensitiveKeys_Redacted(t *testing.T) {
	resetPII(t)
	cases := []string{
		"password", "passwd", "secret", "token", "api_key", "apikey",
		"auth", "authorization", "credential", "private_key", "ssn",
		"credit_card", "creditcard", "cvv", "pin", "account_number",
	}
	for _, key := range cases {
		payload := map[string]any{key: "sensitive-value"}
		result := SanitizePayload(payload, true, 32)
		if result[key] != _piiRedacted {
			t.Errorf("key %q: expected %q, got %v", key, _piiRedacted, result[key])
		}
	}
}

func TestSanitizePayload_NonSensitiveKey_NotRedacted(t *testing.T) {
	resetPII(t)
	payload := map[string]any{"username": "alice", "age": 30}
	result := SanitizePayload(payload, true, 32)
	if result["username"] != "alice" {
		t.Errorf("expected username unchanged, got %v", result["username"])
	}
	if result["age"] != 30 {
		t.Errorf("expected age unchanged, got %v", result["age"])
	}
}

// ── Test 3: custom rule — drop mode ──────────────────────────────────────────

func TestSanitizePayload_CustomRule_Drop(t *testing.T) {
	resetPII(t)
	SetPIIRules([]PIIRule{
		{Path: []string{"card_number"}, Mode: PIIModeDrop},
	})
	payload := map[string]any{
		"card_number": "4111-1111-1111-1111",
		"user":        "bob",
	}
	result := SanitizePayload(payload, true, 32)
	if _, ok := result["card_number"]; ok {
		t.Error("expected card_number to be dropped")
	}
	if result["user"] != "bob" {
		t.Errorf("expected user unchanged, got %v", result["user"])
	}
}

// ── Test 4: custom rule — redact mode ────────────────────────────────────────

func TestSanitizePayload_CustomRule_Redact(t *testing.T) {
	resetPII(t)
	SetPIIRules([]PIIRule{
		{Path: []string{"email"}, Mode: PIIModeRedact},
	})
	payload := map[string]any{"email": "alice@example.com"}
	result := SanitizePayload(payload, true, 32)
	if result["email"] != _piiRedacted {
		t.Errorf("expected %q, got %v", _piiRedacted, result["email"])
	}
}

// ── Test 5: custom rule — hash mode ──────────────────────────────────────────

func TestSanitizePayload_CustomRule_Hash(t *testing.T) {
	resetPII(t)
	SetPIIRules([]PIIRule{
		{Path: []string{"uid"}, Mode: PIIModeHash},
	})
	payload := map[string]any{"uid": "user-42"}
	result := SanitizePayload(payload, true, 32)
	hashed, ok := result["uid"].(string)
	if !ok {
		t.Fatalf("expected string hash value, got %T", result["uid"])
	}
	if len(hashed) != 12 {
		t.Errorf("expected 12 hex chars, got %q (len %d)", hashed, len(hashed))
	}
	// Verify it's hex.
	for _, c := range hashed {
		if !strings.ContainsRune("0123456789abcdef", c) {
			t.Errorf("non-hex char %q in hash %q", c, hashed)
		}
	}
}

// ── Test 6: custom rule — truncate mode ──────────────────────────────────────

func TestSanitizePayload_CustomRule_Truncate_String(t *testing.T) {
	resetPII(t)
	SetPIIRules([]PIIRule{
		{Path: []string{"note"}, Mode: PIIModeTruncate, TruncateTo: 5},
	})
	payload := map[string]any{"note": "hello world"}
	result := SanitizePayload(payload, true, 32)
	if result["note"] != "hello..." {
		t.Errorf("expected %q, got %v", "hello...", result["note"])
	}
}

func TestSanitizePayload_CustomRule_Truncate_ShortString(t *testing.T) {
	resetPII(t)
	SetPIIRules([]PIIRule{
		{Path: []string{"note"}, Mode: PIIModeTruncate, TruncateTo: 20},
	})
	payload := map[string]any{"note": "hi"}
	result := SanitizePayload(payload, true, 32)
	if result["note"] != "hi" {
		t.Errorf("expected %q unchanged, got %v", "hi", result["note"])
	}
}

func TestSanitizePayload_CustomRule_Truncate_NonString_Stringified(t *testing.T) {
	resetPII(t)
	SetPIIRules([]PIIRule{
		{Path: []string{"count"}, Mode: PIIModeTruncate, TruncateTo: 5},
	})
	payload := map[string]any{"count": 42}
	result := SanitizePayload(payload, true, 32)
	// fmt.Sprintf("%v", 42) = "42" (2 chars < 5) → no truncation
	if result["count"] != "42" {
		t.Errorf("expected %q for non-string truncate, got %v", "42", result["count"])
	}
}

// ── Test 7: wildcard * in path ────────────────────────────────────────────────

func TestSanitizePayload_WildcardPath(t *testing.T) {
	resetPII(t)
	SetPIIRules([]PIIRule{
		{Path: []string{"*", "secret_field"}, Mode: PIIModeDrop},
	})
	payload := map[string]any{
		"acct1": map[string]any{"secret_field": "s1", "name": _testAlice},
		"acct2": map[string]any{"secret_field": "s2", "name": "bob"},
	}
	result := SanitizePayload(payload, true, 32)

	acct1, _ := result["acct1"].(map[string]any)
	if acct1 == nil {
		t.Fatal("expected acct1 to be present")
	}
	if _, ok := acct1["secret_field"]; ok {
		t.Error("expected acct1.secret_field to be dropped")
	}
	if acct1["name"] != _testAlice {
		t.Errorf("expected acct1.name=%s, got %v", _testAlice, acct1["name"])
	}

	acct2, _ := result["acct2"].(map[string]any)
	if acct2 == nil {
		t.Fatal("expected acct2 to be present")
	}
	if _, ok := acct2["secret_field"]; ok {
		t.Error("expected acct2.secret_field to be dropped")
	}
}

// ── Test 8: nested map traversal ─────────────────────────────────────────────

func TestSanitizePayload_NestedMap_ThreeLevels(t *testing.T) {
	resetPII(t)
	payload := map[string]any{
		"level1": map[string]any{
			"level2": map[string]any{
				"password": "deep-secret", // pragma: allowlist secret
				"safe":     "ok",
			},
		},
	}
	result := SanitizePayload(payload, true, 32)

	l1, _ := result["level1"].(map[string]any)
	if l1 == nil {
		t.Fatal("expected level1")
	}
	l2, _ := l1["level2"].(map[string]any)
	if l2 == nil {
		t.Fatal("expected level2")
	}
	if l2["password"] != _piiRedacted { // pragma: allowlist secret
		t.Errorf("expected nested password redacted, got %v", l2["password"])
	}
	if l2["safe"] != "ok" {
		t.Errorf("expected safe unchanged, got %v", l2["safe"])
	}
}

// ── Test 9: slice traversal ───────────────────────────────────────────────────

func TestSanitizePayload_SliceOfMaps(t *testing.T) {
	resetPII(t)
	payload := map[string]any{
		"users": []any{
			map[string]any{"name": "alice", "token": "t1"},
			map[string]any{"name": "bob", "token": "t2"},
		},
	}
	result := SanitizePayload(payload, true, 32)

	users, _ := result["users"].([]any)
	if len(users) != 2 {
		t.Fatalf("expected 2 users, got %d", len(users))
	}
	for i, u := range users {
		m, _ := u.(map[string]any)
		if m == nil {
			t.Fatalf("user %d: expected map", i)
		}
		if m["token"] != _piiRedacted {
			t.Errorf("user %d: expected token redacted, got %v", i, m["token"])
		}
	}
}

// ── Test 10: depth limit enforced ────────────────────────────────────────────

func TestSanitizePayload_DepthLimit_StopsRecursion(t *testing.T) {
	resetPII(t)
	// With maxDepth=1, nested maps at depth 2 are not traversed.
	payload := map[string]any{
		"outer": map[string]any{
			"password": "should-not-be-redacted", // pragma: allowlist secret
		},
	}
	result := SanitizePayload(payload, true, 1)

	outer, _ := result["outer"].(map[string]any)
	if outer == nil {
		t.Fatal("expected outer map")
	}
	// At depth=1, recursion into outer does not happen, so password stays.
	if outer["password"] == _piiRedacted { // pragma: allowlist secret
		t.Error("expected password NOT redacted at depth limit of 1")
	}
}

// ── Test 11: maxDepth=0 uses default 8 ───────────────────────────────────────

func TestSanitizePayload_ZeroMaxDepth_UsesDefault(t *testing.T) {
	resetPII(t)
	// Build a 6-level deep structure with a password at the bottom.
	// Default depth is 8, so a 6-level nest must be fully sanitized.
	inner := map[string]any{"password": "deep"} // pragma: allowlist secret
	current := inner
	for i := 0; i < 5; i++ {
		current = map[string]any{"nested": current}
	}

	result := SanitizePayload(current, true, 0)
	// Traverse down to find the password.
	node := result
	for i := 0; i < 5; i++ {
		next, _ := node["nested"].(map[string]any)
		if next == nil {
			t.Fatalf("expected nested map at depth %d", i)
		}
		node = next
	}
	if node["password"] != _piiRedacted { // pragma: allowlist secret
		t.Errorf("expected deep password redacted, got %v", node["password"])
	}
}

// ── Test 12: SetPIIRules / GetPIIRules round-trip ────────────────────────────

func TestSetGetPIIRules_RoundTrip(t *testing.T) {
	resetPII(t)
	rules := []PIIRule{
		{Path: []string{"a", "b"}, Mode: PIIModeDrop},
		{Path: []string{"*", "x"}, Mode: PIIModeHash},
	}
	SetPIIRules(rules)
	got := GetPIIRules()

	if len(got) != len(rules) {
		t.Fatalf("expected %d rules, got %d", len(rules), len(got))
	}
	for i, r := range rules {
		if got[i].Mode != r.Mode {
			t.Errorf("rule %d: mode mismatch, want %q got %q", i, r.Mode, got[i].Mode)
		}
		if len(got[i].Path) != len(r.Path) {
			t.Errorf("rule %d: path length mismatch", i)
		}
	}
	// Verify isolation: mutating returned slice doesn't affect global.
	got[0].Mode = _testMutated
	got2 := GetPIIRules()
	if got2[0].Mode == _testMutated {
		t.Error("expected GetPIIRules to return independent copy")
	}
}

// ── Test 13: _resetPIIRules clears rules ─────────────────────────────────────

func TestResetPIIRules_ClearsRules(t *testing.T) {
	_resetPIIRules()
	t.Cleanup(_resetPIIRules)

	SetPIIRules([]PIIRule{
		{Path: []string{"x"}, Mode: PIIModeDrop},
	})
	_resetPIIRules()
	rules := GetPIIRules()
	if len(rules) != 0 {
		t.Errorf("expected empty rules after reset, got %d", len(rules))
	}
}

// ── Test 14: hash is deterministic ───────────────────────────────────────────

func TestSanitizePayload_Hash_Deterministic(t *testing.T) {
	resetPII(t)
	SetPIIRules([]PIIRule{
		{Path: []string{"uid"}, Mode: PIIModeHash},
	})
	payload := map[string]any{"uid": "user-99"}
	r1 := SanitizePayload(payload, true, 32)
	r2 := SanitizePayload(payload, true, 32)

	h1, _ := r1["uid"].(string)
	h2, _ := r2["uid"].(string)
	if h1 != h2 {
		t.Errorf("hash not deterministic: %q vs %q", h1, h2)
	}
}

// ── pii.go:142 depth-1 in map recursion ──────────────────────────────────────

func TestSanitizePayload_MapDepth_CorrectDecrement(t *testing.T) {
	resetPII(t)
	payload := map[string]any{
		"level1": map[string]any{
			"level2": map[string]any{
				"password": "deep-hidden", // pragma: allowlist secret
			},
		},
	}
	result := SanitizePayload(payload, true, 2)

	l1, _ := result["level1"].(map[string]any)
	if l1 == nil {
		t.Fatal("expected level1")
	}
	l2, _ := l1["level2"].(map[string]any)
	if l2 == nil {
		t.Fatal("expected level2")
	}
	if l2["password"] == _piiRedacted { // pragma: allowlist secret
		t.Error("expected password NOT redacted when map depth limit reached (depth=1 stops recursion)")
	}
}

// ── pii.go:144 depth-1 vs depth+1 in _sanitizeSlice ─────────────────────────

func TestSanitizePayload_SliceDepth_CorrectDecrement(t *testing.T) {
	resetPII(t)
	payload := map[string]any{
		"arr": []any{
			map[string]any{
				"nested": map[string]any{
					"password": "deep-secret", // pragma: allowlist secret
				},
			},
		},
	}
	// maxDepth=3: arr(depth=3) → slice(depth=2) → map(depth=2) → nested(depth=2>1 recurse)
	// → map(depth=1) → password → sensitive → redacted
	result := SanitizePayload(payload, true, 3)

	arr, _ := result["arr"].([]any)
	if arr == nil {
		t.Fatal("expected arr in result")
	}
	item, _ := arr[0].(map[string]any)
	if item == nil {
		t.Fatal("expected map item in arr")
	}
	nested, _ := item["nested"].(map[string]any)
	if nested == nil {
		t.Fatal("expected nested map")
	}
	if nested["password"] != _piiRedacted { // pragma: allowlist secret
		t.Errorf("expected deep password redacted at depth 3, got %v", nested["password"])
	}

	// Now verify depth boundary: maxDepth=2 stops before reaching the password.
	result2 := SanitizePayload(payload, true, 2)
	arr2, _ := result2["arr"].([]any)
	item2, _ := arr2[0].(map[string]any)
	// At depth=2: _sanitizeSlice called with depth=2-1=1.
	// Inner map processed at depth=1. depth<=1 → no recursion into nested map.
	// nested map is returned unchanged.
	nested2, _ := item2["nested"].(map[string]any)
	if nested2 == nil {
		t.Fatal("expected nested map at depth 2")
	}
	if nested2["password"] == _piiRedacted { // pragma: allowlist secret
		t.Error("expected password NOT redacted when depth stops before reaching it")
	}
}
