// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Prove `flushTelemetry()` puts records on the wire without tearing providers down.
 *
 * Why a standalone process rather than a case in otlp-collector.test.ts: the
 * collector is verified by grepping its debug log after the run, which cannot
 * tell *when* a record arrived. If this process also called shutdownTelemetry(),
 * shutdown's own drain would be an equally good explanation for anything that
 * showed up, and the test would pass with flush completely broken.
 *
 * So this exits without shutting down. Every signal named below can only have
 * reached the collector because flush sent it.
 *
 * It also emits a second set *after* the flush and asserts the providers are
 * still installed, which is the other half of the contract — flush drains, it
 * does not tear down.
 */

import {
  counter,
  flushTelemetry,
  getConfig,
  getLogger,
  getRuntimeStatus,
  registerOtelProviders,
  setupTelemetry,
  withTrace,
} from '../src/index.js';

const endpoint = process.env['PROVIDE_TEST_OTLP_ENDPOINT'];
if (!endpoint) {
  console.error('flush-collector-probe: PROVIDE_TEST_OTLP_ENDPOINT unset; skipping');
  process.exit(0);
}

function fail(message: string): never {
  console.error(`flush-collector-probe: FAIL — ${message}`);
  process.exit(1);
}

setupTelemetry({
  serviceName: 'provide-telemetry-typescript-integration',
  otelEnabled: true,
  metricsEnabled: true,
  otlpEndpoint: endpoint,
  consoleOutput: false,
  captureToWindow: false,
});
await registerOtelProviders(getConfig());

const before = getRuntimeStatus();
if (!before.providers.traces || !before.providers.metrics || !before.providers.logs) {
  fail(`providers not installed before flush: ${JSON.stringify(before.providers)}`);
}

// Batch one — only a working flush can deliver this, since we never shut down.
const requests = counter('integration.flush.requests', { unit: '1' });
const logger = getLogger('integration.flush');
withTrace('integration.flush.span', () => {
  logger.info({ event: 'integration.flush.log', suite: 'flush' });
  requests.add(1, { suite: 'flush' });
});

const drained = await flushTelemetry();
if (!drained) {
  fail('flushTelemetry() reported an incomplete drain against a reachable collector');
}

// Flush drains; it must not tear down. Providers stay installed and telemetry
// keeps working — the second batch proves the pipeline survived the drain.
const after = getRuntimeStatus();
if (!after.providers.traces || !after.providers.metrics || !after.providers.logs) {
  fail(`flush tore providers down: ${JSON.stringify(after.providers)}`);
}
if (!after.setupDone) {
  fail('flush cleared setup state');
}

withTrace('integration.flush.after.span', () => {
  logger.info({ event: 'integration.flush.after.log', suite: 'flush-after' });
  requests.add(1, { suite: 'flush-after' });
});

const drainedAgain = await flushTelemetry();
if (!drainedAgain) {
  fail('a second flushTelemetry() reported an incomplete drain; flush is not repeatable');
}

console.error('flush-collector-probe: OK — flushed twice, providers still installed');
// Deliberately no shutdownTelemetry(): see the module comment.
process.exit(0);
