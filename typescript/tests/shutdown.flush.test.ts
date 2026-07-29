// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * flushTelemetry — the drain half of shutdownTelemetry.
 *
 * Providers must be force-flushed and left installed, every provider must get
 * its attempt, and the result must report whether all of them made the deadline.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { _resetConfig, setupTelemetry } from '../src/config.js';
import { _resetRuntimeForTests, _storeRegisteredProviders } from '../src/runtime.js';
import { flushTelemetry } from '../src/shutdown.js';

function provider(onFlush?: () => Promise<void>): {
  calls: string[];
  provider: Record<string, unknown>;
} {
  const calls: string[] = [];
  return {
    calls,
    provider: {
      forceFlush: () => {
        calls.push('forceFlush');
        return onFlush ? onFlush() : Promise.resolve();
      },
      shutdown: () => {
        calls.push('shutdown');
        return Promise.resolve();
      },
    },
  };
}

beforeEach(() => {
  _resetRuntimeForTests();
  _resetConfig();
});
afterEach(() => {
  vi.restoreAllMocks();
  _resetRuntimeForTests();
  _resetConfig();
});

describe('flushTelemetry', () => {
  it('resolves true with nothing installed', async () => {
    await expect(flushTelemetry(50)).resolves.toBe(true);
  });

  it('flushes every provider without shutting any down', async () => {
    const a = provider();
    const b = provider();
    _storeRegisteredProviders([a.provider, b.provider]);

    await expect(flushTelemetry(50)).resolves.toBe(true);

    expect(a.calls).toEqual(['forceFlush']);
    expect(b.calls).toEqual(['forceFlush']);
  });

  it('treats a provider with no forceFlush as nothing to flush', async () => {
    _storeRegisteredProviders([{ shutdown: () => Promise.resolve() }]);
    await expect(flushTelemetry(50)).resolves.toBe(true);
  });

  it('resolves false and warns when a provider misses the deadline', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const slow = provider(() => new Promise<void>(() => {}));
    _storeRegisteredProviders([slow.provider]);

    await expect(flushTelemetry(20)).resolves.toBe(false);

    expect(warn).toHaveBeenCalledWith(expect.stringContaining('forceFlush exceeded 20ms deadline'));
  });

  it('still flushes the other providers when one misses the deadline', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    const slow = provider(() => new Promise<void>(() => {}));
    const fast = provider();
    _storeRegisteredProviders([slow.provider, fast.provider]);

    await expect(flushTelemetry(20)).resolves.toBe(false);

    expect(fast.calls).toEqual(['forceFlush']);
  });

  it('rejects when a forceFlush that arrived in time rejected', async () => {
    const broken = provider(() => Promise.reject(new Error('exporter down')));
    _storeRegisteredProviders([broken.provider]);

    await expect(flushTelemetry(50)).rejects.toThrow('exporter down');
  });

  it('defaults the deadline to the bounded-shutdown timeout', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    setupTelemetry({ exporterLogsShutdownTimeoutMs: 25 });
    const slow = provider(() => new Promise<void>(() => {}));
    _storeRegisteredProviders([slow.provider]);

    await expect(flushTelemetry()).resolves.toBe(false);

    expect(warn).toHaveBeenCalledWith(expect.stringContaining('exceeded 25ms deadline'));
  });

  it('leaves the providers registered so telemetry keeps working', async () => {
    const a = provider();
    _storeRegisteredProviders([a.provider]);

    await flushTelemetry(50);
    await flushTelemetry(50);

    expect(a.calls).toEqual(['forceFlush', 'forceFlush']);
  });
});
