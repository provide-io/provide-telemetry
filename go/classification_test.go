// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

//go:build !nogovernance

package telemetry

import (
	"testing"
)

// resetClassification is a test helper that resets classification state and registers cleanup.
func resetClassification(t *testing.T) {
	t.Helper()
	ResetClassificationForTests()
	t.Cleanup(ResetClassificationForTests)
}

// ── DataClass constants ───────────────────────────────────────────────────────

func TestDataClassConstants(t *testing.T) {
	cases := []struct {
		name     string
		got      DataClass
		expected DataClass
	}{
		{"Public", DataClassPublic, "PUBLIC"},
		{"Internal", DataClassInternal, "INTERNAL"},
		{"PII", DataClassPII, "PII"},
		{"PHI", DataClassPHI, "PHI"},
		{"PCI", DataClassPCI, "PCI"},
		{"Secret", DataClassSecret, "SECRET"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if tc.got != tc.expected {
				t.Errorf("expected %q, got %q", tc.expected, tc.got)
			}
		})
	}
}

// ── Default policy ────────────────────────────────────────────────────────────

func TestDefaultClassificationPolicy(t *testing.T) {
	resetClassification(t)
	p := GetClassificationPolicy()
	if p.Public != "pass" {
		t.Errorf("Public: expected 'pass', got %q", p.Public)
	}
	if p.Internal != "pass" {
		t.Errorf("Internal: expected 'pass', got %q", p.Internal)
	}
	if p.PII != "redact" {
		t.Errorf("PII: expected 'redact', got %q", p.PII)
	}
	if p.PHI != "drop" {
		t.Errorf("PHI: expected 'drop', got %q", p.PHI)
	}
	if p.PCI != "hash" {
		t.Errorf("PCI: expected 'hash', got %q", p.PCI)
	}
	if p.Secret != "drop" { // pragma: allowlist secret
		t.Errorf("Secret: expected 'drop', got %q", p.Secret)
	}
}

// ── No rules → hook stays nil ─────────────────────────────────────────────────

func TestNoRules_HookIsNil(t *testing.T) {
	resetClassification(t)
	resetPII(t)
	// After reset, hook should be nil — no overhead.
	_piiMu.RLock()
	hook := _classificationHook
	_piiMu.RUnlock()
	if hook != nil {
		t.Error("expected classification hook to be nil before any rules are registered")
	}
}

// ── RegisterClassificationRules installs hook ─────────────────────────────────

func TestRegisterClassificationRules_InstallsHook(t *testing.T) {
	resetClassification(t)
	resetPII(t)
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "email", Classification: DataClassPII},
	})
	_piiMu.RLock()
	hook := _classificationHook
	_piiMu.RUnlock()
	if hook == nil {
		t.Error("expected hook to be installed after RegisterClassificationRules")
	}
}

func TestRegisterClassificationRule_InstallsHook(t *testing.T) {
	resetClassification(t)
	resetPII(t)
	RegisterClassificationRule(ClassificationRule{Pattern: "email", Classification: DataClassPII})
	_piiMu.RLock()
	hook := _classificationHook
	_piiMu.RUnlock()
	if hook == nil {
		t.Error("expected hook to be installed after RegisterClassificationRule")
	}
}

// ── Register empty list still installs hook ───────────────────────────────────

func TestRegisterClassificationRules_EmptyList_InstallsHook(t *testing.T) {
	resetClassification(t)
	resetPII(t)
	RegisterClassificationRules([]ClassificationRule{})
	_piiMu.RLock()
	hook := _classificationHook
	_piiMu.RUnlock()
	if hook == nil {
		t.Error("expected hook to be installed even with empty rule list")
	}
}

// ── Classification tags appear in SanitizePayload ─────────────────────────────

func TestClassificationTag_AddedToPayload(t *testing.T) {
	resetClassification(t)
	resetPII(t)
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "email", Classification: DataClassPII},
	})
	payload := map[string]any{
		"email": "alice@example.com",
		"name":  "Alice",
	}
	result := SanitizePayload(payload, true, 0)
	if result["__email__class"] != "PII" {
		t.Errorf("expected __email__class=PII, got %v", result["__email__class"])
	}
	if _, ok := result["__name__class"]; ok {
		t.Error("did not expect __name__class to be set")
	}
}

