// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

//go:build !nogovernance

package telemetry

import (
	"testing"
)

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

	got := ClassifyKey("email")
	if got == nil {
		t.Fatal("expected ClassifyKey to return a pointer for a matching key")
	}
	if *got != DataClassPII {
		t.Errorf("expected %q, got %q", DataClassPII, *got)
	}

	if miss := ClassifyKey("name"); miss != nil {
		t.Errorf("expected nil for unmatched key, got %v", *miss)
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

// ── Policy actions ────────────────────────────────────────────────────────────

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
