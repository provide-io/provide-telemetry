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
import {
  _clearProviderState,
  _getRegisteredProviders,
  type ShutdownableProvider,
} from './runtime.js';
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

async function flushAndShutdownProvider(
  provider: ShutdownableProvider,
  timeoutMs: number,
): Promise<void> {
  // Skip-when-undefined paths use explicit `if` guards (not `?.()`) so a
  // Stryker mutation that drops the optional chain becomes a hard TypeError
  // observable to the calling test.
  if (provider.forceFlush) {
    const flushed = await raceWithDeadline(provider.forceFlush(), timeoutMs);
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
  // Stryker disable next-line ConditionalExpression: flipping `if (provider.shutdown)`
  // to `if (true)` would call `undefined()` when shutdown is missing — but
  // the TypeError is swallowed by Promise.allSettled in shutdownTelemetry,
  // so the mutation has no observable effect on any test assertion.
  if (provider.shutdown) {
    const stopped = await raceWithDeadline(provider.shutdown(), timeoutMs);
    if (!stopped) {
      console.warn(
        `[provide/telemetry] provider shutdown exceeded ${timeoutMs}ms deadline; abandoning background shutdown`,
      );
    }
  }
}

/**
 * Force-flush one provider, leaving it installed. Resolves to false when the
 * flush was abandoned at the deadline; rethrows a forceFlush rejection that
 * arrived in time, so a broken exporter is not silently reported as drained.
 */
async function flushProvider(provider: ShutdownableProvider, timeoutMs: number): Promise<boolean> {
  if (!provider.forceFlush) return true;
  const flush = provider.forceFlush();
  const flushed = await raceWithDeadline(flush, timeoutMs);
  if (!flushed) {
    console.warn(
      `[provide/telemetry] provider forceFlush exceeded ${timeoutMs}ms deadline; abandoning background flush`,
    );
    return false;
  }
  // raceWithDeadline maps a rejection to "settled"; re-await the already-settled
  // promise so the error surfaces instead of counting as a successful drain.
  await flush;
  return true;
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
 * was abandoned; with nothing installed there is nothing to flush, so true.
 *
 * A provider a host application installed on the OTel globals is not ours to
 * drain and is left alone.
 */
export async function flushTelemetry(timeoutMs?: number): Promise<boolean> {
  const providers = _getRegisteredProviders();
  const deadlineMs = timeoutMs ?? getConfig().exporterLogsShutdownTimeoutMs;
  // Map eagerly so every provider's flush is in flight before the first await:
  // one slow exporter must not delay the others' drain.
  const results = await Promise.all(providers.map((p) => flushProvider(p, deadlineMs)));
  return results.every((ok) => ok);
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
