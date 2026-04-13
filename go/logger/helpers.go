// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// helpers.go provides unexported wrappers over the shared internal packages so
// that white-box tests in this package can exercise the logic without directly
// importing the internal modules (keeping test code readable and concise).

package logger

import (
	"github.com/provide-io/provide-telemetry/go/internal/fingerprintcore"
)

// _extractBasename is an unexported wrapper over fingerprintcore.ExtractBasename
// used by white-box tests.
func _extractBasename(file string) string {
	return fingerprintcore.ExtractBasename(file)
}

// _extractFuncName is an unexported wrapper over fingerprintcore.ExtractFuncName
// used by white-box tests.
func _extractFuncName(fn string) string {
	return fingerprintcore.ExtractFuncName(fn)
}
