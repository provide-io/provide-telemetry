// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

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

func TestClassificationTag_PHI(t *testing.T) {
	resetClassification(t)
	resetPII(t)
	RegisterClassificationRules([]ClassificationRule{
		{Pattern: "dob", Classification: DataClassPHI},
	})
	result := SanitizePayload(map[string]any{"dob": "1990-01-01"}, true, 0)
	if result["__dob__class"] != "PHI" {
		t.Errorf("expected __dob__class=PHI, got %v", result["__dob__class"])
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
