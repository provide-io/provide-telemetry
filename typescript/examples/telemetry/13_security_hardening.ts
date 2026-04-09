#!/usr/bin/env npx tsx
// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of Provide Telemetry.

/**
 * Security hardening features: input sanitization, secret detection, protocol guards.
 *
 * Demonstrates:
 *   1. Control character stripping from log attributes
 *   2. Attribute value truncation (configurable max length)
 *   3. Automatic secret detection and redaction (AWS keys, JWTs, GitHub tokens)
 *   4. Configurable nesting depth limits
 *   5. Environment variable configuration
 *
 * Run: npx tsx examples/telemetry/13_security_hardening.ts
 */

import {
  event,
  getLogger,
  registerPiiRule,
  sanitizePayload,
  setupTelemetry,
  shutdownTelemetry,
} from '../../src/index.js';

function main(): void {
  setupTelemetry({ serviceName: 'ts-security-demo', logLevel: 'info' });
  const log = getLogger('security-demo');

  console.log('=== Security Hardening Demo ===\n');

  // 1. Automatic secret detection in values (AWS keys, JWTs, GitHub tokens)
  console.log('1. Automatic secret detection:');
  const payload: Record<string, unknown> = {
    user: 'alice',
    debug_output: 'AKIAIOSFODNN7EXAMPLE', // pragma: allowlist secret
    auth_header: 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0', // pragma: allowlist secret
    notes: 'normal text is fine',
  };
  sanitizePayload(payload);
  for (const [k, v] of Object.entries(payload)) {
    console.log(`   ${k}: ${String(v)}`);
  }
  console.log();

  // 2. Value truncation via PII rule
  console.log('2. Value truncation via PII rule:');
  registerPiiRule({ path: 'big_field', mode: 'truncate', truncateTo: 20 });
  const truncPayload: Record<string, unknown> = {
    big_field: 'x'.repeat(200),
    other: 'untouched',
  };
  sanitizePayload(truncPayload);
  console.log(`   big_field truncated to: ${String(truncPayload['big_field'])}`);
  console.log(`   other: ${String(truncPayload['other'])}\n`);

  // 3. Default sensitive field redaction (password, token, api_key, etc.)
  console.log('3. Default sensitive field redaction:');
  log.info({ ...event('security', 'demo', 'pii'), password: 'hunter2', token: 'abc123', user: 'alice' }); // pragma: allowlist secret
  console.log('   (password and token fields redacted in log output)\n');

  // 4. Nesting depth limit
  console.log('4. Nesting depth limit (default 8):');
  const deep: Record<string, unknown> = { l1: { l2: { l3: { l4: { l5: { l6: { l7: { l8: { l9: 'deep' } } } } } } } } };
  sanitizePayload(deep, [], { maxDepth: 4 });
  console.log(`   Sanitized with maxDepth=4: ${JSON.stringify(deep)}\n`);

  // 5. Environment variable configuration
  console.log('5. Configurable via environment:');
  console.log('   PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH=2048  (OTLP export layer)');
  console.log('   PROVIDE_SECURITY_MAX_ATTR_COUNT=128          (OTLP export layer)');
  console.log('   PROVIDE_SECURITY_MAX_NESTING_DEPTH=4');

  shutdownTelemetry();
  console.log('\n=== Done ===');
}

main();
