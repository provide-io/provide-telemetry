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

	"github.com/provide-io/provide-telemetry/go/internal/levelcore"
)

// LevelTrace is a custom slog level below DEBUG for very verbose output.
const LevelTrace = slog.Level(-8)

// LevelCritical is a custom slog level above ERROR. slog's own ladder stops at
// ERROR, so without it CRITICAL had to fold onto ERROR and the ladder's top two
// levels were indistinguishable.
const LevelCritical = levelcore.SlogCritical

const (
	_cbBaseCooldown = 30 * time.Second
	_cbMaxCooldown  = 1024 * time.Second
)

// _maxExportAttempts caps the export retry loop (retries + the first try).
// Matches TypeScript's MAX_EXPORT_ATTEMPTS, so an exporter retries value the
// TS runtime rejects is rejected here too instead of booting one language and
// failing another on the same environment.
const _maxExportAttempts = 101