func TestClassificationTag_PHI_Dropped(t *testing.T) {
	resetClassification(t)
	resetPII(t)
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "dob", Classification: DataClassPHI},
	})
	// PHI default policy is "drop" — key is removed and no class tag appears.
	result := SanitizePayload(map[string]any{"dob": "1990-01-01"}, true, 0)
	if _, ok := result["dob"]; ok {
		t.Errorf("expected dob to be dropped, but got %v", result["dob"])
	}
	if _, ok := result["__dob__class"]; ok {
		t.Errorf("expected no __dob__class tag for dropped key, but it was set")
	}
}

// ── First-match wins ──────────────────────────────────────────────────────────

func TestClassifyField_FirstMatchWins(t *testing.T) {
	resetClassification(t)
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "email", Classification: DataClassPII},
		{Pattern: "email", Classification: DataClassPHI},
	})
	label := _classifyField("email", nil)
	if label != "PII" {
		t.Errorf("expected 'PII' (first match), got %q", label)
	}
}

// ── Wildcard patterns ─────────────────────────────────────────────────────────

func TestClassifyField_WildcardPattern(t *testing.T) {
	resetClassification(t)
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "user_*", Classification: DataClassInternal},
	})
	if label := _classifyField("user_id", 42); label != "INTERNAL" {
		t.Errorf("expected INTERNAL for user_id, got %q", label)
	}
	if label := _classifyField("user_name", "Alice"); label != "INTERNAL" {
		t.Errorf("expected INTERNAL for user_name, got %q", label)
	}
}

func TestClassifyField_WildcardNoMatchForUnrelated(t *testing.T) {
	resetClassification(t)
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "user_*", Classification: DataClassInternal},
	})
	if label := _classifyField("email", "alice@example.com"); label != "" {
		t.Errorf("expected empty for email, got %q", label)
	}
}

// ── No match → empty string ───────────────────────────────────────────────────

func TestClassifyField_NoMatch_ReturnsEmpty(t *testing.T) {
	resetClassification(t)
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "dob", Classification: DataClassPHI},
	})
	label := _classifyField("email", "alice@example.com")
	if label != "" {
		t.Errorf("expected empty string for unmatched key, got %q", label)
	}
}

func TestClassifyField_NoRules_ReturnsEmpty(t *testing.T) {
	resetClassification(t)
	label := _classifyField("email", "alice@example.com")
	if label != "" {
		t.Errorf("expected empty string with no rules, got %q", label)
	}
}

func TestClassifyKey_ReturnsPointerOrNil(t *testing.T) {
	resetClassification(t)
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "email", Classification: DataClassPII},
	})

	got := ClassifyKey("email", nil)
	if got == nil {
		t.Fatal("expected ClassifyKey to return a pointer for a matching key")
	}
	if *got != DataClassPII {
		t.Errorf("expected %q, got %q", DataClassPII, *got)
	}

	if miss := ClassifyKey("name", nil); miss != nil {
		t.Errorf("expected nil for unmatched key, got %v", *miss)
	}
}

// ── SetClassificationPolicy / GetClassificationPolicy ────────────────────────

func TestSetAndGetClassificationPolicy(t *testing.T) {
	resetClassification(t)
	newPolicy := ClassificationPolicy{
		Public:   "pass",
		Internal: "pass",
		PII:      "drop",
		PHI:      "redact",
		PCI:      "hash",
		Secret:   "drop",
	}
	SetClassificationPolicy(newPolicy)
	got := GetClassificationPolicy()
	if got.PII != "drop" {
		t.Errorf("expected PII='drop', got %q", got.PII)
	}
	if got.PHI != "redact" {
		t.Errorf("expected PHI='redact', got %q", got.PHI)
	}
}

// ── ResetClassificationForTests clears all state ──────────────────────────────

func TestResetClassificationForTests_ClearsRules(t *testing.T) {
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "email", Classification: DataClassPII},
	})
	ResetClassificationForTests()
	if label := _classifyField("email", nil); label != "" {
		t.Errorf("expected no label after reset, got %q", label)
	}
}

func TestResetClassificationForTests_RemovesHook(t *testing.T) {
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "email", Classification: DataClassPII},
	})
	ResetClassificationForTests()
	_piiMu.RLock()
	hook := _classificationHook
	_piiMu.RUnlock()
	if hook != nil {
		t.Error("expected hook to be nil after reset")
	}
}

