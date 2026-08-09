// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

// Package telemetry — recursive input hardening, the structural stage of the
// signal pipeline.
//
// This is a different kind of work from pii.go: pii.go decides *policy* (which
// fields are sensitive and what to do with them), while this decides *shape*
// (how deep, how wide, how long, and what to do with values JSON cannot
// represent). Hardening runs first, so rule matching, secret detection,
// serialization and export all operate on a finite, JSON-shaped value.
//
// Before this existed the PII engine traversed exactly two shapes,
// map[string]any and []any. Anything with a concrete element type went to the
// handler verbatim: a []credentials, a map[string]string or a plain struct
// carried its Password field straight through redaction untouched.
package telemetry

import (
	"encoding"
	"math"
	"reflect"
	"slices"
	"strings"

	"github.com/provide-io/provide-telemetry/go/internal/piicore"
)

// Redacted is the sentinel every masking path substitutes for a value.
const Redacted = piicore.Redacted

// Default caps, matching TelemetryConfig's security defaults.
const (
	_defaultMaxValueLength = 1024
	_defaultMaxAttrCount   = 64
)

// Limits bounds the shape a hardened value may take.
type Limits struct {
	// MaxDepth is the nesting level at which a composite collapses to Redacted.
	MaxDepth int
	// MaxValueLength truncates longer strings, suffixing "...". 0 disables.
	MaxValueLength int
	// MaxAttrCount caps the keys retained per object. 0 disables.
	MaxAttrCount int
}

// DefaultLimits returns the caps used when no configuration is available.
func DefaultLimits() Limits {
	return Limits{
		MaxDepth:       piicore.DefaultMaxDepth,
		MaxValueLength: _defaultMaxValueLength,
		MaxAttrCount:   _defaultMaxAttrCount,
	}
}

// _limitsFromConfig reads the operator's security caps, falling back to the
// defaults for any cap left unset. A zero MaxDepth is "not configured", not
// "collapse everything" — a hand-built TelemetryConfig would otherwise redact
// every attribute it carries.
func _limitsFromConfig(cfg *TelemetryConfig) Limits {
	limits := DefaultLimits()
	if cfg.Security.MaxNestingDepth > 0 {
		limits.MaxDepth = cfg.Security.MaxNestingDepth
	}
	if cfg.Security.MaxAttrValueLength > 0 {
		limits.MaxValueLength = cfg.Security.MaxAttrValueLength
	}
	if cfg.Security.MaxAttrCount > 0 {
		limits.MaxAttrCount = cfg.Security.MaxAttrCount
	}
	return limits
}

// _unlimited is the limit set canonicalization runs under: hashing a value must
// not depend on how wide or long it was, only on what it contained. Cycles are
// still bounded, by the reference set rather than by depth.
func _unlimited() Limits {
	return Limits{MaxDepth: math.MaxInt, MaxValueLength: 0, MaxAttrCount: 0}
}

// visit identifies one reference already on the current traversal path.
// Type is part of the key because two values of different types can share an
// address — a struct and its first field, most commonly.
type visit struct {
	typ reflect.Type
	ptr uintptr
}

// Harden reduces value to a finite, JSON-shaped, non-cyclic form.
//
// The result is built only from nil, bool, int64, uint64, float64, string,
// []any and map[string]any, whatever went in. That is the contract the rest of
// the pipeline relies on: the PII engine can look inside it, and
// canonicalJSON can serialize it without a reflective fallback.
func Harden(value any, limits Limits) any {
	return hardenValue(reflect.ValueOf(value), make(map[visit]struct{}), 0, limits)
}

// hardenValue normalizes one reflected value.
//
// Pointers and interfaces are followed rather than described: what matters
// downstream is the value they reach. Every reference crossed on the way —
// pointer, map or slice — is recorded in seen and never removed, so a value
// reached a second time anywhere in the walk collapses to Redacted instead of
// expanding. That single rule covers a true cycle (an infinite serializer) and
// a subtree shared n times (an n-fold blowup), and both arrive from
// caller-supplied data. TypeScript's WeakSet has exactly this reach, and its
// suite pins the shared-sibling case, so the bound has to be the walk rather
// than the current path for the two SDKs to agree.
func hardenValue(v reflect.Value, seen map[visit]struct{}, depth int, limits Limits) any {
	v, early, decided := _followReferences(v, seen, limits)
	if decided {
		return early
	}
	if !v.IsValid() {
		return nil
	}
	if id, tracked := _containerIdentity(v); tracked && _repeatReference(id, seen) {
		return Redacted
	}
	if text, ok := _hardenAsText(v, limits); ok {
		return text
	}
	return hardenKind(v, seen, depth, limits)
}

