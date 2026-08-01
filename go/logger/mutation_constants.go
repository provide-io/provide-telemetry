// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// Go coverage starts after package initialization, so Gremlins cannot
// attribute mutations in constant declarations to tests. CI excludes this
// declaration-only file; mutation_boundaries_test.go asserts the exact value.

package logger

import "log/slog"

// LevelTrace is a custom slog level below DEBUG for very verbose output.
const LevelTrace = slog.Level(-8)
