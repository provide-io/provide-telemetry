// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { beforeEach, describe, expect, test, vi } from 'vitest';

import {
  type ConsentLevel,
  getConsentLevel,
  loadConsentFromEnv,
  resetConsentForTests,
  setConsentLevel,
  shouldAllow,
} from '../src/consent.js';

beforeEach(() => {
  resetConsentForTests();
  delete process.env['PROVIDE_CONSENT_LEVEL'];
});

describe('ConsentLevel defaults', () => {
  test('default consent is FULL', () => {
    expect(getConsentLevel()).toBe('FULL');
  });
});

describe('ConsentLevel.FULL', () => {
  beforeEach(() => setConsentLevel('FULL'));

  test('allows logs at any level', () => {
    expect(shouldAllow('logs', 'DEBUG')).toBe(true);
    expect(shouldAllow('logs', 'INFO')).toBe(true);
    expect(shouldAllow('logs', 'WARNING')).toBe(true);
    expect(shouldAllow('logs', 'ERROR')).toBe(true);
  });

  test('allows traces', () => {
    expect(shouldAllow('traces')).toBe(true);
  });

  test('allows metrics', () => {
    expect(shouldAllow('metrics')).toBe(true);
  });

  test('allows context', () => {
    expect(shouldAllow('context')).toBe(true);
  });
});

describe('ConsentLevel.NONE', () => {
  beforeEach(() => setConsentLevel('NONE'));

  test('blocks all signals', () => {
    expect(shouldAllow('logs', 'ERROR')).toBe(false);
    expect(shouldAllow('traces')).toBe(false);
    expect(shouldAllow('metrics')).toBe(false);
    expect(shouldAllow('context')).toBe(false);
  });
});

describe('ConsentLevel.FUNCTIONAL', () => {
  beforeEach(() => setConsentLevel('FUNCTIONAL'));

  test('blocks logs below WARNING', () => {
    expect(shouldAllow('logs', 'DEBUG')).toBe(false);
    expect(shouldAllow('logs', 'INFO')).toBe(false);
  });

  test('allows logs at WARNING and above', () => {
    expect(shouldAllow('logs', 'WARNING')).toBe(true);
    expect(shouldAllow('logs', 'ERROR')).toBe(true);
    expect(shouldAllow('logs', 'CRITICAL')).toBe(true);
  });

  test('allows logs at WARN (alias)', () => {
    expect(shouldAllow('logs', 'WARN')).toBe(true);
  });

  test('allows traces', () => {
    expect(shouldAllow('traces')).toBe(true);
  });

  test('allows metrics', () => {
    expect(shouldAllow('metrics')).toBe(true);
  });

  test('blocks context', () => {
    expect(shouldAllow('context')).toBe(false);
  });

  test('allows unknown signals', () => {
    expect(shouldAllow('custom_signal')).toBe(true);
  });

  test('blocks logs with no log level', () => {
    expect(shouldAllow('logs')).toBe(false);
    expect(shouldAllow('logs', undefined)).toBe(false);
  });
});

describe('ConsentLevel.MINIMAL', () => {
  beforeEach(() => setConsentLevel('MINIMAL'));

  test('blocks logs below ERROR', () => {
    expect(shouldAllow('logs', 'DEBUG')).toBe(false);
    expect(shouldAllow('logs', 'INFO')).toBe(false);
    expect(shouldAllow('logs', 'WARNING')).toBe(false);
  });

  test('allows logs at ERROR and above', () => {
    expect(shouldAllow('logs', 'ERROR')).toBe(true);
    expect(shouldAllow('logs', 'CRITICAL')).toBe(true);
  });

  test('blocks traces even with ERROR-level logLevel argument', () => {
    expect(shouldAllow('traces', 'ERROR')).toBe(false);
  });

  test('blocks traces', () => {
    expect(shouldAllow('traces')).toBe(false);
  });

  test('blocks metrics even with ERROR-level logLevel argument', () => {
    expect(shouldAllow('metrics', 'ERROR')).toBe(false);
  });

  test('blocks metrics', () => {
    expect(shouldAllow('metrics')).toBe(false);
  });

  test('blocks context', () => {
    expect(shouldAllow('context')).toBe(false);
  });

  test('blocks unknown signals', () => {
    expect(shouldAllow('custom_signal')).toBe(false);
  });

  test('blocks logs with no log level', () => {
    expect(shouldAllow('logs')).toBe(false);
    expect(shouldAllow('logs', undefined)).toBe(false);
  });
});

