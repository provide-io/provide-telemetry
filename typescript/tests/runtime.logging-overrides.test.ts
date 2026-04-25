// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Parity: RuntimeOverrides.logging brings TypeScript in line with Python's
 * hot-reload contract (docs/API.md, docs/INTERNALS.md).  updateRuntimeConfig
 * and reloadRuntimeFromEnv must re-apply log level, format, and module levels
 * without a provider restart. Provider-changing fields are NOT affected.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { _resetConfig, setupTelemetry } from '../src/config';
import type { RuntimeOverrides } from '../src/config';
import { _resetContext } from '../src/context';
import { _resetRootLogger, getLogger } from '../src/logger';
import {
  _markProvidersRegistered,
  _resetRuntimeForTests,
  getRuntimeConfig,
  reloadRuntimeFromEnv,
  reconfigureTelemetry,
  updateRuntimeConfig,
} from '../src/runtime';

// Pull a fresh window.__pinoLogs per test to isolate captured output.
function resetCapture(): Record<string, unknown>[] {
  const w = window as unknown as Record<string, unknown>;
  const logs: Record<string, unknown>[] = [];
  w['__pinoLogs'] = logs;
  return logs;
}

async function flush(): Promise<void> {
  // pino's Node destination stream is async; give it a tick.
  await new Promise((r) => setTimeout(r, 10));
}

beforeEach(() => {
  _resetConfig();
  _resetRuntimeForTests();
  _resetContext();
  _resetRootLogger();
  setupTelemetry({
    serviceName: 'logging-ovr',
    logLevel: 'info',
    logFormat: 'json',
    captureToWindow: true,
    consoleOutput: false,
  });
});

afterEach(() => {
  _resetConfig();
  _resetRuntimeForTests();
  _resetContext();
  _resetRootLogger();
});

describe('RuntimeOverrides.logging — logLevel', () => {
  it('updateRuntimeConfig({ logging: { logLevel: "debug" } }) makes DEBUG logs appear that were previously dropped', async () => {
    // Sanity: with level=info, a .debug() call should NOT be captured.
    const beforeLogs = resetCapture();
    getLogger('my.mod').debug({ event: 'cache.miss.ok' }, 'before');
    await flush();
    expect(beforeLogs.some((l) => l['event'] === 'cache.miss.ok')).toBe(false);

    // Hot-reload: lift level to debug via the new logging override.
    updateRuntimeConfig({ logging: { logLevel: 'debug' } });
    _resetRootLogger(); // logger rebuild is triggered via config-version bump;
    //                      reset explicitly so this test exercises the visible
    //                      behaviour change regardless of stream caching.
    expect(getRuntimeConfig().logLevel).toBe('debug');

    const afterLogs = resetCapture();
    getLogger('my.mod').debug({ event: 'cache.miss.ok' }, 'after');
    await flush();
    expect(afterLogs.some((l) => l['event'] === 'cache.miss.ok')).toBe(true);
  });

  it('accepts empty logging override without error', () => {
    expect(() => updateRuntimeConfig({ logging: {} })).not.toThrow();
  });
});

describe('RuntimeOverrides.logging — logFormat', () => {
  it('updateRuntimeConfig({ logging: { logFormat: "pretty" } }) is reflected in runtime config', () => {
    updateRuntimeConfig({ logging: { logFormat: 'pretty' } });
    expect(getRuntimeConfig().logFormat).toBe('pretty');
  });

  it('updateRuntimeConfig({ logging: { logFormat: "json" } }) round-trips through getRuntimeConfig', () => {
    updateRuntimeConfig({ logging: { logFormat: 'json' } });
    expect(getRuntimeConfig().logFormat).toBe('json');
  });
});

describe('RuntimeOverrides.logging — logModuleLevels', () => {
  it('updateRuntimeConfig merges module-level overrides into the active config', async () => {
    updateRuntimeConfig({
      logging: { logModuleLevels: { 'provide.server': 'debug' } },
    });
    const cfg = getRuntimeConfig();
    expect(cfg.logModuleLevels).toEqual({ 'provide.server': 'debug' });

    _resetRootLogger();
    const logs = resetCapture();
    // 'provide.server.auth' longest-prefix-matches 'provide.server' → debug.
    getLogger('provide.server.auth').debug({ event: 'mod.lvl.match' });
    await flush();
    expect(logs.some((l) => l['event'] === 'mod.lvl.match')).toBe(true);
  });

  it('empty logModuleLevels overrides back to no module filtering', () => {
    updateRuntimeConfig({
      logging: { logModuleLevels: { 'foo.bar': 'debug' } },
    });
    expect(getRuntimeConfig().logModuleLevels).toEqual({ 'foo.bar': 'debug' });
    updateRuntimeConfig({ logging: { logModuleLevels: {} } });
    expect(getRuntimeConfig().logModuleLevels).toEqual({});
  });
});

