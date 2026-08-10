// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * shutdownTelemetry — flushes and shuts down any OTEL providers registered by
 * registerOtelProviders. Safe to call before process exit or on hot-reload.
 *
 * Each provider's forceFlush+shutdown sequence is bounded by
 * `exporterLogsShutdownTimeoutMs` (env: `PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS`,
 * default 5s). When a provider's Promise hangs — e.g. the OTLP HTTP exporter
 * sitting in its internal retry loop against an unreachable endpoint — the
 * race resolves on the deadline and shutdownTelemetry returns instead of
 * hanging the caller. The abandoned Promise stays pending in the microtask
 * queue but no longer blocks the caller's flow.
 *
 * Uses Promise.allSettled so a failure in one provider's forceFlush/shutdown
 * does not prevent the others from draining.
 */

import { context, metrics, trace } from '@opentelemetry/api';
import { getConfig } from './config.js';
import { _clearProviderState } from './runtime.js';
import {
  _getProvidersBySignal,
  _getRegisteredProviders,
  _signalForProvider,
  type ShutdownableProvider,
  type SignalName,
} from './provider-registry.js';
import { _asyncBlockingRiskField, _incrementHealth } from './health.js';
import { _resetRootLogger } from './logger.js';
import { _resetOtelLogProviderForTests } from './otel-logs.js';
import { dynImportOtel } from './otel-dynimport.js';

async function disableInstalledOtelGlobals(): Promise<void> {
  trace.disable();
  metrics.disable();
  context.disable();
  try {
    const { logs } = await dynImportOtel('@opentelemetry/api-logs');
    logs.disable();
  } catch {
    // Optional peer dep not installed.
  }
}

/** Sentinel returned by the deadline race when `op` settled before the timer. */
const SETTLED = Symbol('settled');

/**
 * Race `op` against a timer. Returns `true` iff `op` settled (resolved or
 * rejected) before `timeoutMs` elapsed.
 *
 * The timer is `unref()`'d on Node so a pending deadline never blocks
 * process exit on its own, and is always cleared after the race so a
 * fast-resolving `op` doesn't leave a dangling timer behind.
 *
 * On timeout the underlying Promise is abandoned, not cancelled — JavaScript
 * has no general Promise cancellation primitive. For OTel exporters this is
 * acceptable because the hang lives on a background socket; the contract is
 * "shutdown returns by the deadline", not "all I/O is cancelled by the
 * deadline".
 */
async function raceWithDeadline(op: Promise<unknown>, timeoutMs: number): Promise<boolean> {
  // setTimeout returns synchronously, so `timer` is always defined by the
  // time the executor finishes — no undefined-guard needed at clearTimeout.
  let timer!: ReturnType<typeof setTimeout>;
  const timeoutPromise = new Promise<undefined>((resolve) => {
    timer = setTimeout(() => resolve(undefined), timeoutMs);
    // Stryker disable next-line OptionalChaining: setTimeout returns Timeout on
    // Node (has unref) and number on browsers (no unref); the optional call is
    // platform-conditional and equivalent in any single-runtime test env.
    (timer as { unref?: () => void }).unref?.();
  });
  // Map both fulfillment and rejection to the SETTLED sentinel so we can
  // distinguish "op finished" from "timer fired" via identity, regardless
  // of op's value or thrown error. Mutating either arrow to return undefined
  // makes raceWithDeadline incorrectly report a timeout even when op settled.
  const settled: Promise<typeof SETTLED> = op.then(
    () => SETTLED,
    () => SETTLED,
  );
  const result = await Promise.race([settled, timeoutPromise]);
  clearTimeout(timer);
  return result === SETTLED;
}

/**
 * Start a budget of `timeoutMs` now; each call returns what is left of it.
 *
 * Never returns a negative value: `setTimeout` treats one as 0, but a negative
 * delay reads as "already overdue" to anyone stepping through, and clamping
 * here keeps the two call sites honest.
 */