func TestResetClassificationForTests_RestoresDefaultPolicy(t *testing.T) {
	SetClassificationPolicy(ClassificationPolicy{PII: "drop"})
	ResetClassificationForTests()
	p := GetClassificationPolicy()
	if p.PII != "redact" {
		t.Errorf("expected default PII='redact' after reset, got %q", p.PII)
	}
}

// ── Disabled SanitizePayload does not call hook ───────────────────────────────

func TestClassification_DisabledPayload_NoTags(t *testing.T) {
	resetClassification(t)
	resetPII(t)
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "email", Classification: DataClassPII},
	})
	result := SanitizePayload(map[string]any{"email": "alice@example.com"}, false, 0)
	if _, ok := result["__email__class"]; ok {
		t.Error("did not expect __email__class when sanitization is disabled")
	}
}

// ── Multiple RegisterClassificationRules calls accumulate ────────────────────

func TestRegisterClassificationRules_Accumulates(t *testing.T) {
	resetClassification(t)
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "email", Classification: DataClassPII},
	})
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "dob", Classification: DataClassPHI},
	})
	if label := _classifyField("email", nil); label != "PII" {
		t.Errorf("expected PII for email, got %q", label)
	}
	if label := _classifyField("dob", nil); label != "PHI" {
		t.Errorf("expected PHI for dob, got %q", label)
	}
}

// ── PUBLIC and SECRET labels ──────────────────────────────────────────────────

func TestPublicClassificationLabel(t *testing.T) {
	resetClassification(t)
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "status", Classification: DataClassPublic},
	})
	if label := _classifyField("status", "ok"); label != "PUBLIC" {
		t.Errorf("expected PUBLIC, got %q", label)
	}
}

func TestSecretClassificationLabel(t *testing.T) {
	resetClassification(t)
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "api_token", Classification: DataClassSecret},
	})
	if label := _classifyField("api_token", "xyz"); label != "SECRET" {
		t.Errorf("expected SECRET, got %q", label)
	}
}

// ── Policy hook wiring ────────────────────────────────────────────────────────

func TestPolicyHookInstalledAfterRegister(t *testing.T) {
	resetClassification(t)
	resetPII(t)
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "email", Classification: DataClassPII},
	})
	_piiMu.RLock()
	hook := _policyHook
	_piiMu.RUnlock()
	if hook == nil {
		t.Error("expected _policyHook to be installed after RegisterClassificationRules")
	}
}

func TestPolicyHookClearedAfterReset(t *testing.T) {
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "email", Classification: DataClassPII},
	})
	ResetClassificationForTests()
	_piiMu.RLock()
	hook := _policyHook
	_piiMu.RUnlock()
	if hook != nil {
		t.Error("expected _policyHook to be nil after ResetClassificationForTests")
	}
}

func TestLookupPolicyAction_UnknownLabelReturnsPass(t *testing.T) {
	resetClassification(t)
	// Call internal function directly to cover the default branch.
	action := _lookupPolicyAction("UNKNOWN_LABEL")
	if action != "pass" {
		t.Errorf("expected 'pass' for unknown label, got %q", action)
	}
}

func TestLookupPolicyAction_AllLabels(t *testing.T) {
	resetClassification(t)
	cases := []struct {
		label    string
		expected string
	}{
		{string(DataClassPublic), "pass"},
		{string(DataClassInternal), "pass"},
		{string(DataClassPII), "redact"},
		{string(DataClassPHI), "drop"},
		{string(DataClassPCI), "hash"},
		{string(DataClassSecret), "drop"},
		{"UNKNOWN", "pass"},
	}
	for _, tc := range cases {
		t.Run(tc.label, func(t *testing.T) {
			action := _lookupPolicyAction(tc.label)
			if action != tc.expected {
				t.Errorf("expected %q for label %q, got %q", tc.expected, tc.label, action)
			}
		})
	}
}

// ── Policy action: drop ───────────────────────────────────────────────────────

func TestPolicyAction_Drop_RemovesKey(t *testing.T) {
	resetClassification(t)
	resetPII(t)
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "dob", Classification: DataClassPHI},
	})
	// PHI default = "drop"
	result := SanitizePayload(map[string]any{"dob": "1990-01-01", "name": "Alice"}, true, 0)
	if _, ok := result["dob"]; ok {
		t.Errorf("expected dob to be dropped, got %v", result["dob"])
	}
	if result["name"] != "Alice" {
		t.Errorf("expected name to be unchanged, got %v", result["name"])
	}
}

