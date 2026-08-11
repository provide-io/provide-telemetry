// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// parity_propagation_test.go validates Go behavioral parity for W3C propagation
// guards against spec/behavioral_fixtures.yaml: traceparent size limits (at/over
// 512 bytes), tracestate pair count limits (32 accepted, 33 discarded), and
// baggage size limits (8192 accepted, 8193 discarded).
// The _validTraceID, _validSpanID, and validTraceparent() helpers are defined
// in propagation_test.go (same package).

package telemetry

import (
	"net/http"
	"strings"
	"testing"
)

// ── Propagation Guards ───────────────────────────────────────────────────────

func TestParity_Propagation_TraceparentAtLimit_Accepted(t *testing.T) {
	headers := http.Header{}
	tp := "00-" + _validTraceID + "-" + _validSpanID + "-01"
	headers.Set("Traceparent", tp)
	pc := ExtractW3CContext(headers)
	if pc.Traceparent == "" {
		t.Error("traceparent within 512 bytes should be accepted")
	}
}

func TestParity_Propagation_TraceparentOverLimit_Handled(t *testing.T) {
	headers := http.Header{}
	long := strings.Repeat("x", 513)
	headers.Set("Traceparent", long)
	pc := ExtractW3CContext(headers)
	if pc.Traceparent != "" {
		t.Errorf("oversized traceparent should be discarded, got %d bytes", len(pc.Traceparent))
	}
}

func TestParity_Propagation_Tracestate32Pairs_Accepted(t *testing.T) {
	headers := http.Header{}
	headers.Set("Traceparent", validTraceparent())
	pairs := make([]string, 32)
	for i := range pairs {
		pairs[i] = "k=v"
	}
	headers.Set("Tracestate", strings.Join(pairs, ","))
	pc := ExtractW3CContext(headers)
	if pc.Tracestate == "" {
		t.Error("32 tracestate pairs should be accepted")
	}
}

func TestParity_Propagation_Tracestate33Pairs_Handled(t *testing.T) {
	headers := http.Header{}
	headers.Set("Traceparent", validTraceparent())
	pairs := make([]string, 33)
	for i := range pairs {
		pairs[i] = "k=v"
	}
	headers.Set("Tracestate", strings.Join(pairs, ","))
	pc := ExtractW3CContext(headers)
	if pc.Tracestate != "" {
		t.Errorf("33 tracestate pairs should be discarded, got %q", pc.Tracestate)
	}
}

// ── Propagation Guards — baggage limits ──────────────────────────────────────

func TestParity_Propagation_BaggageAtLimit_Accepted(t *testing.T) {
	headers := http.Header{}
	headers.Set("Baggage", strings.Repeat("x", 8192))
	pc := ExtractW3CContext(headers)
	if pc.Baggage == "" {
		t.Error("expected baggage at limit (8192) to be accepted")
	}
}

func TestParity_Propagation_BaggageOverLimit_Discarded(t *testing.T) {
	headers := http.Header{}
	headers.Set("Baggage", strings.Repeat("x", 8193))
	pc := ExtractW3CContext(headers)
	if pc.Baggage != "" {
		t.Error("expected baggage over limit (8193) to be discarded")
	}
}

// ── Propagation Oversized Traceparent ───────────────────────────────────────
// Parity category: propagation_oversized_traceparent — a traceparent with
// content beyond the canonical 4-part W3C form (e.g. an extra hyphen-
// separated segment) must be rejected. Returned context must have neither
// a TraceID nor a SpanID — no partial acceptance, no truncation. The raw
// Traceparent field is also cleared on parse failure so Python, TypeScript,
// Go, and Rust all agree: a malformed traceparent produces an empty context.

func TestParity_Propagation_OversizedTraceparent_Rejected(t *testing.T) {
	headers := http.Header{}
	tp := "00-" + _validTraceID + "-" + _validSpanID + "-01-extra"
	headers.Set("Traceparent", tp)
	pc := ExtractW3CContext(headers)
	if pc.TraceID != "" {
		t.Errorf("malformed traceparent must yield empty TraceID, got %q", pc.TraceID)
	}
	if pc.SpanID != "" {
		t.Errorf("malformed traceparent must yield empty SpanID, got %q", pc.SpanID)
	}
	if pc.Traceparent != "" {
		t.Errorf("malformed traceparent must also clear Traceparent for cross-language parity, got %q", pc.Traceparent)
	}
}

// ── Propagation Tracestate Grammar ───────────────────────────────────────────
// Parity category: propagation_tracestate_grammar — a tracestate that passes
// the length and pair-count guards must also fit the W3C list-member grammar;
// one bad member discards the whole header.

func TestParity_Propagation_TracestateGrammar(t *testing.T) {
	cases := []struct {
		name       string
		tracestate string
		kept       bool
	}{
		{"crlf member discarded", "vendor=value\r\nx-injected: yes", false},
		{"ansi escape discarded", "vendor=va\x1b[31mlue", false},
		{"missing equals discarded", "vendorvalue", false},
		{"one invalid member discards all", "vendor=ok,bad\r\nmember=x", false},
		{"uppercase key discarded", "Vendor=x", false},
		{"comma only discarded", ",", false},
		{"257-char key discarded", strings.Repeat("a", 257) + "=x", false},
		{"value with equals discarded", "vendor=a=b", false},
		{"key specials kept", "k_e-y*a/b@c=1", true},
		{"digit-first key kept", "0key=x", true},
		{"valid multi-member kept", "congo=t61rcWkgMzE,rojo=00f067aa0ba902b7", true},
		{"ows after comma kept", "congo=t61, rojo=00f", true},
		{"tab ows kept", "congo=t61,\trojo=00f", true},
		{"multi-tenant key kept", "az3@rojo=00f067aa", true},
		{"empty value kept", "vendor=", true},
		{"256-char key kept", strings.Repeat("a", 256) + "=x", true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			headers := http.Header{}
			headers.Set("Traceparent", validTraceparent())
			headers.Set("Tracestate", tc.tracestate)
			pc := ExtractW3CContext(headers)
			if tc.kept && pc.Tracestate != tc.tracestate {
				t.Errorf("expected tracestate kept, got %q", pc.Tracestate)
			}
			if !tc.kept && pc.Tracestate != "" {
				t.Errorf("expected tracestate discarded, got %q", pc.Tracestate)
			}
		})
	}
}
