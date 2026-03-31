// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * React 18+ helpers for @undef-games/telemetry.
 *
 * Import from '@undef-games/telemetry/react'.
 * React must be installed as a peer dependency (>=18).
 */

import { useEffect } from 'react';
import { bindContext, unbindContext } from './context';

// ── useTelemetryContext ──────────────────────────────────────────────────────

/**
 * Bind key/value pairs into telemetry context for the lifetime of the component.
 * Cleans up on unmount. Re-runs when values change (content-compared, not by reference).
 */
export function useTelemetryContext(values: Record<string, unknown>): void {
  // Content-stable dep: avoids re-running when the object reference changes but values are equal.
  // Note: key insertion order affects JSON.stringify — { b:1, a:2 } !== { a:2, b:1 }.
  // Callers that build `values` via dynamic spread should keep key order consistent.
  const serialized = JSON.stringify(values);

  useEffect(() => {
    const keys = Object.keys(values);
    bindContext(values);
    return () => {
      unbindContext(...keys);
    };
    // `serialized` is the intentional dep — avoids re-running for referentially-new-but-equal
    // objects. `values` is deliberately omitted; the serialized string is the stable proxy.
  }, [serialized]);
}
