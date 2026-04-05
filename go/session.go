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
// Returns ("", false) when no session is set or the stored value is not a string.
// Returns (id, true) when a valid session ID is present.
func GetSessionID(ctx context.Context) (string, bool) {
	v := ctx.Value(_sessionKey)
	if v == nil {
		return "", false
	}
	s, ok := v.(string)
	if !ok {
		return "", false
	}
	if s == "" {
		return "", false
	}
	return s, true
}

// ClearSessionContext removes the session ID from the context.
// Returns a new context.
func ClearSessionContext(ctx context.Context) context.Context {
	return context.WithValue(ctx, _sessionKey, "")
}
