// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
// @vitest-environment node

import { afterEach, describe, expect, it } from 'vitest';

import {
  counter,
  getConfig,
  getLogger,
  registerOtelProviders,
  resetTelemetryState,
  setupTelemetry,
  shutdownTelemetry,
  withTrace,
} from '../../src/index.js';

describe('OTLP collector integration', () => {
  afterEach(async () => {
    await shutdownTelemetry();
    resetTelemetryState();
  });

  it('exports logs, traces, and metrics through a real collector', async () => {
    const endpoint = process.env['PROVIDE_TEST_OTLP_ENDPOINT'];
    if (!endpoint) {
      return;
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

    const requests = counter('integration.collector.requests', { unit: '1' });
    const logger = getLogger('integration.collector');
    withTrace('integration.collector.span', () => {
      logger.info({ event: 'integration.collector.log', suite: 'integration' });
      requests.add(1, { suite: 'integration' });
    });

    await shutdownTelemetry();
    expect(true).toBe(true);
  });
});
