// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of Provide Telemetry.

/**
 * 🌐 W3C trace-context propagation.
 *
 * Demonstrates:
 * - extractW3cContext for W3C traceparent/tracestate/baggage header parsing
 * - bindPropagationContext / clearPropagationContext lifecycle
 * - getActivePropagationContext for downstream correlation
 * - getTraceContext for reading the active trace IDs
 *
 * Note: The Python equivalent uses ASGI middleware; this example shows
 * the same propagation primitives via direct header parsing.
 *
 * Run: npx tsx examples/telemetry/02_w3c_propagation.ts
 */

import {
  bindPropagationContext,
  clearPropagationContext,
  extractW3cContext,
  getActivePropagationContext,
  getLogger,
  getTraceContext,
  setupTelemetry,
  shutdownTelemetry,
} from '../../src/index.js';

function runHttpRequest(): void {
  console.log('\n🔗 HTTP request — full W3C header propagation');

  const headers: Record<string, string> = {
    traceparent: '00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01',
    tracestate: 'vendor=value',
    baggage: 'user_id=123',
  };

  const extracted = extractW3cContext(headers);
  console.log(`  📥 Extracted traceId=${extracted.traceId}`);
  console.log(`  📥 Extracted spanId=${extracted.spanId}`);
  console.log(`  📥 Baggage: ${extracted.baggage}`);

  bindPropagationContext(extracted);

  const log = getLogger('examples.w3c');
  const active = getActivePropagationContext();
  log.info({ event: 'example.w3c.received', traceId: active.traceId });

  const traceCtx = getTraceContext();
  log.info({ event: 'example.w3c.trace', traceCtx });

  clearPropagationContext();
  console.log('  ✅ Response dispatched, context cleared');
}

function runManualPropagation(): void {
  console.log('\n🧪 Manual propagation context bind/clear');

  const headers: Record<string, string> = {
    traceparent: '00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01',
    tracestate: 'game=chess',
  };

  const ctx = extractW3cContext(headers);
  bindPropagationContext(ctx);

  const active = getActivePropagationContext();
  console.log(`  🔍 Bound traceId=${active.traceId}`);
  console.log(`  🔍 Bound spanId=${active.spanId}`);

  clearPropagationContext();
  const after = getActivePropagationContext();
  console.log(`  🧹 After clear: traceId=${after.traceId}`);
}

function runNestedPropagation(): void {
  console.log('\n🎮 Nested propagation context (outer → inner)');

  const outer = extractW3cContext({
    traceparent: '00-1111111111111111ffffffffffffffff-1111111111111111-01',
  });
  const inner = extractW3cContext({
    traceparent: '00-2222222222222222ffffffffffffffff-2222222222222222-01',
  });

  bindPropagationContext(outer);
  console.log(`  📋 Outer: ${getActivePropagationContext().traceId}`);

  bindPropagationContext(inner);
  console.log(`  📋 Inner: ${getActivePropagationContext().traceId}`);

  clearPropagationContext();
  console.log(`  📋 Restored outer: ${getActivePropagationContext().traceId}`);

  clearPropagationContext();
  console.log(`  📋 After full clear: ${getActivePropagationContext().traceId ?? '(none)'}`);
}

function runInvalidHeader(): void {
  console.log('\n⚠️  Invalid traceparent header — graceful ignore');

  const ctx = extractW3cContext({ traceparent: 'not-a-valid-traceparent' });
  console.log(`  traceId=${ctx.traceId ?? '(ignored)'}  ✅ No throw`);

  const allZeroCtx = extractW3cContext({
    traceparent: '00-00000000000000000000000000000000-00f067aa0ba902b7-01',
  });
  console.log(`  all-zero traceId=${allZeroCtx.traceId ?? '(ignored)'}  ✅ No throw`);
}

async function main(): Promise<void> {
  console.log('🌐 W3C Propagation Demo');
  setupTelemetry({ serviceName: 'provide-telemetry-examples', consoleOutput: false });

  runHttpRequest();
  runManualPropagation();
  runNestedPropagation();
  runInvalidHeader();

  console.log('\n🏁 Done!');
  await shutdownTelemetry();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