function deadlineRemaining(timeoutMs: number): () => number {
  const startedAt = Date.now();
  return () => Math.max(0, timeoutMs - (Date.now() - startedAt));
}

/**
 * How long a provider call may hold the event loop before it counts as having
 * blocked it.
 *
 * 50ms is the long-task threshold browsers and Node profilers use: under it a
 * stall is indistinguishable from ordinary scheduling noise; over it, timers,
 * I/O callbacks and request handlers are all visibly late.
 */
const LONG_TASK_MS = 50;

/**
 * Count a provider call that held the event loop, per signal.
 *
 * Node's reading of `async_blocking_risk_*`. There is no "am I on an event
 * loop?" question to ask here the way Python asks asyncio and .NET asks
 * `SynchronizationContext` — in Node the answer is always yes, every line of
 * this module already runs on the loop. What varies is whether a call *blocks*
 * it, and everything this module awaits yields. The provider calls do not:
 * `forceFlush()` and `shutdown()` are ordinary functions that run synchronously
 * until they return a Promise, and an OTLP exporter serializes its whole
 * pending batch in that prelude. That serialization is the one blocking call
 * this drain path can reach, and while it runs nothing else on the loop does —
 * not the request handlers, and not the deadline timer meant to bound this very
 * flush.
 *
 * Only the synchronous span is measured. Time the returned Promise spends
 * pending is the exporter waiting on a socket, which is exactly what the loop
 * is for and is already reported as export latency.
 */
function recordBlockingRisk(provider: ShutdownableProvider, syncMs: number): void {
  // Stryker disable next-line EqualityOperator: `<` vs `<=` differs only when a
  // provider blocks for exactly LONG_TASK_MS, which no timing-based test can
  // produce on demand — the boundary is wall-clock, not a value we choose. The
  // threshold itself is pinned by the tests either side of it.
  if (syncMs < LONG_TASK_MS) return;
  const signal = _signalForProvider(provider);
  // An untagged or foreign provider has no recorded signal. Charging its stall
  // to logs would invent an attribution, and pointing an operator at the wrong
  // exporter is worse than not pointing at one.
  if (!signal) return;
  _incrementHealth(_asyncBlockingRiskField(signal));
}

/**
 * Invoke one provider phase, timing the part of it that runs synchronously.
 *
 * The timer brackets the call itself, not the await: everything between these
 * two `Date.now()` reads happened before the event loop got its next turn.
 */
function callProviderPhase(
  provider: ShutdownableProvider,
  phase: () => Promise<void>,
): Promise<void> {
  const startedAt = Date.now();
  try {
    return phase();
  } finally {
    recordBlockingRisk(provider, Date.now() - startedAt);
  }
}

