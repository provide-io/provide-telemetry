// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import "testing"

// TestParseBaggageRejectsNonTokenKeys pins the injection boundary: a baggage key
// becomes a log-attribute key, and the console renderer emits keys bare, so a
// control character in a key from an untrusted header would forge a log record.
func TestParseBaggageRejectsNonTokenKeys(t *testing.T) {
	for _, raw := range []string{
		"ev\nil=x,ok=1",
		"ev\ril=x,ok=1",
		"bad key=x,ok=1",
		"ev\x00il=x,ok=1",
		"a\tb=x,ok=1",
	} {
		got := ParseBaggage(raw)
		if len(got) != 1 || got["ok"] != "1" {
			t.Fatalf("ParseBaggage(%q) = %v; want only the well-formed member", raw, got)
		}
	}
}

func TestParseBaggageStripsControlCharsFromValues(t *testing.T) {
	got := ParseBaggage("k=a\x00b\nc")
	if got["k"] != "abc" {
		t.Fatalf("ParseBaggage value = %q; want %q", got["k"], "abc")
	}
}

func TestParseBaggageKeepsLegitimateMembers(t *testing.T) {
	got := ParseBaggage("tenant=acme;role=admin,region=eu")
	if got["tenant"] != "acme" || got["region"] != "eu" || len(got) != 2 {
		t.Fatalf("ParseBaggage = %v; want tenant/region only", got)
	}
}
