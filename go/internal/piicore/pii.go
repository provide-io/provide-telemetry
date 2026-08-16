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
	PIIModePass     = "pass"
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
// value when no custom rule matches. Patterns are sourced from the generated file.
var BuiltinSecretPatterns = generatedSecretPatterns // pragma: allowlist secret

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
	return secretSpan(s, customPatterns) != nil
}

// pathMinSegments is how many slash-separated parts a span needs before its
// shape is considered path-like.
const pathMinSegments = 3

// looksLikePath reports whether a matched span is a filesystem path rather
// than a secret.
//
// The long_base64 pattern is [A-Za-z0-9+/]{40,} and "/" belongs to the base64
// alphabet, so any deep path of unpunctuated segments matched it:
// /home/deploy/apps/production/current/lib/service is 48 characters of pure
// base64 alphabet holding no secret. Narrowing the charset is not the fix —
// dropping "/" costs 44% of detections on 32-byte secrets, since a 44-char
// base64 string containing one slash cannot be told from a path by charset.
//
// Shape separates them: a path carries several short all-lowercase words
// (usr, local, lib), which random base64 effectively never produces — a
// 20-character all-lowercase run has probability (26/64)^20, about 1e-8.
func looksLikePath(span string) bool {
	segments := make([]string, 0, 8)
	for _, seg := range strings.Split(span, "/") {
		if seg != "" {
			segments = append(segments, seg)
		}
	}
	if len(segments) < pathMinSegments {
		return false
	}
	wordy := 0
	for _, seg := range segments {
		if isLowerAlpha(seg) {
			wordy++
		}
	}
	return wordy*2 >= len(segments)
}

func isLowerAlpha(s string) bool {
	for _, r := range s {
		if r < 'a' || r > 'z' {
			return false
		}
	}
	return s != ""
}

// secretSpan returns the [start,end) span of the first secret-looking match,
// or nil when the value holds none.
func secretSpan(s string, customPatterns map[string]*regexp.Regexp) []int {
	if len(s) < MinSecretLength { // pragma: allowlist secret
		return nil
	}
	for _, re := range BuiltinSecretPatterns {
		if loc := re.FindStringIndex(s); loc != nil && !looksLikePath(s[loc[0]:loc[1]]) {
			return loc
		}
	}
	for _, re := range customPatterns {
		if loc := re.FindStringIndex(s); loc != nil && !looksLikePath(s[loc[0]:loc[1]]) {
			return loc
		}
	}
	return nil
}

// RedactSecretSpans replaces only the secret-looking token of s, leaving the
// rest of the string readable.
//
// The match is first widened to its whitespace-delimited token. Redacting the
// literal match alone can leave part of a credential behind: the jwt pattern
// matches header.payload, and a JWT has THREE dot-separated parts, so the
// signature would survive. Whitespace is the boundary a secret cannot cross
// without ceasing to be one token.
func RedactSecretSpans(s string, customPatterns map[string]*regexp.Regexp) string {
	loc := secretSpan(s, customPatterns)
	if loc == nil {
		return s
	}
	start, end := loc[0], loc[1]
	for start > 0 && !isSpaceByte(s[start-1]) {
		start--
	}
	for end < len(s) && !isSpaceByte(s[end]) {
		end++
	}
	return s[:start] + Redacted + s[end:]
}

func isSpaceByte(b byte) bool {
	return b == ' ' || b == '\t' || b == '\n' || b == '\r' || b == '\v' || b == '\f'
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
		// Span-scoped: only the credential token goes, the message stays.
		return RedactSecretSpans(str, customPatterns), false
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
