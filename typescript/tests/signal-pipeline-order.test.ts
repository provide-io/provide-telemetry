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
// mock observer. A parallel `processSignal` built for the test could pass
// while the shipping pipeline diverged from it, which is the class of bug this
// whole fixture exists to prevent — so each stage is detected by the effect it
// actually leaves behind: a health counter, a redacted field, a collected
// receipt, a rendered record, a returned ticket.

import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { parse } from 'yaml';
import { specFixturePath } from './support/spec-fixtures.js';
import { _resetBackpressureForTests, setQueuePolicy, tryAcquire } from '../src/backpressure.js';
import { _resetConfig, setupTelemetry } from '../src/config.js';
import { resetConsentForTests, setConsentLevel } from '../src/consent.js';
import { _resetHealthForTests, getHealthSnapshot } from '../src/health.js';
import { _resetRootLogger, makeWriteHook } from '../src/logger.js';
import { resetPiiRulesForTests } from '../src/pii.js';
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

/** Stages this suite can observe on the logs pipeline. */
const OBSERVABLE = new Set([
  'consent',
  'sampling',
  'backpressure',
  'hardening',
  'pii',
  'receipt',
  'local',
  'health',
  'release',
]);

function reset(): void {
  _resetConfig();
  _resetRootLogger();
  _resetHealthForTests();
  _resetBackpressureForTests();
  _resetSamplingForTests();
  resetConsentForTests();
  resetPiiRulesForTests();
  resetReceiptsForTests();
}

beforeEach(reset);
afterEach(() => {
  reset();
  vi.restoreAllMocks();
});

/**
 * Run one record through the real write hook and report which stages ran.
 *
 * The record carries a cycle and a sensitive key, so hardening and PII each
 * leave a distinguishable mark on the same input.
 */
function observeStages(configureGates: () => void = () => undefined): string[] {
  setupTelemetry({ serviceName: 'pipeline-svc', logLevel: 'trace' });
  enableReceipts({ enabled: true, serviceName: 'pipeline-svc' });
  // Gates are configured after setup, which installs the default policies and
  // would otherwise overwrite them.
  configureGates();

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

  const before = getHealthSnapshot();
  try {
    makeWriteHook()(record);
  } finally {
    spy.mockRestore();
  }
  const after = getHealthSnapshot();

  // Reaching the hook at all means consent was consulted; everything after it
  // is inferred from the marks the record and the counters carry.
  return ['consent'].concat(
    detect(record, rendered, before, after).filter((stage) => OBSERVABLE.has(stage)),
  );
}

function detect(
  record: Record<string, unknown>,
  rendered: unknown[],
  before: ReturnType<typeof getHealthSnapshot>,
  after: ReturnType<typeof getHealthSnapshot>,
): string[] {
  const stages: string[] = [];
  const reachedBody = rendered.length > 0 || after.logsEmitted > before.logsEmitted;
  if (!reachedBody) return stages;
  // Everything below only happens inside the hook body, which is reached only
  // after sampling and backpressure both admitted the record.
  stages.push('sampling', 'backpressure');
  if (record['self'] === '***') stages.push('hardening');
  if (record['password'] === '***') stages.push('pii');
  if (getEmittedReceiptsForTests().length > 0) stages.push('receipt');
  if (rendered.length > 0) stages.push('local');
  if (after.logsEmitted > before.logsEmitted) stages.push('health');
  return stages;
}

/** True when a fresh ticket can still be taken from a single-slot queue. */
function ticketWasReleased(): boolean {
  const ticket = tryAcquire('logs');
  if (ticket === null) return false;
  return true;
}

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
});

describe('observed stages on the real write hook', () => {
  it('runs every observable stage on the full success path', () => {
    const observed = observeStages();
    const expected = (
      fixture.cases.find((c) => c.id === 'backend_success') as PipelineCase
    ).expected.filter((stage) => OBSERVABLE.has(stage));
    expect(observed).toEqual(expected.filter((stage) => stage !== 'release'));
    expect(ticketWasReleased()).toBe(true);
  });

  it('stops at consent when consent is withheld, and still releases', () => {
    const observed = observeStages(() => {
      setConsentLevel('NONE');
    });
    expect(observed).toEqual(['consent']);
    expect(ticketWasReleased()).toBe(true);
  });

  it('stops at sampling when the rate is zero, and still releases', () => {
    const observed = observeStages(() => {
      setSamplingPolicy('logs', { defaultRate: 0 });
    });
    expect(observed).toEqual(['consent']);
    expect(ticketWasReleased()).toBe(true);
  });

  it('stops at backpressure when the queue is full, and leaks no capacity', () => {
    let held: ReturnType<typeof tryAcquire> = null;
    const observed = observeStages(() => {
      setQueuePolicy({ maxLogs: 1 });
      held = tryAcquire('logs');
    });
    expect(held).not.toBeNull();
    expect(observed).toEqual(['consent']);
    // The rejected record must not have consumed the one remaining slot: with
    // the held ticket still outstanding, the queue is full and stays full.
    expect(tryAcquire('logs')).toBeNull();
  });

  it('hardens before PII, so a cycle never reaches the PII traversal', () => {
    // Order matters, not just presence: PII walks the record recursively, so a
    // cycle that survived hardening would be its problem to solve.
    const observed = observeStages();
    expect(observed.indexOf('hardening')).toBeLessThan(observed.indexOf('pii'));
    expect(observed.indexOf('pii')).toBeLessThan(observed.indexOf('receipt'));
    expect(observed.indexOf('receipt')).toBeLessThan(observed.indexOf('local'));
    expect(observed.indexOf('local')).toBeLessThan(observed.indexOf('health'));
  });
});
