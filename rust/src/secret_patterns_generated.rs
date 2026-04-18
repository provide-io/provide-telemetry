// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
// Auto-generated from spec/secret_patterns.yaml — do not edit.

/// Minimum string length for secret detection.
pub(crate) const MIN_SECRET_LENGTH: usize = 20;

/// (name, regex_pattern) pairs for built-in secret detection.
pub(crate) const PATTERNS: &[(&str, &str)] = &[
    ("aws_key", r#"(?:AKIA|ASIA)[A-Z0-9]{16}"#), // AWS access key ID
    ("jwt", r#"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"#), // JSON Web Token (header.payload)
    ("github_token", r#"gh[pos]_[A-Za-z0-9_]{36,}"#), // GitHub personal access token / OAuth / app token
    ("long_hex", r#"[0-9a-fA-F]{40,}"#),              // Long hex string (SHA hashes, API keys)
    ("long_base64", r#"[A-Za-z0-9+/]{40,}={0,2}"#),   // Long base64 string (encoded secrets, keys)
];
