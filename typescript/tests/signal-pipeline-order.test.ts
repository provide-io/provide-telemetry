// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Canonical signal pipeline order — spec/pipeline_fixtures.yaml.
//
// Every exit path through the pipeline is a subsequence of the canonical stage
// order: a stage may be skipped, but two stages may never swap places, and
// `release` runs on every path including rejections. A path that rejects an
// event and forgets to release leaks queue capacity until the process restarts.
//
// The stages here are observed on the *real* write hook rather than through a
// mock pipeline. A parallel `processSignal` built for the test could pass while
// the shipping pipeline diverged from it, which is the class of bug this whole
// fixture exists to prevent. The gates, the backend bridge and the bookkeeping
// report through the SDK's stage hook as they run; the payload stages are read
// off the marks they actually leave — a collapsed cycle, a redacted field, a
// collected receipt, a rendered record — at the moment the first post-sink
// stage reports, so each lands in the sequence where it really happened. Every
// fixture case is compared whole, release included.

import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { parse } from 'yaml';

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

import { LoggerProvider, BatchLogRecordProcessor } from '@opentelemetry/sdk-logs';
import { OTLPLogExporter } from '@opentelemetry/exporter-logs-otlp-http';
import { logs } from '@opentelemetry/api-logs';
import { specFixturePath } from './support/spec-fixtures.js';
import { _resetBackpressureForTests, setQueuePolicy, tryAcquire } from '../src/backpressure.js';
import { _resetConfig, setupTelemetry } from '../src/config.js';
import { resetConsentForTests, setConsentLevel } from '../src/consent.js';
import { _resetHealthForTests, getHealthSnapshot } from '../src/health.js';
import { _resetRootLogger, makeWriteHook } from '../src/logger.js';
import { _resetOtelLogProviderForTests, setupOtelLogProvider } from '../src/otel-logs.js';
import { resetPiiRulesForTests } from '../src/pii.js';
import { _setPipelineStageHook } from '../src/pipeline-stages.js';
import {
  enableReceipts,
  getEmittedReceiptsForTests,
  resetReceiptsForTests,
} from '../src/receipts.js';
import { _resetSamplingForTests, setSamplingPolicy } from '../src/sampling.js';

interface PipelineCase {
  id: string;
  description: string;
  expected: string[];
}

const FIXTURES = specFixturePath('pipeline_fixtures.yaml');
const fixture = parse(readFileSync(FIXTURES, 'utf8')) as {
  events: string[];
  cases: PipelineCase[];
};

function reset(): void {
  _setPipelineStageHook(null);
  _resetConfig();
  _resetRootLogger();
  _resetHealthForTests();
  _resetBackpressureForTests();
  _resetSamplingForTests();
  _resetOtelLogProviderForTests();
  resetConsentForTests();
  resetPiiRulesForTests();
  resetReceiptsForTests();
}

beforeEach(reset);
afterEach(() => {
  reset();
  vi.restoreAllMocks();
});

interface Run {
  /** Undefined: no backend. Otherwise the OTel logger's emit behaviour. */
  backend?: 'accepts' | 'throws';
  gates?: () => void;
}

async function installBackend(mode: 'accepts' | 'throws'): Promise<void> {
  vi.mocked(LoggerProvider).mockImplementation(function () {
    return { shutdown: vi.fn(), forceFlush: vi.fn() };
  } as never);
  vi.mocked(BatchLogRecordProcessor).mockImplementation(function () {
    return {};
  } as never);
  vi.mocked(OTLPLogExporter).mockImplementation(function () {
    return {};
  } as never);
  const emit = vi.fn(() => {
    if (mode === 'throws') throw new Error('collector refused');
  });
  vi.mocked(logs.getLogger).mockReturnValue({ emit } as never);
  await setupOtelLogProvider({
    serviceName: 'pipeline-svc',
    otelEnabled: true,
    otlpEndpoint: 'http://localhost:4318',
  } as never);
}

/**
 * Run one record through the real write hook and report the stages it passed.
 *
 * The record carries a cycle and a sensitive key, so hardening and PII each
 * leave a distinguishable mark on the same input.
 */