describe('setConsentLevel / getConsentLevel', () => {
  test('set and get round-trip', () => {
    const levels: ConsentLevel[] = ['FULL', 'FUNCTIONAL', 'MINIMAL', 'NONE'];
    for (const level of levels) {
      setConsentLevel(level);
      expect(getConsentLevel()).toBe(level);
    }
  });
});

describe('loadConsentFromEnv', () => {
  test('loads FULL from env (overriding non-FULL state)', () => {
    setConsentLevel('NONE');
    process.env['PROVIDE_CONSENT_LEVEL'] = 'FULL';
    loadConsentFromEnv();
    expect(getConsentLevel()).toBe('FULL');
  });

  test('loads FUNCTIONAL from env', () => {
    process.env['PROVIDE_CONSENT_LEVEL'] = 'FUNCTIONAL';
    loadConsentFromEnv();
    expect(getConsentLevel()).toBe('FUNCTIONAL');
  });

  test('loads MINIMAL from env', () => {
    process.env['PROVIDE_CONSENT_LEVEL'] = 'MINIMAL';
    loadConsentFromEnv();
    expect(getConsentLevel()).toBe('MINIMAL');
  });

  test('loads NONE from env', () => {
    process.env['PROVIDE_CONSENT_LEVEL'] = 'NONE';
    loadConsentFromEnv();
    expect(getConsentLevel()).toBe('NONE');
  });

  test('every valid value applies over any prior level', () => {
    const levels: ConsentLevel[] = ['FULL', 'FUNCTIONAL', 'MINIMAL', 'NONE'];
    for (const level of levels) {
      setConsentLevel(level === 'FULL' ? 'NONE' : 'FULL');
      process.env['PROVIDE_CONSENT_LEVEL'] = level;
      loadConsentFromEnv();
      expect(getConsentLevel()).toBe(level);
    }
  });

  test('an invalid env value fails closed to NONE, overriding the current level', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    try {
      setConsentLevel('MINIMAL');
      process.env['PROVIDE_CONSENT_LEVEL'] = 'BOGUS';
      loadConsentFromEnv();
      expect(getConsentLevel()).toBe('NONE');
      expect(warnSpy).toHaveBeenCalledTimes(1);
    } finally {
      warnSpy.mockRestore();
    }
  });

  test('leaves the default FULL in place when env is unset', () => {
    delete process.env['PROVIDE_CONSENT_LEVEL'];
    loadConsentFromEnv();
    expect(getConsentLevel()).toBe('FULL');
  });

  test('unset env leaves a programmatic level untouched (no reset to FULL)', () => {
    setConsentLevel('MINIMAL');
    delete process.env['PROVIDE_CONSENT_LEVEL'];
    loadConsentFromEnv();
    expect(getConsentLevel()).toBe('MINIMAL');
  });

  test('empty env value is blank, not invalid, and leaves the level untouched', () => {
    setConsentLevel('FUNCTIONAL');
    process.env['PROVIDE_CONSENT_LEVEL'] = '';
    loadConsentFromEnv();
    expect(getConsentLevel()).toBe('FUNCTIONAL');
  });

  test('handles lowercase env value', () => {
    process.env['PROVIDE_CONSENT_LEVEL'] = 'minimal';
    loadConsentFromEnv();
    expect(getConsentLevel()).toBe('MINIMAL');
  });

  test('handles env value with whitespace', () => {
    process.env['PROVIDE_CONSENT_LEVEL'] = '  NONE  ';
    loadConsentFromEnv();
    expect(getConsentLevel()).toBe('NONE');
  });

  test('reads nothing and leaves the level untouched when process is unavailable', () => {
    setConsentLevel('MINIMAL');
    process.env['PROVIDE_CONSENT_LEVEL'] = 'NONE';
    const realProcess = globalThis.process;
    // Simulate a browser bundle: `process` is not defined at all.
    vi.stubGlobal('process', undefined);
    try {
      loadConsentFromEnv();
      expect(getConsentLevel()).toBe('MINIMAL');
    } finally {
      vi.stubGlobal('process', realProcess);
      vi.unstubAllGlobals();
    }
  });

  test('swallows an env accessor that throws and leaves the level untouched', () => {
    setConsentLevel('MINIMAL');
    const realProcess = globalThis.process;
    const throwing = new Proxy(
      {},
      {
        get: () => {
          throw new Error('env unavailable');
        },
      },
    );
    vi.stubGlobal('process', { env: throwing });
    try {
      loadConsentFromEnv();
      expect(getConsentLevel()).toBe('MINIMAL');
    } finally {
      vi.stubGlobal('process', realProcess);
      vi.unstubAllGlobals();
    }
  });
});
