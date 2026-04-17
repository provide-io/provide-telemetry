// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// Code generated from spec/secret_patterns.yaml — DO NOT EDIT.

package piicore

import "regexp"

// MinSecretLength is the minimum string length for secret detection.
const MinSecretLength = 20 // pragma: allowlist secret

// generatedSecretPatterns are compiled from spec/secret_patterns.yaml. // pragma: allowlist secret
var generatedSecretPatterns = []*regexp.Regexp{ // pragma: allowlist secret
	regexp.MustCompile(`(?:AKIA|ASIA)[A-Z0-9]{16}`), // AWS access key ID
	regexp.MustCompile(`eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}`), // JSON Web Token (header.payload)
	regexp.MustCompile(`gh[pos]_[A-Za-z0-9_]{36,}`), // GitHub personal access token / OAuth / app token
	regexp.MustCompile(`[0-9a-fA-F]{40,}`), // Long hex string (SHA hashes, API keys)
	regexp.MustCompile(`[A-Za-z0-9+/]{40,}={0,2}`), // Long base64 string (encoded secrets, keys)
}
