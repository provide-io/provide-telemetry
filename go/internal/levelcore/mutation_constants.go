// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// Go coverage starts after package initialization, so Gremlins cannot
// attribute mutations in constant declarations to tests. CI excludes this
// declaration-only file; parity_log_levels_test.go asserts the exact values
// through ToSlog and FromSlog.

package levelcore

import "log/slog"

// slog levels for the two rungs slog itself does not define. slog's own ladder
// is Debug -4, Info 0, Warn 4, Error 8, so these continue it at the same pitch.
const (
	SlogTrace    = slog.Level(-8)
	SlogCritical = slog.Level(12)
)
