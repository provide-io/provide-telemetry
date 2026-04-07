// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * React 18+ helpers for @provide-io/telemetry.
 *
 * Import from '@provide-io/telemetry/react'.
 * React must be installed as a peer dependency (>=18).
 */

import { useEffect, useRef } from 'react';
import { bindContext, unbindContext } from './context';

// ── useTelemetryContext ──────────────────────────────────────────────────────

/**
 * Bind key/value pairs into telemetry context for the lifetime of the component.
 * Cleans up on unmount. Re-runs when values change (content-compared, not by reference).
 *
 * **Key ownership**: In browser environments, context is module-global (no
 * AsyncLocalStorage). Do not bind the same key from sibling components — when
 * either sibling unmounts it will delete the key for both. Intended usage:
 *   - App-level keys (userId, sessionId): bind once at the root component.
 *   - Page/component-level keys: bind keys that only that component owns.
 *
 * In Node.js / SSR contexts, AsyncLocalStorage provides per-request isolation
 * so this restriction does not apply.
 */
export function useTelemetryContext(values: Record<string, unknown>): void {
  const serialized = JSON.stringify(values);
  // Store previous keys so we can unbind keys that disappear between renders.
  const prevKeysRef = useRef<string[]>([]);

  useEffect(() => {
    const keys = Object.keys(values);
    // Unbind keys that were present before but are no longer in values.
    const removed = prevKeysRef.current.filter((k) => !keys.includes(k));
    if (removed.length > 0) unbindContext(...removed);

    bindContext(values);
    prevKeysRef.current = keys;

    return () => {
      unbindContext(...Object.keys(values));
    };
    // `serialized` is the intentional dep — avoids re-running for referentially-new-but-equal
    // objects. `values` is deliberately omitted; the serialized string is the stable proxy.
  }, [serialized]);
}
