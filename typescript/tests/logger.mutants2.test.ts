// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Targeted Stryker mutation-kill tests for logger.ts — the pieces not
 * already covered by logger.mutants.test.ts (which handles CONSENT_LEVEL_MAP,
 * the _rootConfigVersion sentinel, and sampling-key composition).
 *
 * Covers:
 *   - LEVEL_MAP (L29-36): pino level number -> console method name.
 *   - applyLazyLoggerPoliciesFromEnv's version guard (L71): env sampling
 *     must NOT be reapplied once real setup has run.
 *
 * LEVEL_MAP and CONSENT_LEVEL_MAP are module-level object literals — static
 * mutants (see pretty.mutants.test.ts for the general rationale): they are
 * evaluated once at import time, before Stryker's per-test coverage switch
 * activates, so a test importing logger.js the normal (static) way is never
 * attributed as "covering" them even when its assertions would genuinely
 * fail under the mutation. `vi.resetModules()` + a dynamic import forces a
 * fresh evaluation inside the test's own tracked window.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { _resetConfig, setupTelemetry } from '../src/config.js';
import { _resetContext } from '../src/context.js';
import { resetConsentForTests } from '../src/consent.js';
import { _resetRootLogger, getLogger, makeWriteHook } from '../src/logger.js';
import { _resetSamplingForTests, getSamplingPolicy, setSamplingPolicy } from '../src/sampling.js';

function freshCfg(overrides?: Parameters<typeof setupTelemetry>[0]) {
  _resetConfig();
  _resetRootLogger();
  _resetContext();
  resetConsentForTests();
  _resetSamplingForTests();
  setupTelemetry({ serviceName: 'test-svc', logLevel: 'trace', ...overrides });
}

beforeEach(() => freshCfg());
afterEach(() => {
  _resetConfig();
  _resetRootLogger();
  _resetContext();
  resetConsentForTests();
  _resetSamplingForTests();
  vi.restoreAllMocks();
});

describe('LEVEL_MAP — pino level number to console method name', () => {
  it.each([
    [10, 'trace'],
    [20, 'debug'],
    [30, 'log'], // info maps to console.log, not console.info
    [40, 'warn'],
    [50, 'error'],
    [60, 'error'], // fatal also maps to console.error
  ])('level %i writes via console.%s', (pinoLevel, expectedMethod) => {
    const spy = vi.spyOn(console, expectedMethod as 'log').mockImplementation(() => undefined);
    try {
      const hook = makeWriteHook();
      hook({ level: pinoLevel, event: 'level-map-probe' });
      expect(spy).toHaveBeenCalled();
    } finally {
      spy.mockRestore();
    }
  });

  it('an unmapped level falls back to console.log, not console[undefined]', () => {
    const spy = vi.spyOn(console, 'log').mockImplementation(() => undefined);
    try {
      const hook = makeWriteHook();
      hook({ level: 999, event: 'unmapped-level-probe' });
      expect(spy).toHaveBeenCalled();
    } finally {
      spy.mockRestore();
    }
  });
});

describe('LEVEL_MAP — pino level number to console method name, from a fresh module', () => {
  it.each([
    [10, 'trace'],
    [20, 'debug'],
    [30, 'log'],
    [40, 'warn'],
    [50, 'error'],
    [60, 'error'],
  ])('level %i writes via console.%s', async (pinoLevel, expectedMethod) => {
    vi.resetModules();
    const logger = await import('../src/logger.js');
    const spy = vi.spyOn(console, expectedMethod as 'log').mockImplementation(() => undefined);
    try {
      const hook = logger.makeWriteHook();
      hook({ level: pinoLevel, event: 'level-map-fresh-probe' });
      expect(spy).toHaveBeenCalled();
    } finally {
      spy.mockRestore();
    }
  });
});

describe('CONSENT_LEVEL_MAP — pino level to consent label, from a fresh module', () => {
  it('MINIMAL consent allows level=50 (error) but drops level=30 (info)', async () => {
    vi.resetModules();
    const logger = await import('../src/logger.js');
    const consent = await import('../src/consent.js');
    consent.setConsentLevel('MINIMAL');
    try {
      const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
      logger.makeWriteHook()({ level: 50, event: 'fresh.err' });
      expect(errorSpy).toHaveBeenCalled();
      errorSpy.mockRestore();

      const logSpy = vi.spyOn(console, 'log').mockImplementation(() => undefined);
      logger.makeWriteHook()({ level: 30, event: 'fresh.info' });
      expect(logSpy).not.toHaveBeenCalled();
      logSpy.mockRestore();
    } finally {
      consent.resetConsentForTests();
    }
  });

  it.each([
    [10, 'trace'],
    [20, 'debug'],
    [30, 'info'],
    [40, 'warn'],
    [50, 'error'],
    [60, 'error'],
  ])('level %i resolves to consent label %s', async (pinoLevel, expectedLabel) => {
    vi.resetModules();
    const logger = await import('../src/logger.js');
    const consent = await import('../src/consent.js');
    const labelsSeen: Array<[string, string | undefined]> = [];
    const spy = vi
      .spyOn(consent, 'shouldAllow')
      .mockImplementation((signal: string, logLevel?: string): boolean => {
        labelsSeen.push([signal, logLevel]);
        return true;
      });
    try {
      logger.makeWriteHook()({ level: pinoLevel, event: 'fresh.level-mapping-probe' });
      const entry = labelsSeen.find(([sig]) => sig === 'logs');
      expect(entry).toBeDefined();
      const [, label] = entry as [string, string | undefined];
      expect(label).toBe(expectedLabel);
    } finally {
      spy.mockRestore();
    }
  });
});

describe('_rootConfigVersion — first getLogger() call, from a fresh module', () => {
  it('produces a functioning logger bound to the configured service', async () => {
    vi.resetModules();
    const logger = await import('../src/logger.js');
    const config = await import('../src/config.js');
    config.setupTelemetry({
      serviceName: 'fresh-sentinel-svc',
      logLevel: 'trace',
      captureToWindow: true,
    });
    (window as unknown as Record<string, unknown>)['__pinoLogs'] = [];

    const log = logger.getLogger('probe.fresh-sentinel');
    expect(log).toBeDefined();
    log.info({ event: 'fresh.sentinel.ok' }, 'fresh.sentinel.ok');

    const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
    expect(logs.length).toBeGreaterThan(0);
    const last = logs[logs.length - 1] as Record<string, unknown>;
    expect(last['service']).toBe('fresh-sentinel-svc');
  });
});

describe('lazy logger env policy — skipped once real setup has run', () => {
  it('does not reapply env sampling once config version is past zero', () => {
    setSamplingPolicy('logs', { defaultRate: 0.42 });
    vi.stubEnv('PROVIDE_SAMPLING_LOGS_RATE', '0');

    getLogger('lazy.env.post-setup');

    // If the version guard were forced open, this env var would clobber the
    // policy setupTelemetry() (in freshCfg, via beforeEach) already established.
    expect(getSamplingPolicy('logs').defaultRate).toBe(0.42);
    vi.unstubAllEnvs();
  });
});
