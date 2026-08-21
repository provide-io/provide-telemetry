// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// Package piicore contains the stateless PII sanitization engine shared by
// the top-level telemetry package and the logger sub-package.  All mutable
// state (rule lists, hooks, custom patterns) lives in the callers; this
// package only provides pure functions. The one exception is the hash
// canonicalizer hook (SetHashCanonicalizer), which exists because the RFC
// 8785 serializer lives in the root package and the root package imports
// this one.
package piicore

import (
	"crypto/sha256"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"sync/atomic"
)

// PIIRule defines a rule for sanitizing a specific field path.
//
// TruncateTo only matters in truncate mode. Go's zero value means "unset":
// the root package normalises 0 to DefaultTruncateTo when the rule is
// registered, so a rule built without a limit truncates to 8 code points like
// every other SDK. A negative limit is clamped to 0 at apply time, which
// keeps nothing but the suffix — never an error, never the whole value.
type PIIRule struct {
	Path       []string
	Mode       string
	TruncateTo int
}

// DefaultTruncateTo is the truncate-mode limit used when a rule carries none.
const DefaultTruncateTo = 8

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

// hashCanonicalizer renders a non-string value to the text hash mode digests.
//
// The contract is the RFC 8785 canonical JSON of the value — the same
// serializer the redaction receipts use — so that every SDK hashes true as
// "true", nil as "null" and an object key-sorted. That serializer lives in the
// root package, which imports this one, so it is installed here at init
// through SetHashCanonicalizer rather than imported. Until one is installed
// (this package's own tests, or a binary that links only a sub-package) the
// fallback is fmt's %v rendering.
var hashCanonicalizer atomic.Pointer[func(any) string]

// SetHashCanonicalizer installs the renderer hash mode uses for non-string
// values. Passing nil restores the %v fallback.
func SetHashCanonicalizer(fn func(any) string) {
	if fn == nil {
		hashCanonicalizer.Store(nil)
		return
	}
	hashCanonicalizer.Store(&fn)
}

// hashInput returns the bytes-as-text that hash mode digests for value: the
// string itself, or the canonical rendering of anything else.
func hashInput(value any) string {
	if s, ok := value.(string); ok {
		return s
	}
	if fn := hashCanonicalizer.Load(); fn != nil {
		return (*fn)(value)
	}
	return fmt.Sprintf("%v", value)
}

// ApplyMode applies the given mode to value and returns (result, should_drop).
//
// Truncate counts Unicode code points, never bytes or UTF-16 units, so an
// astral character is kept or dropped whole. A limit of 0 yields exactly the
// suffix; a negative limit is clamped to 0 rather than panicking on the slice.
func ApplyMode(value any, mode string, truncateTo int) (any, bool) {
	switch mode {
	case PIIModeDrop:
		return nil, true
	case PIIModeHash:
		sum := sha256.Sum256([]byte(hashInput(value)))
		return fmt.Sprintf("%x", sum)[:12], false
	case PIIModeTruncate:
		s := fmt.Sprintf("%v", value)
		limit := max(truncateTo, 0)
		runes := []rune(s)
		if len(runes) > limit {
			return string(runes[:limit]) + TruncationSuffix, false
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
	return len(secretSpans(s, customPatterns)) > 0
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

// secretSpans returns every secret-looking span in s, each widened to its
// whitespace-delimited token, sorted and coalesced.
//
// Every pattern is scanned across the WHOLE value, not stopped at its first
// match, and every pattern is tried even after one has hit. Skipping either
// leaks:
//
//   - Stopping a pattern at its first match let a path shadow a real secret.
//     long_base64 matches a path first; suppressing that match as path-shaped
//     moved the scan to the next pattern, and long_base64 is the last one, so
//     the credential behind the path was never looked for at all.
//   - Stopping at the first pattern to hit left a field's second and third
//     secrets in the log, which whole-value blanking used to cover for free.
//
// Collecting every span also makes the result independent of map iteration
// order, which Go randomises — with one span the chosen secret varied between
// runs and diverged from the other four runtimes.
//
// FindStringIndex runs first as a fast path: a clean value, which is nearly
// every log field, pays one scan per pattern and allocates nothing, because
// FindAllStringIndex is only reached once a pattern is known to match.
func secretSpans(s string, customPatterns map[string]*regexp.Regexp) [][2]int {
	if len(s) < MinSecretLength { // pragma: allowlist secret
		return nil
	}
	var spans [][2]int
	collect := func(re *regexp.Regexp) {
		if re.FindStringIndex(s) == nil {
			return
		}
		for _, loc := range re.FindAllStringIndex(s, -1) {
			// A registered pattern that can match the empty string carries no
			// secret; widening a zero-length match to its token would redact a
			// word for nothing.
			if loc[0] == loc[1] {
				continue
			}
			if !looksLikePath(s[loc[0]:loc[1]]) {
				spans = append(spans, expandToToken(s, loc[0], loc[1]))
			}
		}
	}
	for _, re := range BuiltinSecretPatterns {
		collect(re)
	}
	for _, re := range customPatterns {
		collect(re)
	}
	return mergeSpans(spans)
}

// expandToToken widens a match to its whitespace-delimited token.
//
// Redacting the literal match alone can leave part of a credential behind:
// the jwt pattern matches header.payload, and a JWT has THREE dot-separated
// parts, so the signature would survive. Whitespace is the boundary a secret
// cannot cross without ceasing to be one token.
func expandToToken(s string, start, end int) [2]int {
	for start > 0 && !isSpaceByte(s[start-1]) {
		start--
	}
	for end < len(s) && !isSpaceByte(s[end]) {
		end++
	}
	return [2]int{start, end}
}

// mergeSpans sorts spans and coalesces overlaps so each region is replaced
// once. Two patterns can match the same credential — long_base64 and jwt both
// hit a JWT — and after widening they overlap exactly, which would otherwise
// emit "******".
func mergeSpans(spans [][2]int) [][2]int {
	if len(spans) < 2 {
		return spans
	}
	sort.Slice(spans, func(i, j int) bool { return spans[i][0] < spans[j][0] })
	merged := spans[:1]
	for _, span := range spans[1:] {
		last := &merged[len(merged)-1]
		if span[0] <= last[1] {
			if span[1] > last[1] {
				last[1] = span[1]
			}
			continue
		}
		merged = append(merged, span)
	}
	return merged
}

// RedactSecretSpans replaces every secret-looking token of s, leaving the rest
// of the string readable.
//
// Every span goes, not just the first: whole-value blanking removed a field's
// second and third credentials for free, and scoping redaction to a token
// silently dropped that guarantee.
func RedactSecretSpans(s string, customPatterns map[string]*regexp.Regexp) string {
	spans := secretSpans(s, customPatterns)
	if len(spans) == 0 {
		return s
	}
	return replaceSpans(s, spans)
}

// replaceSpans swaps each span for the redaction sentinel.
func replaceSpans(s string, spans [][2]int) string {
	var out strings.Builder
	prev := 0
	for _, span := range spans {
		out.WriteString(s[prev:span[0]])
		out.WriteString(Redacted)
		prev = span[1]
	}
	out.WriteString(s[prev:])
	return out.String()
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

	// Scan string values for known secret patterns. One scan, not two:
	// detecting and then redacting ran the whole pattern sweep twice for every
	// value carrying a credential.
	if str, ok := value.(string); ok {
		if spans := secretSpans(str, customPatterns); len(spans) > 0 {
			FireReceiptHook(receiptHook, key, PIIModeRedact, value)
			// Span-scoped: only the credential tokens go, the message stays.
			return replaceSpans(str, spans), false
		}
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
