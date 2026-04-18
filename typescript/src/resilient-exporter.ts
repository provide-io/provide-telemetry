// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Per-export resilience wrapper for OTel log/span/metric exporters.
 *
 * Mirrors Python `provide.telemetry.resilient_exporter`. Historically the
 * resilience policy (retries/timeouts/circuit breaker) was only applied when
 * the underlying exporter was constructed; live batch exports bypassed the
 * policy entirely. This wrapper closes that gap by routing every `export()`
 * call through `runWithResilience` so the documented guarantees apply to
 * real transport traffic — not just to the one-shot construction probe.
 */

import { runWithResilience } from './resilience';

/** Shape of an OTel exporter result. */
export interface ExportResultLike {
  code: number;
  error?: Error;
}

/** Callback-based export signature shared by log/span/metric exporters. */
export interface ResilientExportable {
  export(items: unknown, resultCallback: (result: ExportResultLike) => void): void;
  shutdown(): Promise<void>;
  forceFlush?(): Promise<void>;
}

/** OTel ExportResultCode.FAILED value (kept inline so this file has no runtime OTel import). */
const EXPORT_RESULT_FAILED = 1;

/**
 * Wrap `inner` so every `export()` call applies the resilience policy for
 * `signal`. The callback contract is preserved: on fail-open drop or an
 * exhausted retry budget, the wrapper invokes `resultCallback` with a FAILED
 * ExportResult so OTel's batch processor records the drop instead of hanging.
 */
export function wrapResilientExporter<T extends ResilientExportable>(signal: string, inner: T): T {
  const wrapped: ResilientExportable = {
    export(items, resultCallback) {
      // Convert the callback-based inner.export into a Promise so we can hand
      // it to runWithResilience. A non-SUCCESS result is rejected so the
      // resilience layer counts it as a failed attempt and may retry.
      const runOnce = () =>
        new Promise<ExportResultLike>((resolve, reject) => {
          try {
            inner.export(items, (result) => {
              if (result && result.code !== EXPORT_RESULT_FAILED) {
                resolve(result);
              } else {
                reject(result?.error ?? new Error('exporter reported FAILED'));
              }
            });
          } catch (err) {
            reject(err instanceof Error ? err : new Error(String(err)));
          }
        });

      runWithResilience(signal, runOnce).then(
        (result) => {
          // null means fail_open dropped the batch after exhausting retries.
          if (result === null) {
            resultCallback({ code: EXPORT_RESULT_FAILED });
          } else {
            resultCallback(result);
          }
        },
        (err) => {
          // fail_closed path: runWithResilience rejected. Surface to the
          // processor as FAILED so it records the drop rather than crashing
          // inside a background timer handler.
          resultCallback({
            code: EXPORT_RESULT_FAILED,
            error: err instanceof Error ? err : new Error(String(err)),
          });
        },
      );
    },
    shutdown: () => inner.shutdown(),
    forceFlush: (() => {
      const fn = inner.forceFlush;
      return fn ? () => fn.call(inner) : undefined;
    })(),
  };
  // Preserve any additional properties the exporter exposes (e.g. configuration
  // getters used by tests or introspection). Cast is safe because the wrapper
  // implements the same public surface.
  return Object.assign(Object.create(Object.getPrototypeOf(inner) as object), inner, wrapped) as T;
}