func TestPolicyAction_Drop_NoClassTag(t *testing.T) {
	resetClassification(t)
	resetPII(t)
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "dob", Classification: DataClassPHI},
	})
	result := SanitizePayload(map[string]any{"dob": "1990-01-01"}, true, 0)
	if _, ok := result["__dob__class"]; ok {
		t.Error("expected no __dob__class tag for dropped key")
	}
}

func TestPolicyAction_Drop_ViaCustomPolicy(t *testing.T) {
	resetClassification(t)
	resetPII(t)
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "name", Classification: DataClassPII},
	})
	SetClassificationPolicy(ClassificationPolicy{
		Public: "pass", Internal: "pass", PII: "drop", PHI: "drop", PCI: "hash", Secret: "drop",
	})
	result := SanitizePayload(map[string]any{"name": "Alice"}, true, 0)
	if _, ok := result["name"]; ok {
		t.Errorf("expected name to be dropped, got %v", result["name"])
	}
	if _, ok := result["__name__class"]; ok {
		t.Error("expected no __name__class tag for dropped key")
	}
}

// ── Policy action: redact ─────────────────────────────────────────────────────

func TestPolicyAction_Redact_ReplacesValueAndAddsTag(t *testing.T) {
	resetClassification(t)
	resetPII(t)
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "email", Classification: DataClassPII},
	})
	// PII default = "redact"
	result := SanitizePayload(map[string]any{"email": "alice@example.com"}, true, 0)
	if result["email"] != "***" {
		t.Errorf("expected email=***, got %v", result["email"])
	}
	if result["__email__class"] != "PII" {
		t.Errorf("expected __email__class=PII, got %v", result["__email__class"])
	}
}

func TestPolicyAction_Redact_AlreadyRedactedNotDoubleMasked(t *testing.T) {
	resetClassification(t)
	resetPII(t)
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "email", Classification: DataClassPII},
	})
	result := SanitizePayload(map[string]any{"email": "***"}, true, 0)
	// Value stays "***" and class tag is added.
	if result["email"] != "***" {
		t.Errorf("expected email=***, got %v", result["email"])
	}
	if result["__email__class"] != "PII" {
		t.Errorf("expected __email__class=PII, got %v", result["__email__class"])
	}
}

func TestPolicyAction_Redact_ViaCustomPolicy(t *testing.T) {
	resetClassification(t)
	resetPII(t)
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "dob", Classification: DataClassPHI},
	})
	SetClassificationPolicy(ClassificationPolicy{
		Public: "pass", Internal: "pass", PII: "redact", PHI: "redact", PCI: "hash", Secret: "drop",
	})
	result := SanitizePayload(map[string]any{"dob": "1990-01-01"}, true, 0)
	if result["dob"] != "***" {
		t.Errorf("expected dob=***, got %v", result["dob"])
	}
	if result["__dob__class"] != "PHI" {
		t.Errorf("expected __dob__class=PHI, got %v", result["__dob__class"])
	}
}

// ── Policy action: hash ───────────────────────────────────────────────────────

func TestPolicyAction_Hash_Replaces12CharHexAndAddsTag(t *testing.T) {
	resetClassification(t)
	resetPII(t)
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "card_num", Classification: DataClassPCI},
	})
	// PCI default = "hash"
	result := SanitizePayload(map[string]any{"card_num": "4111111111111111"}, true, 0)
	hashed, ok := result["card_num"].(string)
	if !ok {
		t.Fatalf("expected card_num to be a string, got %T", result["card_num"])
	}
	if len(hashed) != 12 {
		t.Errorf("expected 12-char hash, got %d chars: %q", len(hashed), hashed)
	}
	if result["__card_num__class"] != "PCI" {
		t.Errorf("expected __card_num__class=PCI, got %v", result["__card_num__class"])
	}
}

func TestPolicyAction_Hash_IsDeterministic(t *testing.T) {
	resetClassification(t)
	resetPII(t)
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "card_num", Classification: DataClassPCI},
	})
	r1 := SanitizePayload(map[string]any{"card_num": "4111111111111111"}, true, 0)
	r2 := SanitizePayload(map[string]any{"card_num": "4111111111111111"}, true, 0)
	if r1["card_num"] != r2["card_num"] {
		t.Errorf("hash should be deterministic: %v != %v", r1["card_num"], r2["card_num"])
	}
}

