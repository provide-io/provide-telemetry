// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Error fingerprinting and session correlation demo.
 *
 * Demonstrates:
 *   - Error fingerprinting: stable hex fingerprint per exception type + call site
 *   - Session correlation: bind a session ID that propagates across all log events
 *
 * Run: npx tsx typescript/examples/error_fingerprint_and_sessions.ts
 */

import {
  setupTelemetry,
  shutdownTelemetry,
  getLogger,
  computeErrorFingerprint,
  bindSessionContext,
  getSessionId,
  clearSessionContext,
} from '../src/index';

function demoErrorFingerprint(): void {
  console.log('--- Error Fingerprinting ---\n');

  // Same exception type produces the same fingerprint.
  const fpA = computeErrorFingerprint('ValueError');
  const fpB = computeErrorFingerprint('ValueError');
  console.log(`  ValueError fingerprint 1: ${fpA}`);
  console.log(`  ValueError fingerprint 2: ${fpB}`);
  console.log(`  Same? ${fpA === fpB}\n`);

  // Different types produce different fingerprints.
  const fpC = computeErrorFingerprint('TypeError');
  console.log(`  TypeError  fingerprint:   ${fpC}`);
  console.log(`  Differs from ValueError? ${fpA !== fpC}\n`);

  // With a real stack trace.
  try {
    throw new Error('simulated failure');
  } catch (err) {
    const e = err as Error;
    const fp = computeErrorFingerprint(e.constructor.name, e.stack);
    console.log(`  Error with stack fingerprint: ${fp}`);
  }

  // Normal events get no fingerprint (handled by the write hook automatically).
  console.log(`  Normal log event: no fingerprint added\n`);
}

function demoSessionCorrelation(): void {
  console.log('--- Session Correlation ---\n');

  const log = getLogger('examples.session');

  console.log(`  Session before bind: ${getSessionId()}`);

  bindSessionContext('sess-demo-42');
  console.log(`  Session after bind:  ${getSessionId()}`);

  log.info({ event: 'app.session.bound', msg: 'session is active' });
  log.info({ event: 'app.session.action', action: 'page_view', path: '/dashboard' });

  clearSessionContext();
  console.log(`  Session after clear: ${getSessionId()}\n`);
}

function main(): void {
  console.log('Error Fingerprinting and Session Correlation Demo (TypeScript)\n');

  setupTelemetry({ serviceName: 'ts-demo', logLevel: 'info' });

  demoErrorFingerprint();
  demoSessionCorrelation();

  console.log('Done!');
  shutdownTelemetry();
}

main();
