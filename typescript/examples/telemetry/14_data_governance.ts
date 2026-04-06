#!/usr/bin/env npx tsx
// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * 14_data_governance — consent levels, data classification, and redaction receipts.
 *
 * Demonstrates:
 *  - ConsentLevel: gate signal collection per user consent tier
 *  - Data classification: label fields by sensitivity class; pair with PIIRules for enforcement
 *  - RedactionReceipts: cryptographic audit trail for every PII redaction
 *
 * Run: npx tsx examples/telemetry/14_data_governance.ts
 */

import {
  event,
  getLogger,
  registerPiiRule,
  sanitizePayload,
  setupTelemetry,
  shutdownTelemetry,
} from '@provide-io/telemetry';
import { setConsentLevel, shouldAllow } from '@provide-io/telemetry';
import { registerClassificationRules } from '@provide-io/telemetry';
import {
  enableReceipts,
  getEmittedReceiptsForTests,
  resetReceiptsForTests,
} from '@provide-io/telemetry';

// ── 1. Consent Levels ────────────────────────────────────────────────────────
function demoConsent(): void {
  console.log('── 1. Consent Levels ──────────────────────────────────────');
  const levels = ['FULL', 'FUNCTIONAL', 'MINIMAL', 'NONE'] as const;
  for (const level of levels) {
    setConsentLevel(level);
    const logsDebug = shouldAllow('logs', 'DEBUG');
    const logsError = shouldAllow('logs', 'ERROR');
    const traces = shouldAllow('traces');
    const metrics = shouldAllow('metrics');
    const ctx = shouldAllow('context');
    console.log(
      `  ${level.padEnd(12)} logs(DEBUG)=${String(logsDebug).padEnd(5)} ` +
        `logs(ERROR)=${String(logsError).padEnd(5)} traces=${String(traces).padEnd(5)} ` +
        `metrics=${String(metrics).padEnd(5)} context=${ctx}`,
    );
  }
  setConsentLevel('FULL');
  console.log();
}

// ── 2. Data Classification ───────────────────────────────────────────────────
function demoClassification(): void {
  console.log('── 2. Data Classification ─────────────────────────────────');
  // Register rules: pattern → DataClass label
  registerClassificationRules([
    { pattern: 'ssn', classification: 'PII' },
    { pattern: 'card_number', classification: 'PCI' },
    { pattern: 'diagnosis', classification: 'PHI' },
    { pattern: 'api_*', classification: 'SECRET' },
  ]);
  // Classification adds __key__class labels to sanitized output.
  // Enforcement (drop, hash, redact) is applied by registering PIIRules per class.
  registerPiiRule({ path: 'ssn', mode: 'redact' });
  registerPiiRule({ path: 'card_number', mode: 'hash' });
  registerPiiRule({ path: 'diagnosis', mode: 'drop' });
  registerPiiRule({ path: 'api_key', mode: 'drop' });

  // sanitizePayload mutates in-place; capture originals before sanitizing
  const originals: Record<string, unknown> = {
    user: 'alice',
    ssn: '123-45-6789',
    card_number: '4111111111111111',
    diagnosis: 'hypertension',
    api_key: 'sk-prod-abc123', // pragma: allowlist secret
  };
  const payload: Record<string, unknown> = { ...originals };
  sanitizePayload(payload);

  console.log('  Field values after sanitization:');
  for (const k of Object.keys(originals)) {
    const out = k in payload ? JSON.stringify(payload[k]) : '<dropped>';
    console.log(`    ${k}: ${out}`);
  }

  console.log('\n  Classification labels added to output:');
  for (const [k, v] of Object.entries(payload)) {
    if (k.endsWith('__class')) {
      console.log(`    ${k}: ${JSON.stringify(v)}`);
    }
  }
  console.log();
}

// ── 3. Redaction Receipts ────────────────────────────────────────────────────
function demoReceipts(): void {
  console.log('── 3. Redaction Receipts ──────────────────────────────────');
  resetReceiptsForTests();
  enableReceipts({
    enabled: true,
    signingKey: 'demo-hmac-key', // pragma: allowlist secret
    serviceName: 'governance-demo',
  });

  registerPiiRule({ path: 'password', mode: 'redact' });
  const receiptPayload = { user: 'bob', password: 's3cr3t' }; // pragma: allowlist secret
  sanitizePayload(receiptPayload);

  const receipts = getEmittedReceiptsForTests();
  if (receipts.length > 0) {
    const r = receipts[receipts.length - 1];
    console.log(`  receiptId:    ${r.receiptId}`);
    console.log(`  fieldPath:    ${r.fieldPath}`);
    console.log(`  action:       ${r.action}`);
    console.log(`  originalHash: ${r.originalHash.slice(0, 16)}...`);
    console.log(r.hmac ? `  hmac:         ${r.hmac.slice(0, 16)}...` : '  hmac:         (unsigned)');
  } else {
    console.log('  (no receipts captured)');
  }
  enableReceipts({ enabled: false });
  console.log();
}

// ── Main ─────────────────────────────────────────────────────────────────────
async function main(): Promise<void> {
  setupTelemetry({ serviceName: 'governance-demo' });
  const log = getLogger('governance-demo');
  log.info({ ...event('governance', 'demo', 'start') });

  console.log('=== Data Governance Demo ===\n');
  demoConsent();
  demoClassification();
  demoReceipts();

  await shutdownTelemetry();
  console.log('=== Done ===');
}

main().catch(console.error);
