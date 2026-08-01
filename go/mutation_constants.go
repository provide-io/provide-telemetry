// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// Immutable package constants live together because Go coverage starts after
// package initialization. Gremlins therefore cannot attribute mutations in
// constant declarations to tests. CI excludes only this declaration-only file;
// exact-value tests below the public behavior still ratchet every value.

package telemetry

import (
	"log/slog"
	"time"
)

// LevelTrace is a custom slog level below DEBUG for very verbose output.
const LevelTrace = slog.Level(-8)

const (
	_cbBaseCooldown = 30 * time.Second
	_cbMaxCooldown  = 1024 * time.Second
)