async function observeStages(run: Run): Promise<string[]> {
  setupTelemetry({ serviceName: 'pipeline-svc', logLevel: 'trace', consoleOutput: true });
  if (run.backend) await installBackend(run.backend);
  enableReceipts({ enabled: true, serviceName: 'pipeline-svc' });
  // Gates are configured after setup, which installs the default policies and
  // would otherwise overwrite them.
  setQueuePolicy({ maxLogs: 1 });
  run.gates?.();
  // Last, so every counter read in the hook is this record's alone.
  _resetHealthForTests();

  const rendered: unknown[] = [];
  const spy = vi.spyOn(console, 'log').mockImplementation((...args: unknown[]) => {
    rendered.push(args);
  });

  const record: Record<string, unknown> = {
    level: 30,
    event: 'pipeline.probe',
    message: 'pipeline.probe',
    password: 'secret123', // pragma: allowlist secret
  };
  record['self'] = record;

  const stages: string[] = [];
  let sinksReached = false;
  _setPipelineStageHook((stage) => {
    if (
      !sinksReached &&
      (stage === 'backend' || stage === 'health') &&
      stages.includes('backpressure')
    ) {
      sinksReached = true;
      if (record['self'] === '***') stages.push('hardening');
      if (record['password'] === '***') stages.push('pii');
      if (getEmittedReceiptsForTests().length > 0) stages.push('receipt');
      if (rendered.length > 0) stages.push('local');
    }
    // Health counts the record only after every sink has run.
    if (!stages.includes('health') && stage !== 'health' && getHealthSnapshot().logsEmitted !== 0) {
      stages.push(`health-before-${stage}`);
    }
    stages.push(stage);
  });
  try {
    makeWriteHook()(record);
  } finally {
    _setPipelineStageHook(null);
    spy.mockRestore();
  }
  return stages;
}

/** True when a fresh ticket can still be taken from a single-slot queue. */
function ticketWasReleased(): boolean {
  return tryAcquire('logs') !== null;
}

let held: ReturnType<typeof tryAcquire> = null;

const RUNS: Record<string, Run> = {
  consent_rejection: { gates: () => setConsentLevel('NONE') },
  sampling_rejection: { gates: () => setSamplingPolicy('logs', { defaultRate: 0 }) },
  queue_rejection: { gates: () => (held = tryAcquire('logs')) },
  local_only_success: {},
  backend_success: { backend: 'accepts' },
  backend_failure: { backend: 'throws' },
};

describe('canonical stage order', () => {
  it('matches the fixture the other SDKs are held to', () => {
    expect(fixture.events).toEqual([
      'consent',
      'sampling',
      'backpressure',
      'hardening',
      'pii',
      'receipt',
      'local',
      'backend',
      'health',
      'release',
    ]);
  });

  it.each(fixture.cases)('$id keeps its stages in canonical order', (testCase) => {
    const ordered = fixture.events.filter((event) => testCase.expected.includes(event));
    expect(ordered).toEqual(testCase.expected);
  });

  it.each(fixture.cases)('$id releases its ticket exactly once', (testCase) => {
    expect(testCase.expected.filter((event) => event === 'release')).toHaveLength(1);
  });

  it('has a run for every fixture case, and no run without one', () => {
    expect(Object.keys(RUNS).sort()).toEqual(fixture.cases.map((c) => c.id).sort());
  });
});

describe('observed stages on the real write hook', () => {
  it.each(fixture.cases)('$id runs exactly the fixture sequence', async (testCase) => {
    held = null;
    const observed = await observeStages(RUNS[testCase.id] as Run);
    expect(observed).toEqual(testCase.expected);
    if (held !== null) {
      // The refused record must not have consumed the one remaining slot:
      // with the held ticket still outstanding, the queue stays full.
      expect(tryAcquire('logs')).toBeNull();
      _resetBackpressureForTests();
      setQueuePolicy({ maxLogs: 1 });
    }
    expect(ticketWasReleased()).toBe(true);
  });

  it.each([
    ['consent', { gates: () => setConsentLevel('NONE') }, [0, 1, 0]],
    ['sampling', { gates: () => setSamplingPolicy('logs', { defaultRate: 0 }) }, [0, 1, 0]],
    ['admitted', { backend: 'accepts' }, [1, 0, 0]],
    ['refused by the backend', { backend: 'throws' }, [1, 0, 1]],
  ] as Array<[string, Run, number[]]>)(
    'health counts the %s path once',
    async (_name, run, counts) => {
      await observeStages(run);
      const health = getHealthSnapshot();
      expect([health.logsEmitted, health.logsDropped, health.exportFailuresLogs]).toEqual(counts);
    },
  );
});
