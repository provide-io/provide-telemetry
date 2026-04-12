// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package logger

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
	_sanitizeDelegate   func(map[string]any, bool, int) map[string]any
)

// RegisterSecretPattern registers a custom secret detection pattern.
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

// ResetSecretPatterns clears all custom secret patterns (for test cleanup).
func ResetSecretPatterns() {
	_piiMu.Lock()
	defer _piiMu.Unlock()
	_customSecretPats = nil // pragma: allowlist secret
}

// SetClassificationHook registers a classification callback on the PII engine.
func SetClassificationHook(fn func(string, any) string) {
	_piiMu.Lock()
	defer _piiMu.Unlock()
	_classificationHook = fn
}

// SetReceiptHook registers a redaction receipt callback on the PII engine.
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

// ResetPIIRules clears all custom PII rules, hooks, and the sanitize delegate (for test cleanup).
func ResetPIIRules() {
	_piiMu.Lock()
	defer _piiMu.Unlock()
	_piiRules = nil
	_classificationHook = nil
	_receiptHook = nil
	_sanitizeDelegate = nil
}

// SetSanitizePayloadFunc registers an external sanitize function that SanitizePayload
// will delegate to instead of using its own rule set. Pass nil to deregister and
// fall back to the local rule set. This allows the top-level telemetry package to
// wire its own PII engine into the logger sub-package without creating an import cycle.
func SetSanitizePayloadFunc(fn func(map[string]any, bool, int) map[string]any) {
	_piiMu.Lock()
	defer _piiMu.Unlock()
	_sanitizeDelegate = fn
}

// SanitizePayload applies PII sanitization to the given payload map.
// If a delegate function has been registered via SetSanitizePayloadFunc, it is
// called instead of the local rule set, allowing the top-level telemetry engine
// to serve as the single source of truth for PII rules.
// If enabled is false, a shallow copy is returned unchanged.
func SanitizePayload(payload map[string]any, enabled bool, maxDepth int) map[string]any {
	if !enabled {
		return piicore.ShallowCopy(payload)
	}
	_piiMu.RLock()
	delegate := _sanitizeDelegate
	_piiMu.RUnlock()
	if delegate != nil {
		return delegate(payload, enabled, maxDepth)
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