// _followReferences walks pointers and interfaces down to the value they reach.
//
// Split out of hardenValue only to keep it under the cyclomatic bound. The
// third result reports that the walk itself settled the answer — a nil
// reference, a second crossing of the same pointer, or a self-describing one —
// in which case the second result is that answer and the returned value must
// not be used.
func _followReferences(
	v reflect.Value,
	seen map[visit]struct{},
	limits Limits,
) (reflect.Value, any, bool) {
	for v.Kind() == reflect.Interface || v.Kind() == reflect.Pointer {
		if v.IsNil() {
			return v, nil, true
		}
		if v.Kind() == reflect.Pointer {
			if _repeatReference(visit{v.Type(), v.Pointer()}, seen) {
				return v, Redacted, true
			}
			// Self-description is checked on the pointer as well as on the
			// pointee: error and MarshalText are normally declared on the
			// pointer receiver, and *errors.errorString keeps its message in
			// an unexported field — dereferencing first loses it entirely.
			if text, ok := _hardenAsText(v, limits); ok {
				return v, text, true
			}
		}
		v = v.Elem()
	}
	return v, nil, false
}

// _repeatReference records id and reports whether the walk had already crossed it.
func _repeatReference(id visit, seen map[visit]struct{}) bool {
	if _, repeat := seen[id]; repeat {
		return true
	}
	seen[id] = struct{}{}
	return false
}

// _containerIdentity returns the reference identity of a map or slice. Only
// these two kinds carry one: an array or struct reached by value is a copy, so
// two of them being equal is not the sharing this guards against.
//
// Empty containers are exempt. They have nothing to recurse into, so they
// cannot be part of a cycle, and Go hands every zero-size allocation the same
// address — tracking them would collapse the second of two unrelated empty
// slices into Redacted.
func _containerIdentity(v reflect.Value) (visit, bool) {
	switch v.Kind() {
	case reflect.Map, reflect.Slice:
		if v.IsNil() || v.Len() == 0 {
			return visit{}, false
		}
		return visit{v.Type(), v.Pointer()}, true
	default:
		return visit{}, false
	}
}

// _hardenAsText renders the types that describe themselves better than their
// fields do.
//
// error and encoding.TextMarshaler both have a documented, stable string form,
// and their fields are usually unexported — traversing *errors.errorString
// yields an empty map, losing the message entirely. fmt.Stringer is
// deliberately NOT in this set: it is implemented widely enough that honoring
// it would swallow exactly the typed structs this file exists to traverse.
func _hardenAsText(v reflect.Value, limits Limits) (any, bool) {
	switch typed := v.Interface().(type) {
	case error:
		return hardenString(typed.Error(), limits), true
	case encoding.TextMarshaler:
		text, err := typed.MarshalText()
		if err != nil {
			// A type that cannot describe itself gets no second guess:
			// exporting whatever half-formed bytes it returned is worse.
			return Redacted, true
		}
		return hardenString(string(text), limits), true
	default:
		return nil, false
	}
}

// hardenKind dispatches on the reflected kind once pointers, interfaces and
// self-describing types have been resolved.
func hardenKind(v reflect.Value, seen map[visit]struct{}, depth int, limits Limits) any {
	if scalar, ok := hardenScalar(v, limits); ok {
		return scalar
	}
	if depth >= limits.MaxDepth {
		return Redacted
	}
	switch v.Kind() {
	case reflect.Map:
		return hardenMap(v, seen, depth, limits)
	case reflect.Slice, reflect.Array:
		return hardenList(v, seen, depth, limits)
	case reflect.Struct:
		return hardenStruct(v, seen, depth, limits)
	default:
		// chan, func, complex and unsafe.Pointer have no JSON shape, and no
		// rendering of one carries information a consumer could use.
		return Redacted
	}
}

// hardenScalar handles the leaves. Widening every integer to int64/uint64 and
// every float to float64 is what makes the output invariant: the hash of a
// value must not depend on whether the caller happened to hold it in an int32.
func hardenScalar(v reflect.Value, limits Limits) (any, bool) {
	switch v.Kind() {
	case reflect.String:
		return hardenString(v.String(), limits), true
	case reflect.Bool:
		return v.Bool(), true
	case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64:
		return v.Int(), true
	case reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32, reflect.Uint64, reflect.Uintptr:
		return v.Uint(), true
	case reflect.Float32, reflect.Float64:
		return v.Float(), true
	case reflect.Map, reflect.Slice:
		if v.IsNil() {
			// A nil container is absence, not an empty container: reporting
			// {} or [] would claim the caller sent something they did not.
			return nil, true
		}
		if v.Kind() == reflect.Slice && v.Type().Elem().Kind() == reflect.Uint8 {
			return hardenString(string(v.Bytes()), limits), true
		}
		return nil, false
	default:
		return nil, false
	}
}

