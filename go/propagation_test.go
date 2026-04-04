// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"net/http"
	"strings"
	"testing"
)

const (
	_validTraceID = "4bf92f3577b34da6a3ce929d0e0e4736" // pragma: allowlist secret
	_validSpanID  = "00f067aa0ba902b7"
	_validFlags   = "01"
)

func validTraceparent() string {
	return "00-" + _validTraceID + "-" + _validSpanID + "-" + _validFlags
}

func TestExtractW3CContext_ValidTraceparent(t *testing.T) {
	headers := http.Header{}
	headers.Set("Traceparent", validTraceparent())

	pc := ExtractW3CContext(headers)

	if pc.TraceID != _validTraceID {
		t.Errorf("TraceID: want %q, got %q", _validTraceID, pc.TraceID)
	}
	if pc.SpanID != _validSpanID {
		t.Errorf("SpanID: want %q, got %q", _validSpanID, pc.SpanID)
	}
	if pc.Traceparent != validTraceparent() {
		t.Errorf("Traceparent: want %q, got %q", validTraceparent(), pc.Traceparent)
	}
}

func TestExtractW3CContext_MissingTraceparent(t *testing.T) {
	headers := http.Header{}

	pc := ExtractW3CContext(headers)

	if pc.TraceID != "" {
		t.Errorf("TraceID: want empty, got %q", pc.TraceID)
	}
	if pc.SpanID != "" {
		t.Errorf("SpanID: want empty, got %q", pc.SpanID)
	}
}

func TestExtractW3CContext_MalformedTraceparent_WrongFieldCount(t *testing.T) {
	headers := http.Header{}
	headers.Set("Traceparent", "00-"+_validTraceID+"-"+_validSpanID) // missing flags

	pc := ExtractW3CContext(headers)

	if pc.TraceID != "" {
		t.Errorf("TraceID: want empty, got %q", pc.TraceID)
	}
	if pc.SpanID != "" {
		t.Errorf("SpanID: want empty, got %q", pc.SpanID)
	}
}

func TestExtractW3CContext_WrongVersion(t *testing.T) {
	headers := http.Header{}
	headers.Set("Traceparent", "01-"+_validTraceID+"-"+_validSpanID+"-"+_validFlags)

	pc := ExtractW3CContext(headers)

	if pc.TraceID != "" {
		t.Errorf("TraceID: want empty, got %q", pc.TraceID)
	}
	if pc.SpanID != "" {
		t.Errorf("SpanID: want empty, got %q", pc.SpanID)
	}
}

func TestExtractW3CContext_InvalidTraceID_WrongLength(t *testing.T) {
	headers := http.Header{}
	headers.Set("Traceparent", "00-shortid-"+_validSpanID+"-"+_validFlags)

	pc := ExtractW3CContext(headers)

	if pc.TraceID != "" {
		t.Errorf("TraceID: want empty, got %q", pc.TraceID)
	}
}

func TestExtractW3CContext_AllZeroTraceID(t *testing.T) {
	headers := http.Header{}
	zeroTrace := strings.Repeat("0", 32)
	headers.Set("Traceparent", "00-"+zeroTrace+"-"+_validSpanID+"-"+_validFlags)

	pc := ExtractW3CContext(headers)

	if pc.TraceID != "" {
		t.Errorf("TraceID: want empty for all-zero, got %q", pc.TraceID)
	}
}

func TestExtractW3CContext_InvalidSpanID_WrongLength(t *testing.T) {
	headers := http.Header{}
	headers.Set("Traceparent", "00-"+_validTraceID+"-shortspan-"+_validFlags)

	pc := ExtractW3CContext(headers)

	if pc.SpanID != "" {
		t.Errorf("SpanID: want empty, got %q", pc.SpanID)
	}
}

func TestExtractW3CContext_AllZeroSpanID(t *testing.T) {
	headers := http.Header{}
	zeroSpan := strings.Repeat("0", 16)
	headers.Set("Traceparent", "00-"+_validTraceID+"-"+zeroSpan+"-"+_validFlags)

	pc := ExtractW3CContext(headers)

	if pc.SpanID != "" {
		t.Errorf("SpanID: want empty for all-zero, got %q", pc.SpanID)
	}
}