// ── Policy action: truncate ───────────────────────────────────────────────────

func TestPolicyAction_Truncate_ShortenedAndAddsTag(t *testing.T) {
	resetClassification(t)
	resetPII(t)
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "notes", Classification: DataClassInternal},
	})
	SetClassificationPolicy(ClassificationPolicy{
		Public: "pass", Internal: "truncate", PII: "redact", PHI: "drop", PCI: "hash", Secret: "drop",
	})
	result := SanitizePayload(map[string]any{"notes": "abcdefghijklmnop"}, true, 0)
	if result["notes"] != "abcdefgh..." {
		t.Errorf("expected truncated value 'abcdefgh...', got %v", result["notes"])
	}
	if result["__notes__class"] != "INTERNAL" {
		t.Errorf("expected __notes__class=INTERNAL, got %v", result["__notes__class"])
	}
}

func TestPolicyAction_Truncate_ShortValueUnchanged(t *testing.T) {
	resetClassification(t)
	resetPII(t)
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "notes", Classification: DataClassInternal},
	})
	SetClassificationPolicy(ClassificationPolicy{
		Public: "pass", Internal: "truncate", PII: "redact", PHI: "drop", PCI: "hash", Secret: "drop",
	})
	result := SanitizePayload(map[string]any{"notes": "short"}, true, 0)
	if result["notes"] != "short" {
		t.Errorf("expected short value unchanged, got %v", result["notes"])
	}
	if result["__notes__class"] != "INTERNAL" {
		t.Errorf("expected __notes__class=INTERNAL, got %v", result["__notes__class"])
	}
}

// ── Policy action: pass ───────────────────────────────────────────────────────

func TestPolicyAction_Pass_ValueUnchangedTagAdded(t *testing.T) {
	resetClassification(t)
	resetPII(t)
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "status", Classification: DataClassPublic},
	})
	// PUBLIC default = "pass"
	result := SanitizePayload(map[string]any{"status": "ok"}, true, 0)
	if result["status"] != "ok" {
		t.Errorf("expected status=ok unchanged, got %v", result["status"])
	}
	if result["__status__class"] != "PUBLIC" {
		t.Errorf("expected __status__class=PUBLIC, got %v", result["__status__class"])
	}
}

func TestPolicyAction_UnknownAction_FallsBackToPass(t *testing.T) {
	resetClassification(t)
	resetPII(t)
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "foo", Classification: DataClassPublic},
	})
	SetClassificationPolicy(ClassificationPolicy{
		Public: "unknown_action", Internal: "pass", PII: "redact", PHI: "drop", PCI: "hash", Secret: "drop",
	})
	result := SanitizePayload(map[string]any{"foo": "bar"}, true, 0)
	if result["foo"] != "bar" {
		t.Errorf("expected foo=bar unchanged for unknown action, got %v", result["foo"])
	}
	if result["__foo__class"] != "PUBLIC" {
		t.Errorf("expected __foo__class=PUBLIC for unknown action, got %v", result["__foo__class"])
	}
}

// ── Strippable governance ─────────────────────────────────────────────────────

func TestStrippableGovernance_NoClassificationModule_PayloadWorksNormally(t *testing.T) {
	resetPII(t)
	// No RegisterClassificationRules call — hooks stay nil.
	result := SanitizePayload(map[string]any{"email": "alice@example.com", "name": "Alice"}, true, 0)
	// email is NOT in DEFAULT_SANITIZE_FIELDS (intentionally excluded), name is clean.
	for k := range result {
		if len(k) > 7 && k[len(k)-7:] == "__class" {
			t.Errorf("unexpected class tag %q when no classification rules registered", k)
		}
	}
}

func TestStrippableGovernance_DefaultRedactionStillWorks(t *testing.T) {
	resetPII(t)
	// password is in DEFAULT_SANITIZE_FIELDS — should be redacted even without classification.
	result := SanitizePayload(map[string]any{"password": "hunter2", "name": "Alice"}, true, 0)
	if result["password"] != "***" {
		t.Errorf("expected password=***, got %v", result["password"])
	}
	for k := range result {
		if len(k) > 7 && k[len(k)-7:] == "__class" {
			t.Errorf("unexpected class tag %q when no classification rules registered", k)
		}
	}
}
