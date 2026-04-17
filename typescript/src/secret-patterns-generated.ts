// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Auto-generated from spec/secret_patterns.yaml — do not edit.

export const MIN_SECRET_LENGTH = 20;

export const PATTERNS: ReadonlyArray<{ name: string; regex: RegExp }> = [
  { name: 'aws_key', regex: /(?:AKIA|ASIA)[A-Z0-9]{16}/ }, // AWS access key ID
  { name: 'jwt', regex: /eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/ }, // JSON Web Token (header.payload)
  { name: 'github_token', regex: /gh[pos]_[A-Za-z0-9_]{36,}/ }, // GitHub personal access token / OAuth / app token
  { name: 'long_hex', regex: /[0-9a-fA-F]{40,}/ }, // Long hex string (SHA hashes, API keys)
  { name: 'long_base64', regex: /[A-Za-z0-9+/]{40,}={0,2}/ }, // Long base64 string (encoded secrets, keys)
];
