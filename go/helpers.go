// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// helpers.go provides unexported wrappers and aliases over the shared internal
// packages so that white-box tests in the telemetry package can exercise the
// logic without directly importing the internal modules.

package telemetry

import (
	"github.com/provide-io/provide-telemetry/go/internal/fingerprintcore"
	"github.com/provide-io/provide-telemetry/go/internal/piicore"
)

// _piiRedacted is the sentinel value returned when a value is redacted. // pragma: allowlist secret
const _piiRedacted = piicore.Redacted // pragma: allowlist secret

// _secretPatterns exposes the built-in secret patterns for white-box tests. // pragma: allowlist secret
var _secretPatterns = piicore.BuiltinSecretPatterns // pragma: allowlist secret

// _isDefaultSensitiveKey returns true if key matches a default sensitive key name.
func _isDefaultSensitiveKey(key string) bool {
	return piicore.IsDefaultSensitiveKey(key)
}

// _extractBasename is an unexported wrapper over fingerprintcore.ExtractBasename.
func _extractBasename(file string) string {
	return fingerprintcore.ExtractBasename(file)
}

// _extractFuncName is an unexported wrapper over fingerprintcore.ExtractFuncName.
func _extractFuncName(fn string) string {
	return fingerprintcore.ExtractFuncName(fn)
}

// _shortHash12 is an unexported wrapper over fingerprintcore.ShortHash12.
func _shortHash12(input string) string {
	return fingerprintcore.ShortHash12(input)
}
