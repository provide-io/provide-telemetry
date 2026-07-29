// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Stub providers shaped like SDK ones, for tests that install a provider on the
 * OTel globals.
 *
 * Shared rather than copied per test file because they encode the duck-type
 * `_isLiveTracerProvider` probes for — the forceFlush/shutdown lifecycle pair.
 * When that probe gains or drops a required method, this is the one place that
 * has to change, instead of copies in unrelated files quietly passing against
 * the old shape.
 */

/** Hands out tracers, flushes, shuts down. */
export function liveTracerProvider(): object {
  return {
    getTracer: () => ({ startSpan: () => ({}), startActiveSpan: () => undefined }),
    forceFlush: async (): Promise<void> => {},
    shutdown: async (): Promise<void> => {},
  };
}

/** The meter-side equivalent. */
export function liveMeterProvider(): object {
  return {
    getMeter: () => ({}),
    forceFlush: async (): Promise<void> => {},
    shutdown: async (): Promise<void> => {},
  };
}
