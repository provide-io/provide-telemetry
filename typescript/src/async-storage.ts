// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Shared AsyncLocalStorage acquisition for context.ts, tracing.ts and propagation.ts.
 *
 * Mirrors the CJS-sync-`require` / ESM-async-`import` dual path that
 * `propagation.ts` already proved out, and gives the other two modules the same
 * treatment. Before this existed, `context.ts` and `tracing.ts` acquired the
 * constructor with a bare `require('node:async_hooks')` at module scope. That
 * works under vitest and tsx (both CJS), and silently does nothing in the
 * published artifact: package.json declares `"type": "module"`, so `require` is
 * undefined there, the try/catch swallowed the ReferenceError, and every
 * consumer fell back to a single module-level store — concurrent requests
 * crossed each other's log context and trace IDs with no warning.
 *
 * Two rules follow from that, and both are enforced by tests:
 *
 *   1. No module-scope `await`. tsx's default CJS output rejects top-level
 *      await ("Top-level await is currently not supported with the cjs output
 *      format"), and every TS runtime/contract/behavioral probe launches via
 *      `npx tsx` (spec/parity_probe_support.py, spec/contract_probe_harness.py,
 *      spec/_runtime_probe.py) — a regression breaks TypeScript parity in CI.
 *      `propagation.module-scope-await.test.ts` scans this file's AST for it.
 *   2. Acquisition must be retried, not cached once at import time. On the ESM
 *      path the constructor only lands after the fire-and-forget dynamic import
 *      settles, which is strictly after every importing module finished
 *      evaluating. A holder that resolved once at module scope would pin `null`
 *      forever — the exact bug above, moved rather than fixed. `ScopedStorage`
 *      re-attempts on each miss, so the first call after the import settles
 *      gets a live store.
 */

/** The slice of Node's AsyncLocalStorage this package actually uses. */
export type AsyncLocalStorageLike<T> = {
  getStore(): T | undefined;
  run<R>(store: T, fn: () => R): R;
  enterWith(store: T): void;
};

type AlsConstructor = new <T>() => AsyncLocalStorageLike<T>;

let _AlsConstructor: AlsConstructor | null = null;
// Flips to true once acquisition reaches a definitive state (constructor found,
// OR confirmed unavailable). Callers like setupTelemetry use it to tell "still
// racing, defer the check" from "settled, act on it".
// Stryker disable next-line BooleanLiteral
let _initDone = false;
let _initPromise: Promise<void> = Promise.resolve();

// Stryker disable all: the runtime-detection IIFE below runs once at import
// time, under whichever module system loaded this file. Every mutant of its
// guards is therefore unkillable from the vitest harness by construction, not
// by omission: the CJS branch always wins there and returns, so nothing after
// it ever executes and no assertion can distinguish a flipped `typeof` check.
// Killing them would need one Stryker run per module system, which Stryker
// cannot express. What the guards do is instead verified where it is
// observable — by ci/verify-npm-consumer-package.sh against the packed ESM
// tarball, and by the tsx-launched parity probes. Everything downstream of
// acquisition (createAsyncLocalStorage, createScopedStorage, the init flags)
// stays fully mutated; the exemption stops at the closing `restore all`.
//
// Four load environments must be supported, in this order:
//   1. CJS Node (tsx default, transpiled CJS bundles): `require` is defined;
//      load synchronously, no await needed.
//   2. ESM Node >= 20.16 / 22.3 (the published artifact, .mjs entrypoints):
//      `require` is undefined, but `process.getBuiltinModule` resolves builtins
//      synchronously. This branch is what makes the ESM path race-free —
//      see the note below on why the async import alone is not enough.
//   3. ESM Node < 20.16 (package.json still allows >= 18): fire off an async
//      import WITHOUT awaiting it at module scope. A caller that asks before it
//      settles gets `null` and uses its own no-ALS fallback for that call.
//   4. Browsers / Workers / Deno: no path resolves `node:async_hooks`;
//      `_AlsConstructor` stays null permanently — the fallback is the answer,
//      not a race.
//
// Why (2) is load-bearing and not just an optimization: the racing window in
// (3) is not "tiny in practice", it is the common case. A consumer that does
// `const t = await import('@provide-io/telemetry')` and immediately serves a
// request runs before the fire-and-forget import of node:async_hooks settles,
// so the very first requests — the ones a smoke test looks at — silently share
// one module-level store. Measured directly against the packed tarball: with
// only branch (3), two concurrent runWithContext calls both observed
// `undefined`. Branch (2) makes the constructor available during module
// evaluation, exactly as the CJS require does.
/* v8 ignore start */
// Behavior is exercised end-to-end rather than by line coverage:
//   * the vitest loader hits the CJS sync-require branch;
//   * tsx-as-ESM (every TS example, every parity probe) and the packed-artifact
//     probe in ci/verify-npm-consumer-package.sh hit the getBuiltinModule branch;
//   * Node < 20.16 hits the async import;
//   * browsers/workers hit the catch on the require attempt.
// No single test loader can enter all four, so the IIFE is excluded here and
// correctness is asserted through the observable downstream state
// (isAsyncStorageInitDone, ScopedStorage.get) which is fully covered, plus the
// packed-artifact probe in CI.
(function initAsyncStorage(): void {
  try {
    if (typeof require === 'function') {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const mod = require('node:async_hooks') as { AsyncLocalStorage: AlsConstructor };
      _AlsConstructor = mod.AsyncLocalStorage;
      _initDone = true;
      return;
    }
    if (typeof process !== 'undefined' && typeof process.getBuiltinModule === 'function') {
      const mod = process.getBuiltinModule('node:async_hooks') as unknown as {
        AsyncLocalStorage: AlsConstructor;
      };
      _AlsConstructor = mod.AsyncLocalStorage;
      _initDone = true;
      return;
    }
  } catch {
    // A sync path existed but threw (e.g. a browserified bundle where `require`
    // is defined but cannot resolve builtins) — fall through to the async
    // import rather than giving up on ALS entirely.
  }
  _initPromise = (async () => {
    try {
      const mod = (await import('node:async_hooks')) as { AsyncLocalStorage: AlsConstructor };
      _AlsConstructor = mod.AsyncLocalStorage;
    } catch {
      // node:async_hooks unresolvable — leave _AlsConstructor null.
    } finally {
      _initDone = true;
    }
  })();
})();
/* v8 ignore stop */
// Stryker restore all

/**
 * Resolves once acquisition has settled — either a constructor was found or
 * `node:async_hooks` was confirmed unresolvable.
 *
 * Always-resolved on the CJS path; awaits the dynamic import on the ESM path.
 */
export function awaitAsyncStorageInit(): Promise<void> {
  return _initPromise;
}

/** True once acquisition has reached a definitive state. */
export function isAsyncStorageInitDone(): boolean {
  return _initDone;
}

/**
 * A fresh AsyncLocalStorage-backed store, or `null` when `node:async_hooks` is
 * unavailable or has not resolved yet. Callers must keep a no-ALS fallback for
 * the `null` case; prefer {@link createScopedStorage}, which handles the retry.
 */
export function createAsyncLocalStorage<T>(): AsyncLocalStorageLike<T> | null {
  return _AlsConstructor ? new _AlsConstructor<T>() : null;
}

/**
 * A lazily-acquired AsyncLocalStorage holder with the test seams the three
 * call sites need.
 */
export type ScopedStorage<T> = {
  /** The live store, or `null` when ALS is unavailable/unsettled/suppressed. */
  get(): AsyncLocalStorageLike<T> | null;
  /** Drop the instance so the next `get()` builds a fresh one, and un-suppress. */
  reset(): void;
  /** Force `get()` to return `null`, exercising the fallback path. Returns what it replaced. */
  suppress(): AsyncLocalStorageLike<T> | null;
  /** Undo `suppress()`, reinstating the given instance. */
  restore(saved: AsyncLocalStorageLike<T> | null): void;
};

/**
 * Creates a holder that acquires its AsyncLocalStorage on first use and
 * re-attempts on every miss.
 *
 * The retry is the whole point: on the ESM path `createAsyncLocalStorage()`
 * returns `null` for as long as the dynamic import is in flight, so a holder
 * that resolved eagerly at module scope would never see the constructor land.
 */
export function createScopedStorage<T>(): ScopedStorage<T> {
  let instance: AsyncLocalStorageLike<T> | null = null;
  let suppressed = false;

  function get(): AsyncLocalStorageLike<T> | null {
    if (suppressed) return null;
    if (instance === null) instance = createAsyncLocalStorage<T>();
    return instance;
  }

  return {
    get,
    reset(): void {
      suppressed = false;
      instance = null;
    },
    suppress(): AsyncLocalStorageLike<T> | null {
      const prev = get();
      suppressed = true;
      return prev;
    },
    restore(saved: AsyncLocalStorageLike<T> | null): void {
      suppressed = false;
      instance = saved;
    },
  };
}

/**
 * Override the init-done flag for testing, returning the previous value.
 *
 * Used to exercise setupTelemetry's deferred-check branch, which fires only
 * while init is still racing — a state unit tests cannot reach naturally
 * because module-level init has long since settled by the time they run.
 */
export function _setAsyncStorageInitDoneForTest(done: boolean): boolean {
  const prev = _initDone;
  _initDone = done;
  return prev;
}

/**
 * Override the acquired constructor for testing, returning the previous value.
 *
 * This is the seam for the no-ALS environments — browsers, Workers, Deno — that
 * a Node test runner cannot otherwise enter: `require('node:async_hooks')`
 * always resolves there, so the fallback branches every call site carries would
 * be permanently unreachable and could only be covered by suppressing the
 * coverage check. Passing `null` makes them genuinely executable instead.
 */
export function _setAsyncStorageConstructorForTest(
  ctor: AlsConstructor | null,
): AlsConstructor | null {
  const prev = _AlsConstructor;
  _AlsConstructor = ctor;
  return prev;
}