// hardenString strips the control characters that corrupt a log stream, then
// applies the length cap. Cleaning first so the cap counts characters a reader
// will actually see.
//
// TAB, LF and CR survive — they are legitimate content in a message or a stack
// trace. The surviving set is character for character the one Python's
// harden_input uses, so the same input yields the same string in both SDKs.
func hardenString(s string, limits Limits) string {
	cleaned := strings.Map(func(r rune) rune {
		if r == '\t' || r == '\n' || r == '\r' {
			return r
		}
		if r < 0x20 || r == 0x7f {
			return -1
		}
		return r
	}, s)
	if limits.MaxValueLength <= 0 {
		return cleaned
	}
	runes := []rune(cleaned)
	if len(runes) <= limits.MaxValueLength {
		return cleaned
	}
	return string(runes[:limits.MaxValueLength]) + piicore.TruncationSuffix
}

// hardenMap normalizes a map to map[string]any.
//
// Keys are visited in sorted order so that the attribute cap keeps the same
// subset every time: Go randomizes map iteration, and a cap applied to a random
// order would drop a different field on every record.
func hardenMap(v reflect.Value, seen map[visit]struct{}, depth int, limits Limits) any {
	if v.Type().Key().Kind() != reflect.String {
		// JSON has no encoding for a non-string key, and inventing one (the
		// key's %v form) would silently merge keys that were distinct.
		return Redacted
	}
	keys := v.MapKeys()
	slices.SortFunc(keys, func(a, b reflect.Value) int {
		return strings.Compare(a.String(), b.String())
	})
	out := make(map[string]any, len(keys))
	for _, key := range keys {
		if limits.MaxAttrCount > 0 && len(out) >= limits.MaxAttrCount {
			break
		}
		out[key.String()] = hardenValue(v.MapIndex(key), seen, depth+1, limits)
	}
	return out
}

// hardenList normalizes an array or slice to []any, preserving order.
//
// Element count is deliberately not capped: MaxAttrCount is "keys retained per
// object" in every SDK, and truncating a list here would put Go's exported
// payload out of step with the others.
func hardenList(v reflect.Value, seen map[visit]struct{}, depth int, limits Limits) any {
	out := make([]any, 0, v.Len())
	for i := range v.Len() {
		out = append(out, hardenValue(v.Index(i), seen, depth+1, limits))
	}
	return out
}

// hardenStruct normalizes a struct to map[string]any keyed by JSON name.
// Unexported fields are skipped: they are unreachable through reflection
// without unsafe, and a caller who kept a field unexported did not publish it.
func hardenStruct(v reflect.Value, seen map[visit]struct{}, depth int, limits Limits) any {
	typ := v.Type()
	out := make(map[string]any, typ.NumField())
	for i := range typ.NumField() {
		field := typ.Field(i)
		if !field.IsExported() {
			continue
		}
		name, keep := _jsonFieldName(field)
		if !keep {
			continue
		}
		if limits.MaxAttrCount > 0 && len(out) >= limits.MaxAttrCount {
			break
		}
		out[name] = hardenValue(v.Field(i), seen, depth+1, limits)
	}
	return out
}

// _jsonFieldName resolves the key a field is hardened under.
//
// The encoding/json tag is honored so a hardened struct carries the names its
// JSON form would, and so that json:"-" — a caller saying "never serialize
// this" — is obeyed by telemetry too. The exotic json:"-," spelling for a field
// literally named "-" is treated as a skip; no telemetry field is named "-".
func _jsonFieldName(field reflect.StructField) (string, bool) {
	tag, tagged := field.Tag.Lookup("json")
	if !tagged {
		return field.Name, true
	}
	name, _, _ := strings.Cut(tag, ",")
	if name == "-" {
		return "", false
	}
	if name == "" {
		return field.Name, true
	}
	return name, true
}

// _hardenAttrs bounds a log record's attribute map in place of the caller's.
// A nil map hardens to nil rather than to a map, so the original is returned:
// the handler chain downstream indexes it.
func _hardenAttrs(attrs map[string]any, limits Limits) map[string]any {
	if hardened, ok := Harden(attrs, limits).(map[string]any); ok {
		return hardened
	}
	return attrs
}