describe('RuntimeOverrides.logging — other logging flags', () => {
  it('logIncludeTimestamp, logIncludeCaller, logSanitize, logCodeAttributes round-trip through the nested override', () => {
    updateRuntimeConfig({
      logging: {
        logIncludeTimestamp: false,
        logIncludeCaller: false,
        logSanitize: false,
        logCodeAttributes: true,
      },
    });
    const cfg = getRuntimeConfig();
    expect(cfg.logIncludeTimestamp).toBe(false);
    expect(cfg.logIncludeCaller).toBe(false);
    expect(cfg.logSanitize).toBe(false);
    expect(cfg.logCodeAttributes).toBe(true);
  });

  it('pretty renderer settings round-trip through the nested override', () => {
    updateRuntimeConfig({
      logging: {
        logPrettyKeyColor: 'bold',
        logPrettyValueColor: 'cyan',
        logPrettyFields: ['user_id', 'trace_id'],
      },
    });
    const cfg = getRuntimeConfig();
    expect(cfg.logPrettyKeyColor).toBe('bold');
    expect(cfg.logPrettyValueColor).toBe('cyan');
    expect(cfg.logPrettyFields).toEqual(['user_id', 'trace_id']);
  });
});

describe('RuntimeOverrides.logging — provider guardrails', () => {
  it('does NOT affect provider-changing fields (serviceName / otelEnabled / tracingEnabled / metricsEnabled / otlp*)', () => {
    setupTelemetry({
      serviceName: 'locked',
      otelEnabled: true,
      tracingEnabled: true,
      metricsEnabled: true,
      otlpEndpoint: 'http://locked:4318',
      logLevel: 'info',
    });
    updateRuntimeConfig({
      logging: {
        logLevel: 'debug',
        logFormat: 'pretty',
        logModuleLevels: { 'my.mod': 'trace' },
      },
    });
    const cfg = getRuntimeConfig();
    // Logging fields updated.
    expect(cfg.logLevel).toBe('debug');
    expect(cfg.logFormat).toBe('pretty');
    expect(cfg.logModuleLevels).toEqual({ 'my.mod': 'trace' });
    // Provider-changing fields unchanged.
    expect(cfg.serviceName).toBe('locked');
    expect(cfg.otelEnabled).toBe(true);
    expect(cfg.tracingEnabled).toBe(true);
    expect(cfg.metricsEnabled).toBe(true);
    expect(cfg.otlpEndpoint).toBe('http://locked:4318');
  });

  it('reconfigureTelemetry guardrails are unrelated to the logging hot-reload path', () => {
    reconfigureTelemetry({ serviceName: 'cold' });
    _markProvidersRegistered();
    // Provider-changing reconfigure throws after providers registered.
    expect(() => reconfigureTelemetry({ serviceName: 'different' })).toThrow(
      /provider-changing reconfiguration/,
    );
    // But hot logging override still works — it goes through
    // updateRuntimeConfig, not reconfigureTelemetry.
    expect(() => updateRuntimeConfig({ logging: { logLevel: 'debug' } })).not.toThrow();
    expect(getRuntimeConfig().logLevel).toBe('debug');
  });
});

describe('reloadRuntimeFromEnv — logging parity', () => {
  it('picks logging fields up from env vars', () => {
    updateRuntimeConfig({ logging: { logLevel: 'error' } });
    expect(getRuntimeConfig().logLevel).toBe('error');
    process.env['PROVIDE_LOG_LEVEL'] = 'debug';
    try {
      reloadRuntimeFromEnv();
      expect(getRuntimeConfig().logLevel).toBe('debug');
    } finally {
      delete process.env['PROVIDE_LOG_LEVEL'];
    }
  });

  it('picks pretty renderer settings up from env vars', () => {
    process.env['PROVIDE_LOG_PRETTY_KEY_COLOR'] = 'bold';
    process.env['PROVIDE_LOG_PRETTY_VALUE_COLOR'] = 'cyan';
    process.env['PROVIDE_LOG_PRETTY_FIELDS'] = 'user_id, trace_id';
    try {
      reloadRuntimeFromEnv();
      const cfg = getRuntimeConfig();
      expect(cfg.logPrettyKeyColor).toBe('bold');
      expect(cfg.logPrettyValueColor).toBe('cyan');
      expect(cfg.logPrettyFields).toEqual(['user_id', 'trace_id']);
    } finally {
      delete process.env['PROVIDE_LOG_PRETTY_KEY_COLOR'];
      delete process.env['PROVIDE_LOG_PRETTY_VALUE_COLOR'];
      delete process.env['PROVIDE_LOG_PRETTY_FIELDS'];
    }
  });

  it('picks logModuleLevels up from env vars', () => {
    process.env['PROVIDE_LOG_MODULE_LEVELS'] = 'provide.server=debug,asyncio=warning';
    try {
      reloadRuntimeFromEnv();
      const cfg = getRuntimeConfig();
      // Key format matches env var shape (lower-case level).
      expect(cfg.logModuleLevels).toMatchObject({
        'provide.server': expect.any(String),
        asyncio: expect.any(String),
      });
    } finally {
      delete process.env['PROVIDE_LOG_MODULE_LEVELS'];
    }
  });
});

describe('LoggingOverrides typing', () => {
  it('the exported type accepts only known logging fields', () => {
    // This is effectively a compile-time test — if the type drifts, tsc will
    // fail. The runtime assertion below is just to ensure the test runs.
    const overrides: RuntimeOverrides = {
      logging: {
        logLevel: 'debug',
        logFormat: 'json',
        logIncludeTimestamp: true,
        logIncludeCaller: true,
        logSanitize: true,
        logCodeAttributes: false,
        logModuleLevels: {},
        logPrettyKeyColor: 'bold',
        logPrettyValueColor: 'cyan',
        logPrettyFields: ['user_id'],
      },
    };
    expect(overrides.logging).toBeDefined();
  });
});
