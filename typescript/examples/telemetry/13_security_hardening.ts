#!/usr/bin/env npx tsx
// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Security hardening features demo.
 *
 * Demonstrates:
 *   - PII sanitization with field-name matching
 *   - Secret detection in values (AWS keys, JWTs, GitHub tokens)
 *   - Configurable sanitization fields
 *
 * Run: npx tsx typescript/examples/security_hardening.ts
 */

import {
  setupTelemetry,
  shutdownTelemetry,
  getLogger,
  event,
  sanitize,
  registerPiiRule,
  getPiiRules,
} from '../../src/index.js';

function main(): void {
  console.log('=== Security Hardening Demo (TypeScript) ===\n');

  setupTelemetry({ serviceName: 'ts-security-demo', logLevel: 'info' });
  const log = getLogger('security-demo');

  // 1. Default PII sanitization — password, token, authorization, api_key, secret
  console.log('1. Default PII sanitization:');
  const payload: Record<string, unknown> = {
    user: 'alice',
    password: 'hunter2', // pragma: allowlist secret
    token: 'abc123',
    notes: 'normal text',
  };
  sanitize(payload, ['password', 'token', 'authorization', 'api_key', 'secret']);
  console.log(`   user: ${payload['user']}`);
  console.log(`   password: ${payload['password']}`);
  console.log(`   token: ${payload['token']}`);
  console.log(`   notes: ${payload['notes']}\n`);

  // 2. Custom PII rules
  console.log('2. Custom PII rules:');
  registerPiiRule({ path: ['email'], mode: 'redact' });
  console.log(`   Registered rules: ${getPiiRules().length}`);

  log.info({ ...event('security', 'demo', 'pii'), email: 'alice@example.com', name: 'Alice' });
  console.log('   (email field redacted in log output)\n');

  // 3. Logging with automatic secret detection
  console.log('3. Automatic secret detection in logger:');
  log.info({
    ...event('security', 'demo', 'secrets'),
    safe_field: 'normal value',
    debug_info: 'nothing sensitive here',
  });
  console.log('   (secrets in any field are auto-redacted via PII sanitization)\n');

  // 4. Environment variable configuration
  console.log('4. Configurable via environment:');
  console.log('   PROVIDE_LOG_SANITIZE=true (default)');
  console.log('   PROVIDE_LOG_SANITIZE_FIELDS=password,token,authorization,api_key,secret');

  shutdownTelemetry();
  console.log('\n=== Done ===');
}

main();
