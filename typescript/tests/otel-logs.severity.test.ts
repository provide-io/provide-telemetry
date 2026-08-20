// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
// @vitest-environment node

/**
 * The canonical-level → OTel-severity tables, asserted from a freshly evaluated module.
 *
 * SEVERITY_MAP and SEVERITY_TEXT are module-level object literals, so they are
 * built once at import time — before any test has started. Stryker's perTest V8
 * coverage then attributes a mutation of an entry to no test at all, and every
 * one of the eight table mutants was reported as a survivor even though
 * otel-logs.emit.test.ts asserts the mapping level by level. `vi.resetModules()`
 * before the import re-evaluates the tables inside the test, which is the same
 * treatment runtime.arrays.test.ts and hash.mutants.test.ts give their own
 * module-level constants.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('@opentelemetry/sdk-logs', () => ({
  LoggerProvider: vi.fn(),
  BatchLogRecordProcessor: vi.fn(),
}));
vi.mock('@opentelemetry/exporter-logs-otlp-http', () => ({
  OTLPLogExporter: vi.fn(),
}));
vi.mock('@opentelemetry/api-logs', () => ({
  logs: {
    setGlobalLoggerProvider: vi.fn(),
    getLogger: vi.fn(),
  },
}));

interface EmittedRecord {
  severityNumber: number;
  severityText: string;
}

/**
 * Re-evaluate otel-logs.ts, then push one record per canonical level through it.
 *
 * The mocked peer deps are re-instantiated by resetModules too, so the logger
 * stub has to be installed on the freshly imported @opentelemetry/api-logs
 * rather than on the copy this file imported at load time.
 */
async function severitiesFor(levels: string[]): Promise<EmittedRecord[]> {
  vi.resetModules();
  const apiLogs = await import('@opentelemetry/api-logs');
  const emitted: EmittedRecord[] = [];
  vi.mocked(apiLogs.logs.getLogger).mockReturnValue({
    emit: (record: EmittedRecord) => {
      emitted.push(record);
    },
  } as never);
  const { emitLogRecord, setupOtelLogProvider } = await import('../src/otel-logs.js');
  await setupOtelLogProvider({
    serviceName: 'severity-test',
    otelEnabled: true,
    otlpEndpoint: 'http://localhost:4318',
  } as never);
  for (const level of levels) {
    emitLogRecord({ level, message: 'm', time: 1 });
  }
  return emitted;
}

describe('otel-logs severity tables', () => {
  afterEach(() => {
    vi.resetModules();
  });

  it('maps every canonical level to its OTel severity number and text', async () => {
    const emitted = await severitiesFor([
      'TRACE',
      'DEBUG',
      'INFO',
      'WARN',
      'ERROR',
      'CRITICAL',
      'nonsense',
    ]);
    expect(emitted.map((r) => [r.severityNumber, r.severityText])).toEqual([
      [1, 'TRACE'],
      [5, 'DEBUG'],
      [9, 'INFO'],
      [13, 'WARN'],
      [17, 'ERROR'],
      [21, 'FATAL'],
      // A level outside the table falls back to INFO in both directions —
      // an unrecognised level must not arrive at the collector as severity 0.
      [9, 'INFO'],
    ]);
  });
});
