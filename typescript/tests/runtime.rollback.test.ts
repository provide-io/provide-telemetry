// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * A rejected runtime update must leave nothing behind.
 *
 * `validateRuntimeOverrides` does not know every rule `setupTelemetry` applies —
 * the export-attempt ceiling among them — so an override can pass the first
 * check and be rejected by the second. Publishing the merged config before
 * setupTelemetry accepts it left `getRuntimeConfig()` reporting a value that
 * threw, while the exporter policy still ran on the previous one.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { _resetConfig, getConfig, setupTelemetry } from '../src/config.js';
import { MAX_EXPORT_ATTEMPTS } from '../src/resilience.js';
import { _resetRuntimeForTests, getRuntimeConfig, updateRuntimeConfig } from '../src/runtime.js';

beforeEach(() => {
  _resetRuntimeForTests();
  _resetConfig();
  setupTelemetry({ serviceName: 'rollback' });
});

afterEach(() => {
  _resetRuntimeForTests();
  _resetConfig();
});

describe('updateRuntimeConfig rollback', () => {
  it('keeps the previous snapshot when setupTelemetry rejects the update', () => {
    updateRuntimeConfig({ exporterLogsRetries: 3 });
    expect(getRuntimeConfig().exporterLogsRetries).toBe(3);

    // Above the ceiling, but a non-negative integer — so it clears
    // validateRuntimeOverrides and is only caught inside setupTelemetry.
    expect(() => updateRuntimeConfig({ exporterLogsRetries: MAX_EXPORT_ATTEMPTS })).toThrow(
      /exporterLogsRetries/,
    );

    expect(getRuntimeConfig().exporterLogsRetries).toBe(3);
  });

  it('rolls back every field of the rejected update, not only the bad one', () => {
    updateRuntimeConfig({ samplingLogsRate: 0.25, exporterLogsRetries: 2 });

    expect(() =>
      updateRuntimeConfig({ samplingLogsRate: 0.9, exporterLogsRetries: MAX_EXPORT_ATTEMPTS }),
    ).toThrow();

    const cfg = getRuntimeConfig();
    expect(cfg.samplingLogsRate).toBe(0.25);
    expect(cfg.exporterLogsRetries).toBe(2);
  });

  it('still publishes an update setupTelemetry accepts', () => {
    updateRuntimeConfig({ exporterLogsRetries: MAX_EXPORT_ATTEMPTS - 1 });

    expect(getRuntimeConfig().exporterLogsRetries).toBe(MAX_EXPORT_ATTEMPTS - 1);
  });
});

describe('setupTelemetry atomicity', () => {
  it('leaves the effective config untouched when it rejects one', () => {
    // getConfig() is what the emit paths read. Publishing the candidate before
    // validating it left them running on values setupTelemetry had already
    // rejected, for any caller that caught the error and carried on.
    setupTelemetry({ serviceName: 'atomic', samplingLogsRate: 0.5 });

    expect(() => setupTelemetry({ samplingLogsRate: -0.1 })).toThrow(/samplingLogsRate/);

    expect(getConfig().samplingLogsRate).toBe(0.5);
    expect(getConfig().serviceName).toBe('atomic');
  });

  it('leaves the effective config untouched when a runtime override is rejected', () => {
    setupTelemetry({ serviceName: 'atomic', backpressureLogsMaxsize: 5 });

    expect(() => updateRuntimeConfig({ backpressureLogsMaxsize: -1 })).toThrow(
      /backpressureLogsMaxsize/,
    );

    expect(getConfig().backpressureLogsMaxsize).toBe(5);
    expect(getRuntimeConfig().backpressureLogsMaxsize).toBe(5);
  });
});
