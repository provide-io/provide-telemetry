// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"fmt"
	"regexp"
	"sync"
	"sync/atomic"

	"github.com/provide-io/provide-telemetry/go/internal/piicore"
)

// PIIRule defines a rule for sanitizing a specific field path.
//
// In truncate mode a zero TruncateTo means "unset" and is normalised to
// DefaultTruncateTo when the rule is registered; a negative TruncateTo is
// clamped to 0 at apply time, so the output is exactly the suffix.
type PIIRule = piicore.PIIRule

// PII mode constants.
const (
	PIIModeRedact   = piicore.PIIModeRedact
	PIIModeDrop     = piicore.PIIModeDrop
	PIIModeHash     = piicore.PIIModeHash
	PIIModeTruncate = piicore.PIIModeTruncate
)

// DefaultTruncateTo is the truncate-mode limit a rule registered without one
// receives, matching the other SDKs' default of 8 code points.
const DefaultTruncateTo = piicore.DefaultTruncateTo

// Hash mode digests the RFC 8785 canonical JSON of a non-string value, which
// is the serializer the receipts already use. piicore cannot import it — the
// dependency runs the other way — so it is handed over here, before any rule
// can run.
func init() {
	piicore.SetHashCanonicalizer(CanonicalJSON)
}

// _normalizePIIRule fills in the defaults a stored rule must carry: a
// truncate rule whose TruncateTo was left at Go's zero value takes
// DefaultTruncateTo. Negative limits are left alone — piicore clamps them to 0
// at apply time — and other modes ignore the field entirely.
func _normalizePIIRule(rule PIIRule) PIIRule {
	if rule.Mode == PIIModeTruncate && rule.TruncateTo == 0 {
		rule.TruncateTo = DefaultTruncateTo
	}
	return rule
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
	_policyHook         func(label string) string
	_receiptHook        func(fieldPath string, action string, originalValue any)
	_customSecretPats   map[string]*regexp.Regexp
	// _customSecretPatsCache holds an immutable snapshot of _customSecretPats
	// so hot-path readers (message-body secret scrubbing inside the logger
	// handler chain) can load the current pattern map with a single atomic
	// operation — no RLock, no map copy. The snapshot is swapped whenever
	// _customSecretPats is mutated (RegisterSecretPattern / _resetSecretPatterns).
	_customSecretPatsCache atomic.Pointer[map[string]*regexp.Regexp]
)

// _publishCustomSecretPatsSnapshot installs an immutable snapshot of the
// current _customSecretPats map into _customSecretPatsCache. Caller MUST hold
// _piiMu for writing (so the snapshot matches the authoritative map).
func _publishCustomSecretPatsSnapshot() {
	if len(_customSecretPats) == 0 {
		_customSecretPatsCache.Store(nil)
		return
	}
	snapshot := make(map[string]*regexp.Regexp, len(_customSecretPats))
	for name, re := range _customSecretPats {
		snapshot[name] = re
	}
	_customSecretPatsCache.Store(&snapshot)
}

// _loadCustomSecretPatsSnapshot returns the latest published snapshot, or nil
// if no custom patterns are registered. The returned map must be treated as
// read-only — mutating it would corrupt the snapshot shared across goroutines.
func _loadCustomSecretPatsSnapshot() map[string]*regexp.Regexp {
	p := _customSecretPatsCache.Load()
	if p == nil {
		return nil
	}
	return *p
}

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
	// Publish a fresh snapshot so concurrent hot-path readers see the new
	// pattern without taking the RWMutex or reallocating on every record.
	_publishCustomSecretPatsSnapshot()
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
	_publishCustomSecretPatsSnapshot()
}

// SetClassificationHook registers a classification callback on the PII engine.
// Pass nil to deregister.
func SetClassificationHook(fn func(string, any) string) {
	_piiMu.Lock()
	defer _piiMu.Unlock()
	_classificationHook = fn
}

// SetPolicyHook registers a policy lookup callback on the PII engine.
// The callback returns the action ("drop"|"redact"|"hash"|"truncate"|"pass") for a label.
// Pass nil to deregister.
func SetPolicyHook(fn func(label string) string) {
	_piiMu.Lock()
	defer _piiMu.Unlock()
	_policyHook = fn
}

// SetReceiptHook registers a redaction receipt callback on the PII engine.
// Pass nil to deregister.
func SetReceiptHook(fn func(string, string, any)) {
	_piiMu.Lock()
	defer _piiMu.Unlock()
	_receiptHook = fn
}

// SetPIIRules replaces the global PII rule list. Each rule is normalised on
// the way in (see _normalizePIIRule), so GetPIIRules reports the limit a
// truncate rule will actually apply.
func SetPIIRules(rules []PIIRule) {
	_piiMu.Lock()
	defer _piiMu.Unlock()
	cp := make([]PIIRule, len(rules))
	for i, rule := range rules {
		cp[i] = _normalizePIIRule(rule)
	}
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
	_policyHook = nil
	_receiptHook = nil
}

// _applyClassificationPolicy applies classification tags and policy actions (drop/redact/hash/truncate/pass)
// to each top-level key in result that matches the classHook. Keys with action "drop" are removed.
// All other matching keys get a "__key__class" tag; masking actions additionally replace the value.
// The result map is mutated in place.
func _applyClassificationPolicy(
	result map[string]any,
	classHook func(string, any) string,
	policyHook func(string) string,
) {
	// Collect keys first to avoid mutating the map while iterating.
	keys := make([]string, 0, len(result))
	for k := range result {
		keys = append(keys, k)
	}
	for _, k := range keys {
		v := result[k]
		label := classHook(k, v)
		if label == "" {
			continue
		}
		action := piicore.PIIModePass
		if policyHook != nil {
			action = policyHook(label)
		}
		if action == piicore.PIIModeDrop {
			delete(result, k)
			// No class tag for dropped keys.
			continue
		}
		result["__"+k+"__class"] = label
		_applyMaskAction(result, k, v, action)
	}
}

// _applyMaskAction replaces result[k] with a masked value when action is redact/hash/truncate,
// unless the current value is already the redaction sentinel. Pass and unknown actions are no-ops.
func _applyMaskAction(result map[string]any, k string, v any, action string) {
	if action != piicore.PIIModeRedact && action != piicore.PIIModeHash && action != piicore.PIIModeTruncate {
		return
	}
	if strVal, ok := v.(string); ok && strVal == piicore.Redacted {
		return // already redacted — do not double-mask
	}
	masked, drop := piicore.ApplyMode(v, action, piicore.DefaultTruncateTo)
	if !drop {
		result[k] = masked
	}
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

	// Apply classification tags and policy actions for top-level keys if hook is registered.
	_piiMu.RLock()
	classHook := _classificationHook
	policyHook := _policyHook
	_piiMu.RUnlock()
	if classHook != nil {
		_applyClassificationPolicy(result, classHook, policyHook)
	}
	return result
}