async function flushAndShutdownProvider(
  provider: ShutdownableProvider,
  timeoutMs: number,
): Promise<void> {
  // One budget spans both phases. Giving each the full `timeoutMs` lets a flush
  // that lands just inside the deadline be followed by a shutdown that gets the
  // whole deadline again, so a caller passing its remaining SIGTERM budget can
  // wait almost twice that long.
  //
  // A forceFlush rejection is deliberately treated as settled here, not
  // rethrown: teardown must still run on a provider whose exporter is broken,
  // or its queues and sockets leak. The flush-only paths go through
  // flushProviderOutcome instead, which does report the failure.
  const remaining = deadlineRemaining(timeoutMs);
  // Skip-when-undefined paths use explicit `if` guards (not `?.()`) so a
  // Stryker mutation that drops the optional chain becomes a hard TypeError
  // observable to the calling test. The method is hoisted to a local first so
  // its narrowing survives into the callProviderPhase closure.
  const forceFlush = provider.forceFlush;
  if (forceFlush) {
    let flush: Promise<void>;
    try {
      flush = callProviderPhase(provider, () => forceFlush.call(provider));
    } catch (err: unknown) {
      // A synchronously-throwing forceFlush is the same broken exporter as a
      // rejecting one, which the race below already treats as settled. Without
      // this catch (the same one flushProviderOutcome carries) the throw would
      // escape callProviderPhase — try/finally, no catch — before the shutdown
      // phase ran, Promise.allSettled would swallow it, and the provider's
      // queues and sockets would leak. Warn like flushProviderOutcome does,
      // then fall through so teardown still runs.
      console.warn(`[provide/telemetry] provider forceFlush failed: ${String(err)}`);
      flush = Promise.resolve();
    }
    const flushed = await raceWithDeadline(flush, remaining());
    if (!flushed) {
      console.warn(
        `[provide/telemetry] provider forceFlush exceeded ${timeoutMs}ms deadline; abandoning background flush`,
      );
      // When forceFlush has not resolved, skip the dependent shutdown call —
      // BatchLogRecordProcessor.shutdown internally re-flushes and would
      // simply repeat the same hang. Returning here keeps shutdownTelemetry
      // bounded by a single deadline per provider.
      return;
    }
  }
  const shutdown = provider.shutdown;
  // Stryker disable next-line ConditionalExpression: flipping `if (shutdown)`
  // to `if (true)` would call `undefined()` when shutdown is missing — but
  // the TypeError is swallowed by Promise.allSettled in shutdownTelemetry,
  // so the mutation has no observable effect on any test assertion.
  if (shutdown) {
    const stopped = await raceWithDeadline(
      callProviderPhase(provider, () => shutdown.call(provider)),
      remaining(),
    );
    if (!stopped) {
      console.warn(
        `[provide/telemetry] provider shutdown exceeded ${timeoutMs}ms deadline; abandoning background shutdown`,
      );
    }
  }
}

/**
 * Outcome of one provider's bounded drain: `flushed` when forceFlush resolved
 * in time (or there was nothing to flush), `timedOut` when it was abandoned at
 * the deadline, `failed` when it rejected (or threw) within it.
 */
export type FlushOutcome = 'flushed' | 'timedOut' | 'failed';

/**
 * Force-flush one provider, leaving it installed, and report the outcome.
 *
 * Never rejects: a broken exporter is a result (`'failed'`), not an exception —
 * one failing provider must not blow away the other signals' outcomes, and a
 * caller draining before a freeze needs the per-signal answer more than a
 * stack trace (Go maps the same condition to `Failed`, not an aborted call).
 * Both the timeout and the failure are logged so neither is silent.
 */
async function flushProviderOutcome(
  provider: ShutdownableProvider,
  timeoutMs: number,
): Promise<FlushOutcome> {
  const forceFlush = provider.forceFlush;
  if (!forceFlush) return 'flushed';
  let flush: Promise<void>;
  try {
    flush = callProviderPhase(provider, () => forceFlush.call(provider));
  } catch (err: unknown) {
    // A synchronously-throwing forceFlush is the same broken exporter as a
    // rejecting one; without this catch it would reject this call instead.
    console.warn(`[provide/telemetry] provider forceFlush failed: ${String(err)}`);
    return 'failed';
  }
  const settled = await raceWithDeadline(flush, timeoutMs);
  if (!settled) {
    console.warn(
      `[provide/telemetry] provider forceFlush exceeded ${timeoutMs}ms deadline; abandoning background flush`,
    );
    return 'timedOut';
  }
  // raceWithDeadline maps a rejection to "settled"; re-await the already-settled
  // promise so the error surfaces instead of counting as a successful drain.
  try {
    await flush;
  } catch (err: unknown) {
    console.warn(`[provide/telemetry] provider forceFlush failed: ${String(err)}`);
    return 'failed';
  }
  return 'flushed';
}

