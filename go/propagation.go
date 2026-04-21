// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"net/http"
	"strings"
)

// PropagationContext holds W3C trace context headers extracted from an HTTP request.
type PropagationContext struct {
	Traceparent string
	Tracestate  string
	Baggage     string
	TraceID     string
	SpanID      string
}

const (
	_maxTraceparentBytes = 512
	_maxTracestateBytes  = 512
	_maxBaggageBytes     = 8192
	_maxTracestatePairs  = 32
)

var _propagationKey = contextKey{"propagation"}

// ExtractW3CContext extracts W3C trace context from HTTP headers.
// Applies size guards and parses the traceparent header.
func ExtractW3CContext(headers http.Header) PropagationContext {
	tp := _guardSize(headers.Get("Traceparent"), _maxTraceparentBytes)
	ts := _guardTracestateSize(headers.Get("Tracestate"))
	bg := _guardSize(headers.Get("Baggage"), _maxBaggageBytes)

	traceID, spanID := _parseTraceparent(tp)

	return PropagationContext{
		Traceparent: tp,
		Tracestate:  ts,
		Baggage:     bg,
		TraceID:     traceID,
		SpanID:      spanID,
	}
}

// BindPropagationContext returns a new context with the PropagationContext bound.
// If pc.Baggage is non-empty, the raw baggage string is added as "baggage" and
// each parsed key-value pair is added as "baggage.<key>" in the context fields.
func BindPropagationContext(ctx context.Context, pc PropagationContext) context.Context {
	ctx = context.WithValue(ctx, _propagationKey, pc)
	// Bridge propagated trace/span IDs into the trace context so logs
	// emitted before a child span is created still carry upstream IDs.
	// Matches Python (propagation.py:147) and Rust (propagation.rs:147).
	if pc.TraceID != "" || pc.SpanID != "" {
		ctx = SetTraceContext(ctx, pc.TraceID, pc.SpanID)
	}
	if pc.Baggage != "" {
		fields := map[string]any{"baggage": pc.Baggage}
		for k, v := range ParseBaggage(pc.Baggage) {
			fields["baggage."+k] = v
		}
		ctx = BindContext(ctx, fields)
	}
	return ctx
}

// ParseBaggage parses a W3C baggage header into key-value pairs.
// Properties after ';' are stripped. Empty keys are skipped.
func ParseBaggage(raw string) map[string]string {
	result := map[string]string{}
	for _, member := range strings.Split(raw, ",") {
		kv := strings.SplitN(member, ";", 2)[0] // strip properties
		eqIdx := strings.Index(kv, "=")
		if eqIdx < 1 { // no '=' or empty key
			continue
		}
		key := strings.TrimSpace(kv[:eqIdx])
		if key != "" {
			result[key] = strings.TrimSpace(kv[eqIdx+1:])
		}
	}
	return result
}

// GetPropagationContext returns the PropagationContext from ctx, or zero value.
func GetPropagationContext(ctx context.Context) PropagationContext {
	v := ctx.Value(_propagationKey)
	if v == nil {
		return PropagationContext{}
	}
	return v.(PropagationContext) //nolint:forcetypeassert
}

// _guardSize discards s entirely if it exceeds maxBytes.
func _guardSize(s string, maxBytes int) string {
	if len(s) >= maxBytes+1 {
		return ""
	}
	return s
}

// _guardTracestateSize discards tracestate if it exceeds _maxTracestateBytes bytes
// or contains more than _maxTracestatePairs comma-separated pairs.
func _guardTracestateSize(s string) string {
	s = _guardSize(s, _maxTracestateBytes)
	if s == "" {
		return s
	}
	pairs := strings.Split(s, ",")
	if len(pairs) >= _maxTracestatePairs+1 {
		return ""
	}
	return s
}

// _parseTraceparent parses a traceparent header value and returns traceID and spanID.
// Returns empty strings if the header is invalid.
// Accepts any version except "ff"; normalizes traceID and spanID to lowercase.
func _parseTraceparent(tp string) (traceID, spanID string) {
	if tp == "" {
		return "", ""
	}
	parts := strings.Split(tp, "-")
	if len(parts) != 4 {
		return "", ""
	}
	version := parts[0]
	if len(version) != 2 || strings.ToLower(version) == "ff" {
		return "", ""
	}
	tid := strings.ToLower(parts[1])
	sid := strings.ToLower(parts[2])
	if !_isValidTraceID(tid) {
		return "", ""
	}
	if !_isValidSpanID(sid) {
		return "", ""
	}
	return tid, sid
}

// _isValidTraceID returns true if s is exactly 32 hex chars and not all zeros.
func _isValidTraceID(s string) bool {
	if len(s) != 32 {
		return false
	}
	return _isHex(s) && s != "00000000000000000000000000000000"
}

// _isValidSpanID returns true if s is exactly 16 hex chars and not all zeros.
func _isValidSpanID(s string) bool {
	if len(s) != 16 {
		return false
	}
	return _isHex(s) && s != "0000000000000000"
}

// _isHex returns true if every character in s is a lowercase hex digit.
// Callers must normalize to lowercase before calling (e.g. strings.ToLower).
func _isHex(s string) bool {
	for _, c := range s {
		if (c < '0' || c > '9') && (c < 'a' || c > 'f') {
			return false
		}
	}
	return true
}
