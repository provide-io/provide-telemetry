// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

package telemetry

import (
	"math"
	"testing"
)

// TestCanonicalNumberMatchesECMAScript pins the number grammar RFC 8785
// inherits from ECMAScript's Number::toString. Go's own formatters agree with
// none of it: %v switches to exponential at a different magnitude, and strconv
// renders negative zero as "-0".
//
// The expectations are the strings `String(x)` produces in a JavaScript engine.
func TestCanonicalNumberMatchesECMAScript(t *testing.T) {
	cases := []struct {
		value float64
		want  string
	}{
		{0, "0"},
		{math.Copysign(0, -1), "0"},
		{1.5, "1.5"},
		{-1.5, "-1.5"},
		{-0.5, "-0.5"},
		{2, "2"},
		{100, "100"},
		{123.456, "123.456"},
		{0.001, "0.001"},
		{1e-6, "0.000001"},
		{1e-7, "1e-7"},
		{1.5e-7, "1.5e-7"},
		{1e20, "100000000000000000000"},
		{1e21, "1e+21"},
		{1.5e21, "1.5e+21"},
		{math.NaN(), "null"},
		{math.Inf(1), "null"},
		{math.Inf(-1), "null"},
	}
	for _, tc := range cases {
		if got := canonicalNumber(tc.value); got != tc.want {
			t.Errorf("canonicalNumber(%v) = %q, want %q", tc.value, got, tc.want)
		}
	}
}

// TestCanonicalJSONEscapesAndScalars covers the escape set and the concrete
// types the pipeline hands to the serializer directly.
func TestCanonicalJSONEscapesAndScalars(t *testing.T) {
	cases := []struct {
		name  string
		value any
		want  string
	}{
		{"null", nil, "null"},
		{"true", true, "true"},
		{"int64", int64(-7), "-7"},
		{"uint64", uint64(math.MaxUint64), "18446744073709551615"},
		{"two-char escapes", "\"\\\b\f\n\r\t", `"\"\\\b\f\n\r\t"`},
		{"other C0 controls escape as \\u00xx", "\x00\x01\x1f", `"\u0000\u0001\u001f"`},
		{"DEL is not escaped", "\x7f", "\"\x7f\""},
		{"non-ASCII stays literal", "é😀", `"é😀"`},
		{"empty object", map[string]any{}, "{}"},
		{"empty array", []any{}, "[]"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := CanonicalJSON(tc.value); got != tc.want {
				t.Errorf("got %s, want %s", got, tc.want)
			}
		})
	}
}

// TestCanonicalJSONNormalizesArbitraryValues covers the fallback: anything the
// serializer does not recognize is hardened first, which reduces it to one of
// the cases it does. Hardening there runs unlimited, so a long string is hashed
// whole rather than at whatever cap the logger happened to be configured with.
func TestCanonicalJSONNormalizesArbitraryValues(t *testing.T) {
	type row struct {
		Name string `json:"name"`
		Hits int    `json:"hits"`
	}
	long := make([]byte, _defaultMaxValueLength+10)
	for i := range long {
		long[i] = 'x'
	}

	cases := []struct {
		name  string
		value any
		want  string
	}{
		{"typed struct", row{Name: "a", Hits: 2}, `{"hits":2,"name":"a"}`},
		{"typed slice", []row{{Name: "a", Hits: 2}}, `[{"hits":2,"name":"a"}]`},
		{"plain int", 3, "3"},
		{"float32", float32(0.5), "0.5"},
		{"channel", make(chan int), `"***"`},
		{"long string is not truncated", string(long), `"` + string(long) + `"`},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := CanonicalJSON(tc.value); got != tc.want {
				t.Errorf("got %s, want %s", got, tc.want)
			}
		})
	}
}

// TestCanonicalJSONGuardsCycles pins the cycle guard: a composite reached again
// while still being serialized above this point emits null instead of recursing
// until stack exhaustion — the spelling receipts.py's _canonical fixes.
func TestCanonicalJSONGuardsCycles(t *testing.T) {
	direct := map[string]any{}
	direct["self"] = direct
	if got := CanonicalJSON(direct); got != `{"self":null}` {
		t.Errorf("map cycle: got %s, want {\"self\":null}", got)
	}

	sliceCycle := make([]any, 1)
	sliceCycle[0] = sliceCycle
	if got := CanonicalJSON(sliceCycle); got != `[null]` {
		t.Errorf("slice cycle: got %s, want [null]", got)
	}

	indirect := map[string]any{}
	indirect["list"] = []any{indirect}
	if got := CanonicalJSON(indirect); got != `{"list":[null]}` {
		t.Errorf("indirect cycle: got %s, want {\"list\":[null]}", got)
	}
}

// TestCanonicalJSONSerializesSharedSubtreesFully is the other half of the
// guard's contract: it is path-scoped, so an acyclic subtree reached twice
// serializes in full at every occurrence rather than degrading to null the
// second time. Python's receipts.py discards a composite from its seen set
// when the subtree completes; the digests must agree.
func TestCanonicalJSONSerializesSharedSubtreesFully(t *testing.T) {
	shared := map[string]any{"x": int64(1)}
	if got := CanonicalJSON(map[string]any{"a": shared, "b": shared}); got != `{"a":{"x":1},"b":{"x":1}}` {
		t.Errorf("shared map: got %s", got)
	}
	sharedList := []any{int64(2)}
	if got := CanonicalJSON(map[string]any{"a": sharedList, "b": sharedList}); got != `{"a":[2],"b":[2]}` {
		t.Errorf("shared slice: got %s", got)
	}
}

// TestCompareUTF16OrdersSurrogatesBelowBMPTail is the one place Go's natural
// string order disagrees with JCS: an astral character encodes to a surrogate
// pair starting at 0xD800, so UTF-16 sorts it below U+E000..U+FFFF while UTF-8
// bytes sort it above.
func TestCompareUTF16OrdersSurrogatesBelowBMPTail(t *testing.T) {
	astral, bmpTail := "😀", "￿"
	if compareUTF16(astral, bmpTail) >= 0 {
		t.Errorf("want %q < %q under UTF-16 order", astral, bmpTail)
	}
	got := CanonicalJSON(map[string]any{bmpTail: 1, astral: 2})
	want := `{"😀":2,"` + bmpTail + `":1}`
	if got != want {
		t.Errorf("got %s, want %s", got, want)
	}
}
