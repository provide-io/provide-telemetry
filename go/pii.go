// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"crypto/sha256"
	"fmt"
	"strings"
	"sync"
)

// PIIRule defines a rule for sanitizing a specific field path.
type PIIRule struct {
	Path       []string
	Mode       string
	TruncateTo int
}

// PII mode constants.
const (
	PIIModeRedact   = "redact"
	PIIModeDrop     = "drop"
	PIIModeHash     = "hash"
	PIIModeTruncate = "truncate"
)

const (
	_piiRedacted   = "***"
	_piiDefaultMax = 32
)

// _defaultSensitiveKeys lists substrings matched case-insensitively against key names.
var _defaultSensitiveKeys = []string{
	"password", "passwd", "secret", "token", "api_key", "apikey",
	"auth", "authorization", "credential", "private_key", "ssn",
	"credit_card", "creditcard", "cvv", "pin", "account_number",
}

var (
	_piiMu    sync.RWMutex
	_piiRules []PIIRule
)

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

// _resetPIIRules clears all custom PII rules (for test cleanup).
func _resetPIIRules() {
	_piiMu.Lock()
	defer _piiMu.Unlock()
	_piiRules = nil
}

// SanitizePayload applies PII sanitization to the given payload map and returns
// a new map with sensitive fields redacted, dropped, hashed, or truncated.
// The input map is never mutated.
// If enabled is false, a shallow copy is returned unchanged.
// If maxDepth <= 0, the default depth of 32 is used.
func SanitizePayload(payload map[string]any, enabled bool, maxDepth int) map[string]any {
	if !enabled {
		return _shallowCopy(payload)
	}
	if maxDepth <= 0 {
		maxDepth = _piiDefaultMax
	}
	rules := GetPIIRules()
	return _sanitizeMap(payload, []string{}, rules, maxDepth)
}

// _shallowCopy returns a shallow copy of m.
func _shallowCopy(m map[string]any) map[string]any {
	out := make(map[string]any, len(m))
	for k, v := range m {
		out[k] = v
	}
	return out
}

// _sanitizeMap copies the map, recursively sanitizing values.
func _sanitizeMap(m map[string]any, path []string, rules []PIIRule, depth int) map[string]any {
	out := make(map[string]any, len(m))
	for k, v := range m {
		childPath := append(path, k) //nolint:gocritic
		sanitized, drop := _sanitizeValue(k, v, childPath, rules, depth)
		if !drop {
			out[k] = sanitized
		}
	}
	return out
}

// _sanitizeSlice copies the slice, recursively sanitizing each element.
func _sanitizeSlice(s []any, path []string, rules []PIIRule, depth int) []any {
	out := make([]any, len(s))
	for i, item := range s {
		if inner, ok := item.(map[string]any); ok {
			out[i] = _sanitizeMap(inner, path, rules, depth)
		} else {
			out[i] = item
		}
	}
	return out
}

// _sanitizeValue applies custom rules then default key detection to a single value.
// Returns (sanitized value, should_drop).
func _sanitizeValue(key string, value any, path []string, rules []PIIRule, depth int) (any, bool) {
	// Apply custom rules first.
	for _, rule := range rules {
		if _applyRule(rule, path) {
			return _applyMode(value, rule.Mode, rule.TruncateTo)
		}
	}

	// Apply default sensitive key detection.
	if _isDefaultSensitiveKey(key) {
		return _piiRedacted, false
	}

	// Recurse into nested structures if depth allows.
	if depth <= 1 {
		return value, false
	}
	switch typed := value.(type) {
	case map[string]any:
		return _sanitizeMap(typed, path, rules, depth-1), false
	case []any:
		return _sanitizeSlice(typed, path, rules, depth-1), false
	}
	return value, false
}

// _applyRule returns true if the rule's Path matches the given path.
// A '*' in the rule path matches any single key.
func _applyRule(rule PIIRule, path []string) bool {
	if len(rule.Path) != len(path) {
		return false
	}
	for i, seg := range rule.Path {
		if seg != "*" && seg != path[i] {
			return false
		}
	}
	return true
}

// _applyMode applies the given mode to value and returns (result, should_drop).
func _applyMode(value any, mode string, truncateTo int) (any, bool) {
	switch mode {
	case PIIModeDrop:
		return nil, true
	case PIIModeHash:
		sum := sha256.Sum256([]byte(fmt.Sprintf("%v", value)))
		return fmt.Sprintf("%x", sum)[:12], false
	case PIIModeTruncate:
		s, ok := value.(string)
		if !ok {
			return _piiRedacted, false
		}
		if len([]rune(s)) > truncateTo {
			return string([]rune(s)[:truncateTo]), false
		}
		return s, false
	default:
		return _piiRedacted, false
	}
}

// _isDefaultSensitiveKey returns true if key contains any default sensitive substring
// (case-insensitive).
func _isDefaultSensitiveKey(key string) bool {
	lower := strings.ToLower(key)
	for _, sensitive := range _defaultSensitiveKeys {
		if strings.Contains(lower, sensitive) {
			return true
		}
	}
	return false
}
