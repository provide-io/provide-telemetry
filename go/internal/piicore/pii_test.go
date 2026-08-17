// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package piicore

import "testing"

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
