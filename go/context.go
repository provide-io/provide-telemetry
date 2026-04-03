// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import "context"

// contextKey is an unexported type for context keys in this package.
// Using a struct prevents collisions with keys from other packages.
type contextKey struct{ name string }

var _contextFieldsKey = contextKey{"fields"}

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

// copyFields returns a shallow copy of the given map.
func copyFields(src map[string]any) map[string]any {
	dst := make(map[string]any, len(src))
	for k, v := range src {
		dst[k] = v
	}
	return dst
}
