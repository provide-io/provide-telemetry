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
