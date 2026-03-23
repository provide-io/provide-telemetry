// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Tracing — mirrors Python examples/telemetry/tracing.py
 *
 * withTrace() wraps sync or async functions in an OTEL span.
 * Works safely as a no-op when no OTEL SDK is registered.
 * traceDecorator (@trace) provides the same as a class method decorator.
 *
 * Run:
 *   npx tsx examples/tracing.ts
 */

import { getLogger, setupTelemetry, trace, withTrace } from '../src/index.js';

setupTelemetry({
  serviceName: 'tracing-demo',
  logLevel: 'debug',
  consoleOutput: true,
  captureToWindow: false,
  // otelEnabled: true,  // uncomment + set OTEL_EXPORTER_OTLP_ENDPOINT to export spans
});

const log = getLogger('tracing-demo');

// ── Functional API ─────────────────────────────────────────────────────────────

async function fetchUser(id: number): Promise<{ id: number; name: string }> {
  return withTrace('db.fetch_user', async () => {
    log.debug({ event: 'db_query', table: 'users', user_id: id });
    await new Promise((resolve) => setTimeout(resolve, 5)); // simulate DB
    return { id, name: 'Alice' };
  });
}

async function processOrder(orderId: string): Promise<string> {
  return withTrace('order.process', async () => {
    const user = await fetchUser(7); // nested span
    log.info({ event: 'order_processing', order_id: orderId, user: user.name });
    return `processed:${orderId}`;
  });
}

// ── Decorator API (requires experimentalDecorators: true) ─────────────────────

class PaymentService {
  @trace('payment.charge')
  charge(amount: number, currency: string): string {
    log.info({ event: 'payment_charge', amount, currency });
    return `charged:${amount}${currency}`;
  }

  @trace() // uses method name as span name
  async refund(transactionId: string): Promise<void> {
    log.info({ event: 'payment_refund', transaction_id: transactionId });
    await new Promise((resolve) => setTimeout(resolve, 2));
  }
}

async function main(): Promise<void> {
  const result = await processOrder('order-xyz-001');
  log.info({ event: 'done', result });

  const svc = new PaymentService();
  const chargeResult = svc.charge(99.99, 'USD');
  log.info({ event: 'charge_complete', result: chargeResult });

  await svc.refund('txn-abc-123');
  log.info({ event: 'refund_complete' });
}

main().catch(console.error);