func TestExtractW3CContext_TraceparentTooLarge(t *testing.T) {
	headers := http.Header{}
	// Build a traceparent that exceeds 512 bytes.
	long := strings.Repeat("x", 512) + validTraceparent()
	headers.Set("Traceparent", long)

	pc := ExtractW3CContext(headers)

	if pc.Traceparent != "" {
		t.Errorf("Traceparent should be discarded when oversized, got %q", pc.Traceparent)
	}
	if pc.TraceID != "" {
		t.Errorf("TraceID should be empty after discarded traceparent, got %q", pc.TraceID)
	}
	if pc.SpanID != "" {
		t.Errorf("SpanID should be empty after discarded traceparent, got %q", pc.SpanID)
	}
}

func TestExtractW3CContext_TracestateTooLarge(t *testing.T) {
	headers := http.Header{}
	headers.Set("Traceparent", validTraceparent())
	// Build a tracestate longer than 512 bytes
	long := strings.Repeat("k=v,", 200) // well over 512 bytes
	headers.Set("Tracestate", long)

	pc := ExtractW3CContext(headers)

	if pc.Tracestate != "" {
		t.Errorf("Tracestate should be discarded when oversized, got len %d", len(pc.Tracestate))
	}
}

func TestExtractW3CContext_TracestateMoreThan32Pairs(t *testing.T) {
	headers := http.Header{}
	headers.Set("Traceparent", validTraceparent())

	// Build exactly 40 pairs, each short enough that the total is within 512 bytes
	pairs := make([]string, 40)
	for i := range pairs {
		pairs[i] = "k=v"
	}
	headers.Set("Tracestate", strings.Join(pairs, ","))

	pc := ExtractW3CContext(headers)

	if pc.Tracestate != "" {
		t.Errorf("Tracestate should be discarded when exceeding %d pairs, got %q", _maxTracestatePairs, pc.Tracestate)
	}
}

func TestExtractW3CContext_BaggageTooLarge(t *testing.T) {
	headers := http.Header{}
	headers.Set("Traceparent", validTraceparent())
	// Build baggage longer than 8192 bytes
	long := strings.Repeat("k=v,", 3000) // ~12000 bytes
	headers.Set("Baggage", long)

	pc := ExtractW3CContext(headers)

	if pc.Baggage != "" {
		t.Errorf("Baggage should be discarded when oversized, got len %d", len(pc.Baggage))
	}
}

func TestBindAndGetPropagationContext_RoundTrip(t *testing.T) {
	headers := http.Header{}
	headers.Set("Traceparent", validTraceparent())
	headers.Set("Tracestate", "vendor1=abc")
	headers.Set("Baggage", "userId=123")

	pc := ExtractW3CContext(headers)

	ctx := BindPropagationContext(context.Background(), pc)
	got := GetPropagationContext(ctx)

	if got.TraceID != pc.TraceID {
		t.Errorf("TraceID: want %q, got %q", pc.TraceID, got.TraceID)
	}
	if got.SpanID != pc.SpanID {
		t.Errorf("SpanID: want %q, got %q", pc.SpanID, got.SpanID)
	}
	if got.Traceparent != pc.Traceparent {
		t.Errorf("Traceparent: want %q, got %q", pc.Traceparent, got.Traceparent)
	}
	if got.Tracestate != pc.Tracestate {
		t.Errorf("Tracestate: want %q, got %q", pc.Tracestate, got.Tracestate)
	}
	if got.Baggage != pc.Baggage {
		t.Errorf("Baggage: want %q, got %q", pc.Baggage, got.Baggage)
	}
}

func TestGetPropagationContext_EmptyContext(t *testing.T) {
	pc := GetPropagationContext(context.Background())

	if pc.TraceID != "" || pc.SpanID != "" || pc.Traceparent != "" || pc.Tracestate != "" || pc.Baggage != "" {
		t.Errorf("expected zero PropagationContext from empty context, got %+v", pc)
	}
}

func TestExtractW3CContext_InvalidTraceID_UppercaseHex(t *testing.T) {
	headers := http.Header{}
	// TraceID with uppercase hex chars — should be invalid (spec requires lowercase)
	upperTrace := "4BF92F3577B34DA6A3CE929D0E0E4736" // pragma: allowlist secret
	headers.Set("Traceparent", "00-"+upperTrace+"-"+_validSpanID+"-"+_validFlags)

	pc := ExtractW3CContext(headers)

	if pc.TraceID != "" {
		t.Errorf("TraceID: want empty for uppercase hex, got %q", pc.TraceID)
	}
}

