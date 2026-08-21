// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

/**
 * Node async-context installation, made observable.
 *
 * `startActiveSpan` only propagates across `await` boundaries when an
 * AsyncLocalStorage context manager is registered. Installing it used to be a
 * bare try/catch labelled "Not a Node.js environment or peer dep not installed
 * — skip silently", which collapsed three different situations into one: a
 * browser build where no context manager is wanted, a Node process missing the
 * peer dependency, and a Node process where installation genuinely failed. The
 * first is a supported configuration and should stay quiet. The other two
 * produce spans with no parent, which reads as a tracing bug rather than a
 * setup problem.
 *
 * Failing here is never fatal — signal export works without context
 * propagation — so this reports rather than throws.
 */

export const CONTEXT_MANAGER_MESSAGE =
  'AsyncLocalStorage context manager unavailable: spans will not propagate across ' +
  'await boundaries. Install @opentelemetry/context-async-hooks (peer dependency) ' +
  'in this Node application.';

export type ContextManagerOutcome =
  | 'installed'
  | 'unsupported-runtime'
  | 'module-missing'
  | 'install-failed';

export interface ContextManagerDeps {
  isNode: () => boolean;
  importHooks: () => Promise<unknown>;
  importApi: () => Promise<unknown>;
  warn: (message: string) => void;
  setSetupError: (message: string | null) => void;
  readSetupError: () => string | null;
}

let _warned = false;

/** Test seam: the one-time warning latch is module state. */
export function _resetContextManagerWarningForTests(): void {
  _warned = false;
}

function _isModuleMissing(error: unknown): boolean {
  const code = (error as { code?: unknown } | null)?.code;
  // ESM reports ERR_MODULE_NOT_FOUND; a CommonJS consumer reports MODULE_NOT_FOUND.
  return code === 'ERR_MODULE_NOT_FOUND' || code === 'MODULE_NOT_FOUND';
}

function _report(deps: ContextManagerDeps): void {
  deps.setSetupError(CONTEXT_MANAGER_MESSAGE);
  if (!_warned) {
    _warned = true;
    deps.warn(`[provide-telemetry] ${CONTEXT_MANAGER_MESSAGE}`);
  }
}

export async function installContextManager(
  deps: ContextManagerDeps,
): Promise<ContextManagerOutcome> {
  // A browser or edge build has no AsyncLocalStorage and is not meant to. That
  // is a supported configuration, not a degradation, so it stays silent.
  if (!deps.isNode()) return 'unsupported-runtime';

  let hooks: unknown;
  try {
    hooks = await deps.importHooks();
  } catch (error: unknown) {
    _report(deps);
    return _isModuleMissing(error) ? 'module-missing' : 'install-failed';
  }

  try {
    const api = (await deps.importApi()) as {
      context: { setGlobalContextManager: (manager: unknown) => void };
    };
    const Ctor = (
      hooks as { AsyncLocalStorageContextManager: new () => { enable: () => unknown } }
    ).AsyncLocalStorageContextManager;
    const manager = new Ctor();
    manager.enable();
    api.context.setGlobalContextManager(manager);
  } catch {
    _report(deps);
    return 'install-failed';
  }

  // Clear only our own message. An unrelated setup error — a rejected config
  // policy, an AsyncLocalStorage fallback — belongs to whoever recorded it.
  if (deps.readSetupError() === CONTEXT_MANAGER_MESSAGE) deps.setSetupError(null);
  return 'installed';
}
