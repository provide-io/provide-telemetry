// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Context binding — mirrors Python examples/telemetry/context_binding.py
 *
 * Demonstrates bind_context / unbind_context / clear_context and runWithContext
 * for per-request context isolation in async workloads.
 *
 * Run:
 *   npx tsx examples/context_binding.ts
 */

import {
  bindContext,
  clearContext,
  getContext,
  getLogger,
  runWithContext,
  setupTelemetry,
  unbindContext,
} from '../src/index.js';

setupTelemetry({
  serviceName: 'context-demo',
  logLevel: 'debug',
  consoleOutput: true,
  captureToWindow: false,
});

const log = getLogger('demo');

// ── Module-level context ───────────────────────────────────────────────────────

// Bind fields that apply to all log records in this module
bindContext({ env: 'production', region: 'us-east-1' });
log.info({ event: 'startup' }); // → includes env, region

// Selectively remove a field
unbindContext('region');
log.info({ event: 'after_unbind' }); // → only env

// ── Request-scoped context via runWithContext ──────────────────────────────────

async function handleRequest(requestId: string, userId: number): Promise<void> {
  // runWithContext creates an isolated copy of the current context for this async call.
  // In Node.js, AsyncLocalStorage ensures the bindings don't bleed across concurrent requests.
  await runWithContext({ request_id: requestId, user_id: userId }, async () => {
    log.info({ event: 'request_start', method: 'POST', path: '/api/orders' });

    await new Promise((resolve) => setTimeout(resolve, 1)); // simulate async work

    log.info({ event: 'db_query', table: 'orders', rows: 3 });
    log.info({ event: 'request_complete', status: 201 });
  });
}

async function main(): Promise<void> {
  // Simulate two concurrent requests — their context bindings are isolated
  await Promise.all([handleRequest('req-001', 7), handleRequest('req-002', 42)]);

  // Back in the outer context — request_id and user_id are gone
  log.info({ event: 'all_requests_done', ctx: getContext() });

  clearContext();
  log.info({ event: 'context_cleared' }); // → no extra fields
}

main().catch(console.error);
