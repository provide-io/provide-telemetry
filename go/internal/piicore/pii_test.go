// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package piicore

import (
	"crypto/sha256"
	"fmt"
	"testing"
)

// TestDefaultTruncateTo pins the limit a rule registered without one receives.
func TestDefaultTruncateTo(t *testing.T) {
	if DefaultTruncateTo != 8 {
		t.Fatalf("DefaultTruncateTo = %d, want 8", DefaultTruncateTo)
	}
}

// TestApplyModeTruncateLimits covers the three limit edges the contract
// names: zero keeps only the suffix, negative clamps to zero instead of
// panicking on the slice bound, and the count is in code points.
func TestApplyModeTruncateLimits(t *testing.T) {
	for _, tc := range []struct {
		value any
		limit int
		want  string
		note  string
	}{
		{"hello", 0, "...", "zero limit is exactly the suffix"},
		{"hello", -3, "...", "negative limit clamps to zero"},
		{"", -1, "", "empty input stays empty even at a negative limit"},
		{"😀😀😀😀😀", 3, "😀😀😀...", "limit counts code points, not bytes"},
		{"abc", 3, "abc", "at the limit is untouched"},
		{1234567890, 5, "12345...", "non-strings are rendered first"},
	} {
		got, drop := ApplyMode(tc.value, PIIModeTruncate, tc.limit)
		if drop || got != tc.want {
			t.Errorf("ApplyMode(%v, truncate, %d) = %v (drop=%v), want %q — %s", tc.value, tc.limit, got, drop, tc.want, tc.note)
		}
	}
}

// TestMergeSpansExtendsOverlap pins the one branch of mergeSpans the root and
// logger suites never reach: a later span that overlaps the previous one AND
// runs past its end must extend it, not be swallowed by it.
func TestMergeSpansExtendsOverlap(t *testing.T) {
	got := mergeSpans([][2]int{{5, 9}, {0, 6}, {20, 25}, {21, 23}})
	want := [][2]int{{0, 9}, {20, 25}}
	if len(got) != len(want) {
		t.Fatalf("mergeSpans = %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("span %d = %v, want %v", i, got[i], want[i])
		}
	}
}

func first12(text string) string {
	sum := sha256.Sum256([]byte(text))
	return fmt.Sprintf("%x", sum)[:12]
}

// TestApplyModeHashCanonicalizer pins the plumbing: a string is hashed as
// itself whether or not a canonicalizer is installed, a non-string goes
// through the installed canonicalizer, and without one the %v rendering is
// the fallback. The root package installs the RFC 8785 serializer at init;
// this package's own tests start with none.
func TestApplyModeHashCanonicalizer(t *testing.T) {
	t.Cleanup(func() { SetHashCanonicalizer(nil) })

	SetHashCanonicalizer(nil)
	if got, _ := ApplyMode("same-input", PIIModeHash, 0); got != first12("same-input") {
		t.Errorf("string without canonicalizer: got %v, want sha256 of the string", got)
	}
	if got, _ := ApplyMode(nil, PIIModeHash, 0); got != first12("<nil>") {
		t.Errorf("nil without canonicalizer: got %v, want the %%v fallback digest", got)
	}

	calls := 0
	SetHashCanonicalizer(func(v any) string {
		calls++
		return fmt.Sprintf("canonical(%v)", v)
	})
	if got, _ := ApplyMode("same-input", PIIModeHash, 0); got != first12("same-input") {
		t.Errorf("string with canonicalizer: got %v, want the string digested as itself", got)
	}
	if calls != 0 {
		t.Fatalf("canonicalizer must not run for strings, ran %d times", calls)
	}
	if got, _ := ApplyMode(true, PIIModeHash, 0); got != first12("canonical(true)") {
		t.Errorf("bool with canonicalizer: got %v, want the canonicalizer's rendering digested", got)
	}
	if calls != 1 {
		t.Fatalf("canonicalizer should run once for a non-string, ran %d times", calls)
	}

	SetHashCanonicalizer(nil)
	if got, _ := ApplyMode(true, PIIModeHash, 0); got != first12("true") {
		t.Errorf("bool after clearing: got %v, want the %%v fallback digest", got)
	}
}

// TestLooksLikePath pins both halves of the shape test: the segment-count
// floor at its boundary (two segments is not enough, three is), and the
// wordy-segment ratio at its boundary (exactly half is enough, and long
// wordless segments are base64 rather than directories).
//
// Ported from tests/hardening/test_secret_span_redaction.py, which had these
// from the start while the other runtimes went without. looksLikePath is
// unexported, so unlike the rest of piicore's coverage this cannot be driven
// from the root package.
func TestLooksLikePath(t *testing.T) {
	for _, tc := range []struct {
		span string
		want bool
		note string
	}{
		{"usr/local", false, "two segments is below the floor, however wordy"},
		{"ABCDEFGHIJ/1234567890/KLMNOPQRST", false, "long wordless segments are base64"},
		{"usr/local/lib", true, "three short lowercase words is the smallest path"},
		{"usr/local/AB12/CD34", true, "exactly half wordy is enough; the test is >=, not >"},
		{"usr/AB12/CD34", false, "one word in three is a minority; the ratio is a product, not a sum"},
	} {
		if got := looksLikePath(tc.span); got != tc.want {
			t.Errorf("looksLikePath(%q) = %v, want %v — %s", tc.span, got, tc.want, tc.note)
		}
	}
}
