// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Targeted Stryker mutation-kill tests for config.ts — the pieces not
 * already covered by config.mutants.test.ts (which handles the isNodeLike
 * guard's LogicalOperator, _configVersion increments, and _validateConfig
 * error-message StringLiterals).
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { configFromEnv, redactConfig, setupTelemetryAsync, version } from '../src/config.js';
import { ConfigurationError } from '../src/exceptions.js';
import {
  _disablePropagationALSForTest,
  _resetPropagationForTests,
  _restorePropagationALSForTest,
  _setPropagationInitDoneForTest,
} from '../src/propagation.js';
import { resetTelemetryState } from '../src/testing.js';

afterEach(() => resetTelemetryState());

describe('setupTelemetryAsync — isNodeLike guard skips the ALS check on non-Node hosts', () => {
  it('does not await propagation init or throw when process.versions.node is absent', async () => {
    const savedAls = _disablePropagationALSForTest();
    const savedDone = _setPropagationInitDoneForTest(true);
    const savedVersions = Object.getOwnPropertyDescriptor(
      process,
      'versions',
    ) as PropertyDescriptor;
    Object.defineProperty(process, 'versions', {
      value: { v8: '12.0.0' },
      configurable: true,
    });
    try {
      // Real code: !_isNodeLike() is true (no `node` key) -> returns before the
      // ALS check, so fallback mode (which we forced above) never throws.
      await expect(setupTelemetryAsync()).resolves.toBeUndefined();
    } finally {
      Object.defineProperty(process, 'versions', savedVersions);
      _setPropagationInitDoneForTest(savedDone);
      _restorePropagationALSForTest(savedAls);
    }
  });

  it('treats a host with no process.versions object as non-Node', async () => {
    // The two clauses of the host-presence check are not interchangeable: with
    // `process.versions` absent, `&&` yields false (non-Node, return early)
    // while `||` yields true and the `.node` lookup dereferences undefined.
    const savedAls = _disablePropagationALSForTest();
    const savedDone = _setPropagationInitDoneForTest(true);
    const savedVersions = Object.getOwnPropertyDescriptor(
      process,
      'versions',
    ) as PropertyDescriptor;
    Object.defineProperty(process, 'versions', { value: undefined, configurable: true });
    try {
      await expect(setupTelemetryAsync()).resolves.toBeUndefined();
    } finally {
      Object.defineProperty(process, 'versions', savedVersions);
      _setPropagationInitDoneForTest(savedDone);
      _restorePropagationALSForTest(savedAls);
    }
  });

  it('still throws on a genuine Node host with ALS in fallback mode', async () => {
    const savedAls = _disablePropagationALSForTest();
    const savedDone = _setPropagationInitDoneForTest(true);
    try {
      await expect(setupTelemetryAsync()).rejects.toThrow(ConfigurationError);
    } finally {
      _setPropagationInitDoneForTest(savedDone);
      _restorePropagationALSForTest(savedAls);
    }
  });
});

describe('redactConfig — per-signal header/endpoint fields tolerate absence', () => {
  it('does not crash when a per-signal headers field is undefined', () => {
    const cfg = { ...configFromEnv(), otlpLogsHeaders: undefined };
    expect(() => redactConfig(cfg)).not.toThrow();
  });

  it('does not crash when a per-signal endpoint field is undefined', () => {
    const cfg = { ...configFromEnv(), otlpLogsEndpoint: undefined };
    const result = redactConfig(cfg);
    expect(result.otlpLogsEndpoint).toBeUndefined();
  });

  it('masks a per-signal headers field when present and non-empty', () => {
    const cfg = { ...configFromEnv(), otlpLogsHeaders: { 'x-api-key': 'super-secret-value' } };
    const result = redactConfig(cfg);
    expect(result.otlpLogsHeaders).toEqual({ 'x-api-key': 'supe****' });
  });
});

describe('_FALLBACK_MESSAGE — ALS-unavailable error text, from a fresh module', () => {
  // Module-level string const — a static mutant (see pretty.mutants.test.ts):
  // evaluated once at import, so a fresh import is required for Stryker to
  // attribute this test as covering it.
  it('setupTelemetryAsync rejects with the real fallback-mode explanation', async () => {
    vi.resetModules();
    const config = await import('../src/config.js');
    const propagation = await import('../src/propagation.js');
    const saved = propagation._disablePropagationALSForTest();
    const savedDone = propagation._setPropagationInitDoneForTest(true);
    try {
      await expect(config.setupTelemetryAsync()).rejects.toThrow(/AsyncLocalStorage unavailable/);
    } finally {
      propagation._setPropagationInitDoneForTest(savedDone);
      propagation._restorePropagationALSForTest(saved);
    }
  });
});

describe('version — package version string', () => {
  it('is a real semver-shaped string, not empty', async () => {
    // Fresh import so a StringLiteral "" mutant on the module-level const is
    // observed even though the module may already be cached by other tests.
    vi.resetModules();
    const mod = await import('../src/config.js');
    expect(mod.version).toMatch(/^\d+\.\d+\.\d+$/);
    expect(mod.version.length).toBeGreaterThan(0);
  });

  it('matches the currently-imported module value', () => {
    expect(version).toMatch(/^\d+\.\d+\.\d+$/);
  });
});

describe('_isNodeLike is load-bearing in setupTelemetryAsync', () => {
  it('throws on a Node runtime when ALS is genuinely unavailable', async () => {
    // The only observable difference between _isNodeLike() true and false is
    // this branch: on Node, setupTelemetryAsync awaits propagation init and
    // fails loud when ALS is missing; off Node it returns early and stays
    // silent. Every mutation that makes _isNodeLike() report false — including
    // breaking the `typeof process.versions === 'object'` literal — turns this
    // throw into a silent success.
    const saved = _disablePropagationALSForTest();
    _setPropagationInitDoneForTest(true);
    try {
      await expect(setupTelemetryAsync({ serviceName: 'node-like' })).rejects.toThrow(
        ConfigurationError,
      );
    } finally {
      _restorePropagationALSForTest(saved);
      _resetPropagationForTests();
    }
  });
});
