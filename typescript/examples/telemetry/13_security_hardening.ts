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
  sanitizePayload,
  setupTelemetry,
  shutdownTelemetry,
} from '../../src/index.js';

function main(): void {
  setupTelemetry({ serviceName: 'ts-security-demo', logLevel: 'info' });
  const log = getLogger('security-demo');

  console.log('=== Security Hardening Demo ===\n');

  // 1. Control characters stripped from log output
  console.log('1. Control character stripping:');
  log.info({ ...event('security', 'demo', 'control_chars'), data: 'clean\x00hidden\x01bytes\x7fremoved' });
  console.log('   (null bytes and control chars silently removed)\n');

  // 2. Oversized values truncated
  console.log('2. Value truncation (default 1024 chars):');
  const hugeValue = 'x'.repeat(2000);
  log.info({ ...event('security', 'demo', 'truncation'), big_field: hugeValue });
  console.log(`   Input: ${hugeValue.length} chars → truncated to 1024\n`);

  // 3. Secret detection in values
  console.log('3. Automatic secret detection:');
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

  // 4. Nesting depth limit
  console.log('4. Nesting depth limit (default 8):');
  const deep: Record<string, unknown> = { l1: { l2: { l3: { l4: { l5: { l6: { l7: { l8: { l9: 'deep' } } } } } } } } };
  sanitizePayload(deep, [], { maxDepth: 4 });
  console.log(`   Sanitized with maxDepth=4: ${JSON.stringify(deep)}\n`);

  // 5. Environment variable configuration
  console.log('5. Configurable via environment:');
  console.log('   PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH=2048');
  console.log('   PROVIDE_SECURITY_MAX_ATTR_COUNT=128');
  console.log('   PROVIDE_SECURITY_MAX_NESTING_DEPTH=4');

  shutdownTelemetry();
  console.log('\n=== Done ===');
}

main();
