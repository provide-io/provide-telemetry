// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * PROVIDE_CONSENT_LEVEL fail-closed semantics.
 *
 * An unset or blank variable is a no-op. A recognised value is applied. A set,
 * non-empty, unrecognised value is an opt-out the operator misspelled, so it
 * fails closed to NONE and warns once per process, naming the bad value.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { _resetConfig, setupTelemetry } from '../src/config.js';
import {
  getConsentLevel,
  loadConsentFromEnv,
  resetConsentForTests,
  setConsentLevel,
} from '../src/consent.js';
import { _resetRootLogger, getLogger } from '../src/logger.js';
import { _resetSamplingForTests } from '../src/sampling.js';

const ENV = 'PROVIDE_CONSENT_LEVEL';

function expectedWarning(raw: string): string {
  return (
    `[provide-telemetry] PROVIDE_CONSENT_LEVEL="${raw}" is not one of ` +
    'FULL, FUNCTIONAL, MINIMAL, NONE; consent set to NONE (fail-closed)'
  );
}

let warnSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  resetConsentForTests();
  delete process.env[ENV];
  warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
  delete process.env[ENV];
  resetConsentForTests();
});

describe('loadConsentFromEnv fails closed on an unrecognised value', () => {
  it('an invalid value sets consent to NONE', () => {
    process.env[ENV] = 'NOEN';
    loadConsentFromEnv();
    expect(getConsentLevel()).toBe('NONE');
  });

  it('an invalid value overrides a programmatically-set FULL', () => {
    setConsentLevel('FULL');
    process.env[ENV] = 'yes';
    loadConsentFromEnv();
    expect(getConsentLevel()).toBe('NONE');
  });

  it('warns exactly once with the exact text, naming the raw untrimmed value', () => {
    process.env[ENV] = '  noen ';
    loadConsentFromEnv();
    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(warnSpy).toHaveBeenCalledWith(
      '[provide-telemetry] PROVIDE_CONSENT_LEVEL="  noen " is not one of FULL, FUNCTIONAL, MINIMAL, NONE; consent set to NONE (fail-closed)',
    );
    expect(warnSpy.mock.calls[0]).toHaveLength(1);
    expect(getConsentLevel()).toBe('NONE');
  });

  it('two invalid loads warn once; the second still fails closed over a FULL set between them', () => {
    process.env[ENV] = 'BOGUS';
    loadConsentFromEnv();
    expect(getConsentLevel()).toBe('NONE');
    expect(warnSpy).toHaveBeenCalledTimes(1);

    setConsentLevel('FULL');
    loadConsentFromEnv();
    expect(getConsentLevel()).toBe('NONE');
    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(warnSpy).toHaveBeenNthCalledWith(1, expectedWarning('BOGUS'));
  });

  it('resetConsentForTests re-arms the once-per-process warning', () => {
    process.env[ENV] = 'BOGUS';
    loadConsentFromEnv();
    expect(warnSpy).toHaveBeenCalledTimes(1);

    resetConsentForTests();
    expect(getConsentLevel()).toBe('FULL');
    loadConsentFromEnv();
    expect(warnSpy).toHaveBeenCalledTimes(2);
    expect(warnSpy).toHaveBeenNthCalledWith(2, expectedWarning('BOGUS'));
    expect(getConsentLevel()).toBe('NONE');
  });

  it('an empty value is blank, not invalid: level untouched, no warning', () => {
    setConsentLevel('MINIMAL');
    process.env[ENV] = '';
    loadConsentFromEnv();
    expect(getConsentLevel()).toBe('MINIMAL');
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it('a whitespace-only value is blank, not invalid: level untouched, no warning', () => {
    setConsentLevel('MINIMAL');
    process.env[ENV] = '  \t ';
    loadConsentFromEnv();
    expect(getConsentLevel()).toBe('MINIMAL');
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it('a recognised value with padding and lowercase is applied without a warning', () => {
    setConsentLevel('NONE');
    process.env[ENV] = ' functional ';
    loadConsentFromEnv();
    expect(getConsentLevel()).toBe('FUNCTIONAL');
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it('a freshly loaded module warns on its first invalid load without any reset', async () => {
    vi.resetModules();
    const fresh = await import('../src/consent.js');
    process.env[ENV] = 'NOEN';
    fresh.loadConsentFromEnv();
    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(warnSpy).toHaveBeenCalledWith(expectedWarning('NOEN'));
    expect(fresh.getConsentLevel()).toBe('NONE');
  });

  it('a freshly loaded module recognises every level, so a typo in the table cannot fail closed', async () => {
    // The fresh import re-evaluates the module-level level table under test,
    // which is the only place a mutated table would be observable.
    vi.resetModules();
    const fresh = await import('../src/consent.js');
    for (const level of ['full', 'functional', 'minimal', 'none'] as const) {
      process.env[ENV] = ` ${level} `;
      fresh.loadConsentFromEnv();
      expect(fresh.getConsentLevel()).toBe(level.toUpperCase());
    }
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it('an unset variable is a no-op and does not warn', () => {
    setConsentLevel('MINIMAL');
    loadConsentFromEnv();
    expect(getConsentLevel()).toBe('MINIMAL');
    expect(warnSpy).not.toHaveBeenCalled();
  });
});

describe('fail-closed reaches both loader call sites', () => {
  beforeEach(() => {
    _resetConfig();
    _resetRootLogger();
    _resetSamplingForTests();
  });

  afterEach(() => {
    _resetRootLogger();
    _resetConfig();
    _resetSamplingForTests();
  });

  it('setupTelemetry with an invalid value fails closed to NONE and warns', () => {
    setConsentLevel('FULL');
    process.env[ENV] = 'NOEN';
    setupTelemetry({ serviceName: 'svc' });
    expect(getConsentLevel()).toBe('NONE');
    expect(warnSpy).toHaveBeenCalledWith(expectedWarning('NOEN'));
  });

  it('the lazy getLogger path (no setup) with an invalid value fails closed to NONE and warns', () => {
    setConsentLevel('FULL');
    process.env[ENV] = 'NOEN';
    getLogger('consent.lazy.invalid');
    expect(getConsentLevel()).toBe('NONE');
    expect(warnSpy).toHaveBeenCalledWith(expectedWarning('NOEN'));
  });
});
