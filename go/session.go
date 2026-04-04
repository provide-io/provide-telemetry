// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import "context"

var _sessionKey = contextKey{"session"}

// BindSessionContext stores a session ID in the context.
// Returns a new context — does not mutate the parent.
func BindSessionContext(ctx context.Context, sessionID string) context.Context {
	return context.WithValue(ctx, _sessionKey, sessionID)
}

// GetSessionID retrieves the session ID from the context.
// Returns empty string if not set.
func GetSessionID(ctx context.Context) string {
	v := ctx.Value(_sessionKey)
	if v == nil {
		return ""
	}
	s, ok := v.(string)
	if !ok {
		return ""
	}
	return s
}

// ClearSessionContext removes the session ID from the context.
// Returns a new context.
func ClearSessionContext(ctx context.Context) context.Context {
	return context.WithValue(ctx, _sessionKey, "")
}
