// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of Provide Telemetry.

/**
 * 🔒 PII masking and cardinality guardrails.
 *
 * Demonstrates:
 * - registerPiiRule / replacePiiRules / getPiiRules
 * - All four PII modes: hash, truncate, drop, redact
 * - Wildcard path matching for array items (e.g. 'players.*.secret')
 * - registerCardinalityLimit with TTL and OVERFLOW_VALUE
 * - getCardinalityLimits / clearCardinalityLimits / guardAttributes
 * - Default sensitive-key redaction vs. custom rule precedence
 *
 * Run: npx tsx examples/telemetry/05_pii_and_cardinality_policy.ts
 */

import {
  OVERFLOW_VALUE,
  clearCardinalityLimits,
  counter,
  getCardinalityLimits,
  getLogger,
  getPiiRules,
  guardAttributes,
  registerCardinalityLimit,
  registerPiiRule,
  replacePiiRules,
  sanitizePayload,
  setupTelemetry,
  shutdownTelemetry,
} from '../../src/index.js';

async function main(): Promise<void> {
  console.log('🔒 PII & Cardinality Policy Demo\n');

  setupTelemetry({ serviceName: 'provide-telemetry-examples', consoleOutput: false });
  const log = getLogger('examples.policy');
  const tokenValue = process.env['PROVIDE_EXAMPLE_TOKEN'] ?? 'example-token-from-env';

  // ── 🛡️ Register PII rules ────────────────────────────
  console.log('🛡️  Registering PII rules...');
  registerPiiRule({ path: 'user.email', mode: 'hash' });
  registerPiiRule({ path: 'user.full_name', mode: 'truncate', truncateTo: 3 });
  registerPiiRule({ path: 'credit_card', mode: 'drop' });
  console.log(`  📋 Active rules: ${getPiiRules().length}`);

  // ── 📝 Log with PII fields ───────────────────────────
  log.warn({
    event: 'example.policy.pii',
    user: { email: 'dev@example.com', full_name: 'Casey Developer' },
    credit_card: '4111111111111111',
    token: tokenValue,
  });

  // ── 🔀 Wildcard path matching for arrays ──────────────
  console.log('\n🔀 Wildcard path matching on array items...');
  const payload: Record<string, unknown> = {
    players: [
      { secret: 'key-aaa', name: 'Alice' },
      { secret: 'key-bbb', name: 'Bob' },
    ],
  };
  replacePiiRules([{ path: 'players.*.secret', mode: 'redact' }]);
  sanitizePayload(payload);
  const players = payload['players'] as Array<Record<string, unknown>>;
  for (const p of players) {
    console.log(`  🎭 ${p['name']}: secret=${p['secret']}`);
  }
  console.log(`  📋 Rules after replace: ${getPiiRules().length}`);

  // ── 🎯 Custom rule precedence over default redaction ──
  console.log("\n🎯 Custom rule vs. default 'password' redaction...");
  replacePiiRules([{ path: 'password', mode: 'truncate', truncateTo: 4 }]);
  const obj1: Record<string, unknown> = { password: 'hunter2' };
  sanitizePayload(obj1);
  console.log(`  🔑 password → ${obj1['password']}  (custom truncate, not '[REDACTED]')`);

  const obj2: Record<string, unknown> = { password: 'ab' };
  sanitizePayload(obj2);
  console.log(`  🔑 short password → ${obj2['password']}  (no-op truncate preserved)`);

  // ── 🚧 Cardinality limits with overflow ──────────────
  console.log('\n🚧 Cardinality guard (maxValues=2)...');
  replacePiiRules([]);
  registerCardinalityLimit('user_id', { maxValues: 2, ttlSeconds: 60 });

  const metric = counter('example.policy.requests');
  for (const userId of ['u1', 'u2', 'u3', 'u4']) {
    const attrs = guardAttributes({ user_id: userId });
    metric.add(1, attrs);
    const isOverflow = attrs['user_id'] === OVERFLOW_VALUE;
    const icon = isOverflow ? '⚠️' : '✅';
    console.log(`  ${icon} user_id=${userId} → guarded=${attrs['user_id']}`);
  }

  const limits = getCardinalityLimits();
  console.log(`\n  📊 Active cardinality limits: ${JSON.stringify([...limits.keys()])}`);

  // ── 🧹 Clear cardinality state ───────────────────────
  clearCardinalityLimits();
  console.log(`  🧹 After clear: ${getCardinalityLimits().size} limits`);

  console.log('\n🏁 Done!');
  await shutdownTelemetry();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
