// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"fmt"
	"regexp"
	"sync"

	"github.com/provide-io/provide-telemetry/go/internal/piicore"
)

// PIIRule defines a rule for sanitizing a specific field path.
type PIIRule = piicore.PIIRule

// PII mode constants.
const (
	PIIModeRedact   = piicore.PIIModeRedact
	PIIModeDrop     = piicore.PIIModeDrop
	PIIModeHash     = piicore.PIIModeHash
	PIIModeTruncate = piicore.PIIModeTruncate
)

// SecretPattern pairs a diagnostic name with a compiled regexp.
type SecretPattern struct {
	Name    string
	Pattern *regexp.Regexp
}

var (
	_piiMu              sync.RWMutex
	_piiRules           []PIIRule
	_classificationHook func(key string, value any) string
	_receiptHook        func(fieldPath string, action string, originalValue any)
	_customSecretPats   map[string]*regexp.Regexp
)

// RegisterSecretPattern registers a custom secret detection pattern.
// If a pattern with the same name already exists, it is replaced.
// The name is for diagnostics only.
func RegisterSecretPattern(name string, pattern *regexp.Regexp) {
	_piiMu.Lock()
	defer _piiMu.Unlock()
	if _customSecretPats == nil { // pragma: allowlist secret
		_customSecretPats = make(map[string]*regexp.Regexp) // pragma: allowlist secret
	}
	_customSecretPats[name] = pattern
}

// GetSecretPatterns returns all secret patterns (built-in + custom).
func GetSecretPatterns() []SecretPattern {
	_piiMu.RLock()
	defer _piiMu.RUnlock()
	builtins := piicore.BuiltinSecretPatterns
	out := make([]SecretPattern, 0, len(builtins)+len(_customSecretPats))
	for i, re := range builtins {
		out = append(out, SecretPattern{Name: fmt.Sprintf("builtin-%d", i), Pattern: re})
	}
	for name, re := range _customSecretPats {
		out = append(out, SecretPattern{Name: name, Pattern: re})
	}
	return out
}

// _resetSecretPatterns clears all custom secret patterns (for test cleanup).
func _resetSecretPatterns() {
	_piiMu.Lock()
	defer _piiMu.Unlock()
	_customSecretPats = nil // pragma: allowlist secret
}

// SetClassificationHook registers a classification callback on the PII engine.
// Pass nil to deregister.
func SetClassificationHook(fn func(string, any) string) {
	_piiMu.Lock()
	defer _piiMu.Unlock()
	_classificationHook = fn
}

// SetReceiptHook registers a redaction receipt callback on the PII engine.
// Pass nil to deregister.
func SetReceiptHook(fn func(string, string, any)) {
	_piiMu.Lock()
	defer _piiMu.Unlock()
	_receiptHook = fn
}

// SetPIIRules replaces the global PII rule list.
func SetPIIRules(rules []PIIRule) {
	_piiMu.Lock()
	defer _piiMu.Unlock()
	cp := make([]PIIRule, len(rules))
	copy(cp, rules)
	_piiRules = cp
}

// GetPIIRules returns a copy of the current global PII rules.
func GetPIIRules() []PIIRule {
	_piiMu.RLock()
	defer _piiMu.RUnlock()
	cp := make([]PIIRule, len(_piiRules))
	copy(cp, _piiRules)
	return cp
}

// _resetPIIRules clears all custom PII rules and hooks (for test cleanup).
func _resetPIIRules() {
	_piiMu.Lock()
	defer _piiMu.Unlock()
	_piiRules = nil
	_classificationHook = nil
	_receiptHook = nil
}

// SanitizePayload applies PII sanitization to the given payload map and returns
// a new map with sensitive fields redacted, dropped, hashed, or truncated.
// The input map is never mutated.
// If enabled is false, a shallow copy is returned unchanged.
// If maxDepth <= 0, the default depth of 8 is used.
func SanitizePayload(payload map[string]any, enabled bool, maxDepth int) map[string]any {
	if !enabled {
		return piicore.ShallowCopy(payload)
	}
	if maxDepth <= 0 {
		maxDepth = piicore.DefaultMaxDepth
	}
	rules := GetPIIRules()

	_piiMu.RLock()
	receiptHook := _receiptHook
	customs := _customSecretPats
	_piiMu.RUnlock()

	result := piicore.SanitizeMap(payload, []string{}, rules, maxDepth, receiptHook, customs)

	// Apply classification tags for top-level keys if hook is registered.
	_piiMu.RLock()
	classHook := _classificationHook
	_piiMu.RUnlock()
	if classHook != nil {
		for k, v := range result {
			if label := classHook(k, v); label != "" {
				result["__"+k+"__class"] = label
			}
		}
	}
	return result
}