func TestExtractW3CContext_InvalidSpanID_UppercaseHex(t *testing.T) {
	headers := http.Header{}
	// SpanID with uppercase hex chars — should be invalid
	upperSpan := "00F067AA0BA902B7"
	headers.Set("Traceparent", "00-"+_validTraceID+"-"+upperSpan+"-"+_validFlags)

	pc := ExtractW3CContext(headers)

	if pc.SpanID != "" {
		t.Errorf("SpanID: want empty for uppercase hex, got %q", pc.SpanID)
	}
}

// _guardSize: string of maxBytes-1 must NOT be truncated. Under ARITHMETIC mutation
// (maxBytes+1 → maxBytes-1), this string would match (len >= maxBytes-1) and try
// to truncate to maxBytes bytes (which exceeds len), causing a panic.
func TestGuardSize_OneBelowMax_NotTruncated(t *testing.T) {
	s := strings.Repeat("x", _maxTraceparentBytes-1)
	got := _guardSize(s, _maxTraceparentBytes)
	if got != s {
		t.Errorf("string %d bytes shorter than max should not be truncated", _maxTraceparentBytes-1)
	}
}

// _guardSize: string of maxBytes+1 MUST be discarded.
func TestGuardSize_OneOverMax_Discarded(t *testing.T) {
	s := strings.Repeat("x", _maxTraceparentBytes+1)
	got := _guardSize(s, _maxTraceparentBytes)
	if got != "" {
		t.Errorf("string 1 over max should be discarded, got len %d", len(got))
	}
}

// _guardTracestateSize: exactly 31 pairs must NOT be trimmed. Under ARITHMETIC mutation
// (_maxTracestatePairs+1 → _maxTracestatePairs-1), 31 pairs match (>= 31) and would try
// pairs[:32] on 31-element slice → panic.
func TestGuardTracestateSize_31Pairs_NotTrimmed(t *testing.T) {
	pairs := make([]string, _maxTracestatePairs-1)
	for i := range pairs {
		pairs[i] = "k=v"
	}
	ts := strings.Join(pairs, ",")
	got := _guardTracestateSize(ts)
	gotPairs := strings.Split(got, ",")
	if len(gotPairs) != _maxTracestatePairs-1 {
		t.Errorf("%d pairs should not be trimmed, got %d", _maxTracestatePairs-1, len(gotPairs))
	}
}

// _guardSize boundary: string of exactly maxBytes must NOT be truncated
func TestGuardSize_AtExactBoundary_NotTruncated(t *testing.T) {
	exact := strings.Repeat("x", _maxTraceparentBytes) // len == 512
	got := _guardSize(exact, _maxTraceparentBytes)
	if len(got) != _maxTraceparentBytes {
		t.Errorf("string of exactly %d bytes should not be truncated, got len %d", _maxTraceparentBytes, len(got))
	}
}

// _guardTracestateSize boundary: exactly 33 pairs MUST be discarded.
// With `>= _maxTracestatePairs+1`, mutation `> _maxTracestatePairs+1` skips 33.
func TestGuardTracestateSize_33Pairs_Discarded(t *testing.T) {
	pairs := make([]string, _maxTracestatePairs+1)
	for i := range pairs {
		pairs[i] = "k=v"
	}
	ts := strings.Join(pairs, ",")
	got := _guardTracestateSize(ts)
	if got != "" {
		t.Errorf("33 pairs should be discarded, got %q", got)
	}
}

// _guardTracestateSize boundary: exactly 32 pairs must NOT be trimmed
func TestGuardTracestateSize_Exactly32Pairs_NotTrimmed(t *testing.T) {
	pairs := make([]string, _maxTracestatePairs)
	for i := range pairs {
		pairs[i] = "k=v"
	}
	ts := strings.Join(pairs, ",")
	got := _guardTracestateSize(ts)
	gotPairs := strings.Split(got, ",")
	if len(gotPairs) != _maxTracestatePairs {
		t.Errorf("exactly %d pairs should not be trimmed, got %d", _maxTracestatePairs, len(gotPairs))
	}
}

func TestExtractW3CContext_AllFieldsPresent(t *testing.T) {
	headers := http.Header{}
	headers.Set("Traceparent", validTraceparent())
	headers.Set("Tracestate", "vendor=opaque")
	headers.Set("Baggage", "sessionId=abc123")

	pc := ExtractW3CContext(headers)

	if pc.Tracestate != "vendor=opaque" {
		t.Errorf("Tracestate: want %q, got %q", "vendor=opaque", pc.Tracestate)
	}
	if pc.Baggage != "sessionId=abc123" {
		t.Errorf("Baggage: want %q, got %q", "sessionId=abc123", pc.Baggage)
	}
}
