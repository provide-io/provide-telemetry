// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * PII sanitization — mirrors Python examples/telemetry/pii_sanitization.py
 *
 * DEFAULT_SANITIZE_FIELDS is always applied. Add custom fields via setupTelemetry.
 *
 * Run:
 *   npx tsx examples/pii_sanitization.ts
 */

import { DEFAULT_SANITIZE_FIELDS, getLogger, sanitize, setupTelemetry } from '../src/index.js';

setupTelemetry({
  serviceName: 'pii-demo',
  logLevel: 'debug',
  // Additional fields to redact beyond the defaults
  sanitizeFields: ['ssn', 'credit_card_number', 'api_secret'],
  consoleOutput: true,
  captureToWindow: false,
});

const log = getLogger('pii-demo');

console.log('\n── Default sanitize fields ────────────────────────────────────');
console.log(DEFAULT_SANITIZE_FIELDS);

// ── Manual sanitize() call ─────────────────────────────────────────────────────

const rawPayload: Record<string, unknown> = {
  event: 'user_login',
  user_id: 42,
  username: 'alice',
  password: 'super-secret-123',
  token: 'eyJhbGciOiJIUzI1NiJ9...',
  ip_address: '192.168.1.1',
};

console.log('\n── Before sanitize ────────────────────────────────────────────');
console.log(rawPayload);

sanitize(rawPayload, ['ip_address']); // add ip_address as a custom field

console.log('\n── After sanitize ─────────────────────────────────────────────');
console.log(rawPayload);

// ── PII sanitization flows automatically through the logger ───────────────────

console.log('\n── Via logger (automatic) ─────────────────────────────────────');
log.warn({
  event: 'auth_attempt',
  username: 'bob',
  password: 'should-be-redacted',
  token: 'also-redacted',
  user_agent: 'Mozilla/5.0 (visible)',
  ip: '10.0.0.1',
});
