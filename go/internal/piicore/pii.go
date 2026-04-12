// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// Package piicore contains the stateless PII sanitization engine shared by
// the top-level telemetry package and the logger sub-package.  All mutable
// state (rule lists, hooks, custom patterns) lives in the callers; this
// package only provides pure functions.
package piicore

import (
	"crypto/sha256"
	"fmt"
	"regexp"
	"strings"
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

// Exported sentinel values used by both callers.
const (
	Redacted         = "***"
	TruncationSuffix = "..."
	DefaultMaxDepth  = 8
)

// DefaultSensitiveKeys lists case-insensitive exact-match key names that are
// redacted automatically even when no custom rule matches.
var DefaultSensitiveKeys = map[string]struct{}{
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

// BuiltinSecretPatterns are the compiled regexps checked against every string // pragma: allowlist secret
// value when no custom rule matches.
var BuiltinSecretPatterns = []*regexp.Regexp{ // pragma: allowlist secret
	regexp.MustCompile(`(?:AKIA|ASIA)[A-Z0-9]{16}`),
	regexp.MustCompile(`eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}`),
	regexp.MustCompile(`gh[pos]_[A-Za-z0-9_]{36,}`),
	regexp.MustCompile(`[0-9a-fA-F]{40,}`),
	regexp.MustCompile(`[A-Za-z0-9+/]{40,}={0,2}`),
}

// MinSecretLength is the minimum string length checked against secret patterns. // pragma: allowlist secret
const MinSecretLength = 20 // pragma: allowlist secret

// ApplyRule returns true if rule.Path matches path (supports '*' wildcards).
func ApplyRule(rule PIIRule, path []string) bool {
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

// ApplyMode applies the given mode to value and returns (result, should_drop).
func ApplyMode(value any, mode string, truncateTo int) (any, bool) {
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
			return string(runes[:truncateTo]) + TruncationSuffix, false
		}
		return s, false
	default:
		return Redacted, false
	}
}

// IsDefaultSensitiveKey returns true if key exactly matches a default
// sensitive key name, case-insensitively.
func IsDefaultSensitiveKey(key string) bool {
	_, ok := DefaultSensitiveKeys[strings.ToLower(key)]
	return ok
}

// DetectSecretInValue returns true if s matches any built-in secret pattern // pragma: allowlist secret
// or any of the caller-supplied custom patterns.
// customPatterns may be nil.
func DetectSecretInValue(s string, customPatterns map[string]*regexp.Regexp) bool { // pragma: allowlist secret
	if len(s) < MinSecretLength { // pragma: allowlist secret
		return false
	}
	for _, re := range BuiltinSecretPatterns {
		if re.MatchString(s) {
			return true
		}
	}
	for _, re := range customPatterns {
		if re.MatchString(s) {
			return true
		}
	}
	return false
}

// FireReceiptHook calls hook if non-nil.
func FireReceiptHook(hook func(string, string, any), fieldPath, action string, original any) {
	if hook != nil {
		hook(fieldPath, action, original)
	}
}

// ShallowCopy returns a shallow copy of m.
func ShallowCopy(m map[string]any) map[string]any {
	out := make(map[string]any, len(m))
	for k, v := range m {
		out[k] = v
	}
	return out
}

// SanitizeMap copies the map, recursively sanitizing values.
// receiptHook may be nil; customPatterns may be nil.
func SanitizeMap(
	m map[string]any,
	path []string,
	rules []PIIRule,
	depth int,
	receiptHook func(string, string, any),
	customPatterns map[string]*regexp.Regexp,
) map[string]any {
	out := make(map[string]any, len(m))
	for k, v := range m {
		childPath := append(path, k) //nolint:gocritic
		sanitized, drop := SanitizeValue(k, v, childPath, rules, depth, receiptHook, customPatterns)
		if !drop {
			out[k] = sanitized
		}
	}
	return out
}

// SanitizeSlice copies the slice, recursively sanitizing each element.
func SanitizeSlice(
	s []any,
	path []string,
	rules []PIIRule,
	depth int,
	receiptHook func(string, string, any),
	customPatterns map[string]*regexp.Regexp,
) []any {
	out := make([]any, 0, len(s))
	for _, item := range s {
		if inner, ok := item.(map[string]any); ok {
			out = append(out, SanitizeMap(inner, path, rules, depth, receiptHook, customPatterns))
		} else {
			sanitized, drop := SanitizeValue("", item, path, rules, depth, receiptHook, customPatterns)
			if !drop {
				out = append(out, sanitized)
			}
		}
	}
	return out
}

// SanitizeValue applies custom rules, then default key detection, to a single value.
// Returns (sanitized value, should_drop).
func SanitizeValue(
	key string,
	value any,
	path []string,
	rules []PIIRule,
	depth int,
	receiptHook func(string, string, any),
	customPatterns map[string]*regexp.Regexp,
) (any, bool) {
	// Apply custom rules first.
	for _, rule := range rules {
		if ApplyRule(rule, path) {
			FireReceiptHook(receiptHook, strings.Join(path, "."), rule.Mode, value)
			return ApplyMode(value, rule.Mode, rule.TruncateTo)
		}
	}

	// Apply default sensitive key detection.
	if IsDefaultSensitiveKey(key) {
		FireReceiptHook(receiptHook, key, PIIModeRedact, value)
		return Redacted, false
	}

	// Scan string values for known secret patterns.
	if str, ok := value.(string); ok && DetectSecretInValue(str, customPatterns) {
		FireReceiptHook(receiptHook, key, PIIModeRedact, value)
		return Redacted, false
	}

	// Recurse into nested structures if depth allows.
	if depth <= 1 {
		return value, false
	}
	switch typed := value.(type) {
	case map[string]any:
		return SanitizeMap(typed, path, rules, depth-1, receiptHook, customPatterns), false
	case []any:
		return SanitizeSlice(typed, path, rules, depth-1, receiptHook, customPatterns), false
	}
	return value, false
}
