// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { _resetConfig, setupTelemetry } from '../src/config';
import { _resetContext } from '../src/context';
import { _resetHealthForTests, getHealthSnapshot } from '../src/health';
import { _resetRootLogger, makeWriteHook } from '../src/logger';
import { _resetSamplingForTests, setSamplingPolicy } from '../src/sampling';
import { setConsentLevel, resetConsentForTests } from '../src/consent';
import { setQueuePolicy, tryAcquire, _resetBackpressureForTests } from '../src/backpressure';

function makeCfg(overrides?: Parameters<typeof setupTelemetry>[0]) {
  _resetConfig();
  setupTelemetry({
    serviceName: 'test-svc',
    logLevel: 'debug',
    captureToWindow: true,
    ...overrides,
  });
}

beforeEach(() => {
  _resetConfig();
  _resetRootLogger();
  _resetContext();
  setupTelemetry({ serviceName: 'test-svc', logLevel: 'debug', captureToWindow: true });
  (window as unknown as Record<string, unknown>)['__pinoLogs'] = [];
});

afterEach(() => {
  _resetConfig();
  _resetRootLogger();
  _resetContext();
});

describe('write hook — logsEmitted health counter', () => {
  beforeEach(() => _resetHealthForTests());
  afterEach(() => _resetHealthForTests());

  it('increments logsEmitted by 1 for each log record that survives all filters', () => {
    makeCfg();
    const hook = makeWriteHook();
    expect(getHealthSnapshot().logsEmitted).toBe(0);
    hook({ level: 30, event: 'request_ok' });
    expect(getHealthSnapshot().logsEmitted).toBe(1);
  });

  it('increments logsEmitted once per record (not multiple times)', () => {
    makeCfg();
    const hook = makeWriteHook();
    hook({ level: 30, event: 'first' });
    hook({ level: 30, event: 'second' });
    hook({ level: 30, event: 'third' });
    expect(getHealthSnapshot().logsEmitted).toBe(3);
  });

  it('increments logsEmitted for schema-annotated records (not dropped)', () => {
    makeCfg({ strictSchema: true });
    const hook = makeWriteHook();
    // Invalid event name — annotated with _schema_error but still emitted.
    // Cross-language standard: schema violations annotate, never drop.
    hook({ level: 30, event: 'invalid event name with spaces' });
    expect(getHealthSnapshot().logsEmitted).toBe(1);
  });
});

describe('makeWriteHook — sampling gate', () => {
  beforeEach(() => {
    _resetSamplingForTests();
    _resetConfig();
    _resetRootLogger();
    setupTelemetry({ serviceName: 'test-svc', logLevel: 'debug', captureToWindow: true });
    (window as unknown as Record<string, unknown>)['__pinoLogs'] = [];
  });

  afterEach(() => {
    _resetSamplingForTests();
  });

  it('drops log records when logs sampling rate is 0', () => {
    setSamplingPolicy('logs', { defaultRate: 0, overrides: {} });
    const hook = makeWriteHook();
    hook({ level: 30, message: 'should.be.dropped' });
    const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
    expect(logs).toHaveLength(0);
  });

  it('passes log records when logs sampling rate is 1', () => {
    setSamplingPolicy('logs', { defaultRate: 1, overrides: {} });
    const hook = makeWriteHook();
    hook({ level: 30, message: 'should.pass' });
    const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
    expect(logs).toHaveLength(1);
  });
});

describe('makeWriteHook — consent gate', () => {
  beforeEach(() => {
    resetConsentForTests();
    _resetHealthForTests();
    makeCfg();
  });

  afterEach(() => {
    resetConsentForTests();
  });

  it('drops log records when consent is NONE', () => {
    setConsentLevel('NONE');
    const before = getHealthSnapshot().logsEmitted;
    const hook = makeWriteHook();
    hook({ level: 30, message: 'should.be.dropped' });
    expect(getHealthSnapshot().logsEmitted).toBe(before);
  });
});

describe('makeWriteHook — backpressure gate', () => {
  beforeEach(() => {
    _resetBackpressureForTests();
    _resetHealthForTests();
    makeCfg();
  });

  afterEach(() => {
    _resetBackpressureForTests();
  });

  it('drops log records when the log queue is full', () => {
    setQueuePolicy({ maxLogs: 1 });
    const ticket = tryAcquire('logs');
    expect(ticket).not.toBeNull();
    const before = getHealthSnapshot().logsEmitted;
    const hook = makeWriteHook();
    hook({ level: 30, message: 'should.be.dropped.by.backpressure' });
    expect(getHealthSnapshot().logsEmitted).toBe(before);
    // ticket held intentionally — _resetBackpressureForTests() in afterEach will clean up
  });
});