/**
 * Force-flush installed providers without tearing them down.
 *
 * The drain half of {@link shutdownTelemetry}: every provider we installed is
 * force-flushed under a bounded deadline and stays installed and usable. Use it
 * where records must be out before control returns — a request boundary, a
 * checkpoint, a serverless freeze — rather than shutting telemetry down and
 * paying to set it up again.
 *
 * `timeoutMs` defaults to the bounded-shutdown deadline
 * (`PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_MS`) and is applied per provider.
 * Resolves true when every provider flushed within the deadline, false when any
 * was abandoned or failed; with nothing installed there is nothing to flush, so
 * true. Never rejects: an exporter error is a `false` result (and a logged
 * warning), because the other providers' drain outcome must survive it.
 *
 * A provider a host application installed on the OTel globals is not ours to
 * drain and is left alone.
 *
 * Use {@link flushSignals} when you need to know *which* signal failed.
 */
export async function flushTelemetry(timeoutMs?: number): Promise<boolean> {
  const providers = _getRegisteredProviders();
  const deadlineMs = timeoutMs ?? getConfig().exporterLogsShutdownTimeoutMs;
  // Map eagerly so every provider's flush is in flight before the first await:
  // one slow exporter must not delay the others' drain.
  const results = await Promise.all(providers.map((p) => flushProviderOutcome(p, deadlineMs)));
  return results.every((outcome) => outcome === 'flushed');
}

/**
 * Force-flush installed providers, reporting the outcome per signal.
 *
 * The per-signal form of {@link flushTelemetry}. The signals export to three
 * potentially different endpoints, so one unreachable collector says nothing
 * about the other two — collapsing them to a single boolean makes a caller
 * re-emit or alert on records that were already delivered.
 *
 * A signal absent from the returned record has no provider of ours behind it.
 * Providers registered without a signal tag are still drained under the same
 * deadline, but cannot be attributed, so they appear under no key — their
 * outcome surfaces only through the per-provider warnings.
 */
export async function flushSignals(
  timeoutMs?: number,
): Promise<Partial<Record<SignalName, FlushOutcome>>> {
  const bySignal = _getProvidersBySignal();
  const deadlineMs = timeoutMs ?? getConfig().exporterLogsShutdownTimeoutMs;
  const entries = Object.entries(bySignal) as [SignalName, ShutdownableProvider][];
  // Compared by identity: a provider is either tagged or not, and the untagged
  // remainder must be drained exactly once — not skipped, not drained twice.
  const tagged = new Set(entries.map(([, p]) => p));
  const untagged = _getRegisteredProviders().filter((p) => !tagged.has(p));
  // Start every flush — tagged and untagged — before the first await, as
  // flushTelemetry does. Awaiting the untagged drains too is what makes the
  // "still drained" promise above true by the time this call resolves.
  const results = await Promise.all(
    [...entries.map(([, p]) => p), ...untagged].map((p) => flushProviderOutcome(p, deadlineMs)),
  );
  const drained: Partial<Record<SignalName, FlushOutcome>> = {};
  for (const [index, [signal]] of entries.entries()) {
    drained[signal] = results[index];
  }
  return drained;
}

/**
 * Flush and tear down installed providers.
 *
 * `timeoutMs` bounds the drain that precedes teardown — the part that can hang on
 * an unreachable collector — and defaults to the configured bounded-shutdown
 * deadline. A caller shutting down against a deadline passes the time it has left
 * so the drain cannot overrun it; teardown itself is local work and always completes.
 */
export async function shutdownTelemetry(timeoutMs?: number): Promise<void> {
  const providers = _getRegisteredProviders();
  const deadlineMs = timeoutMs ?? getConfig().exporterLogsShutdownTimeoutMs;
  await Promise.allSettled(providers.map((p) => flushAndShutdownProvider(p, deadlineMs)));
  await disableInstalledOtelGlobals();
  _resetOtelLogProviderForTests();
  _clearProviderState();
  _resetRootLogger();
}
