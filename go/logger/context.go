// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package logger

import "context"

// contextKey is an unexported type for context keys in this package.
// Using a named struct prevents collisions with keys from other packages.
type contextKey struct{ name string }

var (
	_contextFieldsKey = contextKey{"fields"}
	// TraceIDKey and SpanIDKey are the context keys used by SetTraceContext /
	// GetTraceContext.  The tracer sub-package imports this package and writes
	// to the same keys so that the logger sees trace IDs without an OTel dep.
	TraceIDKey  = contextKey{"trace.id"} //nolint:gochecknoglobals
	SpanIDKey   = contextKey{"span.id"}  //nolint:gochecknoglobals
	_sessionKey = contextKey{"session"}  //nolint:gochecknoglobals
)

// BindContext adds key-value fields to the context, merging with any existing fields.
// Returns a new context — does not mutate the parent.
func BindContext(ctx context.Context, fields map[string]any) context.Context {
	merged := copyFields(GetBoundFields(ctx))
	for k, v := range fields {
		merged[k] = v
	}
	return context.WithValue(ctx, _contextFieldsKey, merged)
}

// UnbindContext removes the specified keys from the context's bound fields.
// Returns a new context.
func UnbindContext(ctx context.Context, keys ...string) context.Context {
	existing := GetBoundFields(ctx)
	result := make(map[string]any, len(existing))
	remove := make(map[string]struct{}, len(keys))
	for _, k := range keys {
		remove[k] = struct{}{}
	}
	for k, v := range existing {
		if _, skip := remove[k]; !skip {
			result[k] = v
		}
	}
	return context.WithValue(ctx, _contextFieldsKey, result)
}

// ClearContext removes all bound fields from the context.
// Returns a new context.
func ClearContext(ctx context.Context) context.Context {
	return context.WithValue(ctx, _contextFieldsKey, map[string]any{})
}

// GetBoundFields returns a copy of all fields bound to the context.
// Returns an empty map if nothing is bound.
func GetBoundFields(ctx context.Context) map[string]any {
	v := ctx.Value(_contextFieldsKey)
	if v == nil {
		return map[string]any{}
	}
	fields, ok := v.(map[string]any)
	if !ok {
		return map[string]any{}
	}
	return copyFields(fields)
}

// SetTraceContext returns a new context with the given trace/span IDs bound.
// The tracer sub-package delegates here so both packages share the same context keys.
func SetTraceContext(ctx context.Context, traceID, spanID string) context.Context {
	ctx = context.WithValue(ctx, TraceIDKey, traceID)
	ctx = context.WithValue(ctx, SpanIDKey, spanID)
	return ctx
}

// GetTraceContext returns trace/span IDs stored by SetTraceContext.
// Returns empty strings if not set.
// Note: this method reads context keys only. To also check live OTel spans use
// the tracer sub-package's GetTraceContext.
func GetTraceContext(ctx context.Context) (traceID, spanID string) {
	if v, ok := ctx.Value(TraceIDKey).(string); ok {
		traceID = v
	}
	if v, ok := ctx.Value(SpanIDKey).(string); ok {
		spanID = v
	}
	return traceID, spanID
}

// BindSessionContext stores a session ID in the context.
func BindSessionContext(ctx context.Context, sessionID string) context.Context {
	return context.WithValue(ctx, _sessionKey, sessionID)
}

// GetSessionID retrieves the session ID from the context.
func GetSessionID(ctx context.Context) (string, bool) {
	v := ctx.Value(_sessionKey)
	if v == nil {
		return "", false
	}
	s, ok := v.(string)
	if !ok || s == "" {
		return "", false
	}
	return s, true
}

// ClearSessionContext removes the session ID from the context.
func ClearSessionContext(ctx context.Context) context.Context {
	return context.WithValue(ctx, _sessionKey, "")
}

// copyFields returns a shallow copy of the given map.
func copyFields(src map[string]any) map[string]any {
	dst := make(map[string]any, len(src))
	for k, v := range src {
		dst[k] = v
	}
	return dst
}
