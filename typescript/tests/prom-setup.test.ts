// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// @vitest-environment node

/** Loading and driving the listener from setup: the paths that never reach a socket. */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFAULTS, type TelemetryConfig } from '../src/config.js';
import { _resetHealthForTests, getHealthSnapshot, setSetupError } from '../src/health.js';
import {
  _setListenerLoaderForTests,
  LISTENER_ERROR_PREFIX,
  prometheusListenerAddress,
  stopPrometheusListener,
  syncPrometheusListener,
  type ListenerModule,
} from '../src/prom-setup.js';

const LISTEN: TelemetryConfig = {
  ...DEFAULTS,
  metricsExporters: ['prometheus'],
  prometheusListen: 'true',
  prometheusPort: 0,
};

function fakeModule(): ListenerModule & { calls: unknown[][] } {
  const calls: unknown[][] = [];
  return {
    calls,
    syncListener: async (settings, enabled, report) => {
      calls.push(['sync', settings, enabled]);
      if (settings.prometheusPath === '/fail') report('prometheus listener: nope');
    },
    stopListener: async () => {
      calls.push(['stop']);
    },
    listenerAddress: () => ({ host: '127.0.0.1', port: 1 }),
  };
}

beforeEach(() => {
  _resetHealthForTests();
  vi.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(async () => {
  await stopPrometheusListener();
  _setListenerLoaderForTests();
  _resetHealthForTests();
  vi.restoreAllMocks();
});

describe('syncPrometheusListener', () => {
  it('does not load the listener when none is wanted and none was loaded', async () => {
    const loader = vi.fn(async () => fakeModule());
    _setListenerLoaderForTests(loader);
    await syncPrometheusListener(DEFAULTS);
    expect(loader).not.toHaveBeenCalled();
    expect(prometheusListenerAddress()).toBeUndefined();
    await stopPrometheusListener();
  });

  it('loads it once, then forwards every sync, enabled or not', async () => {
    const module = fakeModule();
    const loader = vi.fn(async () => module);
    _setListenerLoaderForTests(loader);
    await syncPrometheusListener(LISTEN);
    await syncPrometheusListener(DEFAULTS);
    expect(loader).toHaveBeenCalledTimes(1);
    expect(module.calls).toEqual([
      ['sync', LISTEN, true],
      ['sync', DEFAULTS, false],
    ]);
    expect(prometheusListenerAddress()).toEqual({ host: '127.0.0.1', port: 1 });
    await stopPrometheusListener();
    expect(module.calls[module.calls.length - 1]).toEqual(['stop']);
  });

  it('records what the listener reports, without logging it a second time', async () => {
    _setListenerLoaderForTests(async () => fakeModule());
    await syncPrometheusListener({ ...LISTEN, prometheusPath: '/fail' });
    expect(getHealthSnapshot().setupError).toBe('prometheus listener: nope');
    expect(console.warn).not.toHaveBeenCalled();
    await syncPrometheusListener(LISTEN);
    expect(getHealthSnapshot().setupError).toBeNull();
  });

  it('a listener that cannot be loaded is reported, never thrown', async () => {
    _setListenerLoaderForTests(async () => {
      throw new Error('cannot load');
    });
    await syncPrometheusListener(LISTEN);
    const message = `${LISTENER_ERROR_PREFIX}Error: cannot load`;
    expect(getHealthSnapshot().setupError).toBe(message);
    expect(console.warn).toHaveBeenCalledWith(
      `[provide/telemetry] metrics.prometheus_listener.failed: ${message}`,
    );
  });

  it('outside Node it is reported and nothing is loaded', async () => {
    const loader = vi.fn(async () => fakeModule());
    _setListenerLoaderForTests(loader);
    const saved = Object.getOwnPropertyDescriptor(process, 'versions') as PropertyDescriptor;
    Object.defineProperty(process, 'versions', { value: { v8: '12.0.0' }, configurable: true });
    try {
      await syncPrometheusListener(LISTEN);
    } finally {
      Object.defineProperty(process, 'versions', saved);
    }
    expect(loader).not.toHaveBeenCalled();
    expect(getHealthSnapshot().setupError).toBe('prometheus listener: requires Node.js');
  });

  it('clears only its own stale error', async () => {
    _setListenerLoaderForTests(async () => fakeModule());
    setSetupError('prometheus listener: old');
    await syncPrometheusListener(DEFAULTS);
    expect(getHealthSnapshot().setupError).toBeNull();
    setSetupError('prometheus listenerless');
    await syncPrometheusListener(DEFAULTS);
    expect(getHealthSnapshot().setupError).toBe('prometheus listenerless');
    expect(LISTENER_ERROR_PREFIX).toBe('prometheus listener: ');
  });

  it('the real loader finds the listener module', async () => {
    await syncPrometheusListener(LISTEN);
    expect(prometheusListenerAddress()?.host).toBe('127.0.0.1');
  });
});
