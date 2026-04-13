// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package logger

import (
	"crypto/sha256"
	"fmt"
	"regexp"
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
	_piiRedacted         = "***"
	_piiTruncationSuffix = "..."
	_piiDefaultMax       = 8
)

// _defaultSensitiveKeys lists case-insensitive exact-match key names.
var _defaultSensitiveKeys = map[string]struct{}{
	"password":       {},
	"passwd":         {},
	"secret":         {},
	"token":          {},
	"api_key":        {},
	"apikey":         {},
	"auth":           {},
	"authorization":  {},
	"credential":     {},
	"private_key":    {},
	"ssn":            {},
	"credit_card":    {},
	"creditcard":     {},
	"cvv":            {},
	"pin":            {},
	"account_number": {},
	"cookie":         {},
}

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
	out := make([]SecretPattern, 0, len(_secretPatterns)+len(_customSecretPats))
	for i, re := range _secretPatterns {
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
		return _shallowCopy(payload)
	}
	_piiMu.RLock()
	delegate := _sanitizeDelegate
	_piiMu.RUnlock()
	if delegate != nil {
		return delegate(payload, enabled, maxDepth)
	}
	if maxDepth <= 0 {
		maxDepth = _piiDefaultMax
	}
	rules := GetPIIRules()
	result := _sanitizeMap(payload, []string{}, rules, maxDepth)
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

func _shallowCopy(m map[string]any) map[string]any {
	out := make(map[string]any, len(m))
	for k, v := range m {
		out[k] = v
	}
	return out
}

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

func _sanitizeSlice(s []any, path []string, rules []PIIRule, depth int) []any {
	out := make([]any, 0, len(s))
	for _, item := range s {
		if inner, ok := item.(map[string]any); ok {
			out = append(out, _sanitizeMap(inner, path, rules, depth))
		} else {
			sanitized, drop := _sanitizeValue("", item, path, rules, depth)
			if !drop {
				out = append(out, sanitized)
			}
		}
	}
	return out
}

func _fireReceiptHook(hook func(string, string, any), fieldPath, action string, original any) {
	if hook != nil {
		hook(fieldPath, action, original)
	}
}

func _sanitizeValue(key string, value any, path []string, rules []PIIRule, depth int) (any, bool) {
	_piiMu.RLock()
	receiptHook := _receiptHook
	_piiMu.RUnlock()
	for _, rule := range rules {
		if _applyRule(rule, path) {
			_fireReceiptHook(receiptHook, strings.Join(path, "."), rule.Mode, value)
			return _applyMode(value, rule.Mode, rule.TruncateTo)
		}
	}
	if _isDefaultSensitiveKey(key) {
		_fireReceiptHook(receiptHook, key, PIIModeRedact, value)
		return _piiRedacted, false
	}
	if str, ok := value.(string); ok && _detectSecretInValue(str) {
		_fireReceiptHook(receiptHook, key, PIIModeRedact, value)
		return _piiRedacted, false
	}
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

func _applyMode(value any, mode string, truncateTo int) (any, bool) {
	switch mode {
	case PIIModeDrop:
		return nil, true
	case PIIModeHash:
		sum := sha256.Sum256([]byte(fmt.Sprintf("%v", value)))
		return fmt.Sprintf("%x", sum)[:12], false
	case PIIModeTruncate:
		s := fmt.Sprintf("%v", value)
		runes := []rune(s)
		if len(runes) >= truncateTo+1 {
			return string(runes[:truncateTo]) + _piiTruncationSuffix, false
		}
		return s, false
	default:
		return _piiRedacted, false
	}
}

func _isDefaultSensitiveKey(key string) bool {
	_, ok := _defaultSensitiveKeys[strings.ToLower(key)]
	return ok
}

const _minSecretLength = 20

var _secretPatterns = []*regexp.Regexp{
	regexp.MustCompile(`(?:AKIA|ASIA)[A-Z0-9]{16}`),
	regexp.MustCompile(`eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}`),
	regexp.MustCompile(`gh[pos]_[A-Za-z0-9_]{36,}`),
	regexp.MustCompile(`[0-9a-fA-F]{40,}`),
	regexp.MustCompile(`[A-Za-z0-9+/]{40,}={0,2}`),
}

func _detectSecretInValue(s string) bool {
	if len(s) < _minSecretLength {
		return false
	}
	for _, re := range _secretPatterns {
		if re.MatchString(s) {
			return true
		}
	}
	_piiMu.RLock()
	customs := _customSecretPats
	for _, re := range customs {
		if re.MatchString(s) {
			_piiMu.RUnlock()
			return true
		}
	}
	_piiMu.RUnlock()
	return false
}
