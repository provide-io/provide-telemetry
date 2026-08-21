// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  CONTEXT_MANAGER_MESSAGE,
  _resetContextManagerWarningForTests,
  installContextManager,
  type ContextManagerDeps,
} from '../src/otel-context-manager.js';

function deps(overrides: Partial<ContextManagerDeps> = {}): ContextManagerDeps {
  let stored: string | null = null;
  return {
    isNode: () => true,
    importHooks: async () => ({
      AsyncLocalStorageContextManager: class {
        enable() {
          return this;
        }
      },
    }),
    importApi: async () => ({ context: { setGlobalContextManager: () => undefined } }),
    warn: vi.fn(),
    setSetupError: (message) => {
      stored = message;
    },
    readSetupError: () => stored,
    ...overrides,
  };
}

beforeEach(() => _resetContextManagerWarningForTests());

describe('installContextManager', () => {
  it('installs the context manager on Node and records no error', async () => {
    const d = deps();
    await expect(installContextManager(d)).resolves.toBe('installed');
    expect(d.readSetupError()).toBeNull();
  });

  it('is silent on a non-Node runtime', async () => {
    const warn = vi.fn();
    const d = deps({
      isNode: () => false,
      importHooks: async () => {
        throw new Error('should not be called');
      },
      warn,
    });
    await expect(installContextManager(d)).resolves.toBe('unsupported-runtime');
    expect(d.readSetupError()).toBeNull();
    expect(warn).not.toHaveBeenCalled();
  });

  it('reports an actionable error when the peer dependency is missing on Node', async () => {
    const warn = vi.fn();
    const missing = Object.assign(new Error('Cannot find module'), {
      code: 'ERR_MODULE_NOT_FOUND',
    });
    const d = deps({
      importHooks: async () => {
        throw missing;
      },
      warn,
    });
    await expect(installContextManager(d)).resolves.toBe('module-missing');
    expect(d.readSetupError()).toBe(CONTEXT_MANAGER_MESSAGE);
    expect(warn).toHaveBeenCalledTimes(1);
    expect(vi.mocked(warn).mock.calls[0][0]).toContain('@opentelemetry/context-async-hooks');
  });

  it('recognises the CommonJS MODULE_NOT_FOUND code too', async () => {
    const missing = Object.assign(new Error('Cannot find module'), { code: 'MODULE_NOT_FOUND' });
    const d = deps({
      importHooks: async () => {
        throw missing;
      },
    });
    await expect(installContextManager(d)).resolves.toBe('module-missing');
  });

  // `throw null` and `throw 'string'` are legal JavaScript, and a rejected
  // dynamic import is not guaranteed to carry an Error. Reading `.code` off a
  // non-object must not itself throw — the optional chaining in
  // _isModuleMissing is load-bearing, not defensive decoration.
  it.each([null, undefined, 'a string', 42])(
    'treats a non-object rejection (%p) as a failed install, not a crash',
    async (thrown) => {
      const d = deps({
        importHooks: async () => {
          throw thrown;
        },
      });
      await expect(installContextManager(d)).resolves.toBe('install-failed');
      expect(d.readSetupError()).toBe(CONTEXT_MANAGER_MESSAGE);
    },
  );

  it('distinguishes an import that fails for another reason', async () => {
    const d = deps({
      importHooks: async () => {
        throw new Error('syntax error in dependency');
      },
    });
    await expect(installContextManager(d)).resolves.toBe('install-failed');
    expect(d.readSetupError()).toBe(CONTEXT_MANAGER_MESSAGE);
  });

  it('reports an actionable error when enable() throws on Node', async () => {
    const d = deps({
      importHooks: async () => ({
        AsyncLocalStorageContextManager: class {
          enable(): never {
            throw new Error('enable exploded');
          }
        },
      }),
    });
    await expect(installContextManager(d)).resolves.toBe('install-failed');
    expect(d.readSetupError()).toBe(CONTEXT_MANAGER_MESSAGE);
  });

  it('reports an actionable error when setGlobalContextManager throws', async () => {
    const d = deps({
      importApi: async () => ({
        context: {
          setGlobalContextManager: () => {
            throw new Error('registry locked');
          },
        },
      }),
    });
    await expect(installContextManager(d)).resolves.toBe('install-failed');
    expect(d.readSetupError()).toBe(CONTEXT_MANAGER_MESSAGE);
  });

  it('warns only once across repeated failures', async () => {
    const warn = vi.fn();
    const d = deps({
      importHooks: async () => {
        throw new Error('nope');
      },
      warn,
    });
    await installContextManager(d);
    await installContextManager(d);
    expect(warn).toHaveBeenCalledTimes(1);
  });

  it('clears its own prior message when a later attempt succeeds', async () => {
    let stored: string | null = CONTEXT_MANAGER_MESSAGE;
    const d = deps({
      setSetupError: (m) => {
        stored = m;
      },
      readSetupError: () => stored,
    });
    await installContextManager(d);
    expect(stored).toBeNull();
  });

  it('leaves an unrelated setup error alone when it succeeds', async () => {
    let stored: string | null = 'applyConfigPolicies failed: bad sample rate';
    const d = deps({
      setSetupError: (m) => {
        stored = m;
      },
      readSetupError: () => stored,
    });
    await installContextManager(d);
    expect(stored).toBe('applyConfigPolicies failed: bad sample rate');
  });

  it('surfaces through both getHealthSnapshot and getRuntimeStatus', async () => {
    const { getHealthSnapshot, setSetupError } = await import('../src/health.js');
    const { getRuntimeStatus } = await import('../src/runtime.js');
    setSetupError(CONTEXT_MANAGER_MESSAGE);
    expect(getHealthSnapshot().setupError).toBe(CONTEXT_MANAGER_MESSAGE);
    expect(getRuntimeStatus().setupError).toBe(CONTEXT_MANAGER_MESSAGE);
    setSetupError(null);
  });
});
