// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * React 18+ helpers for @provide-io/telemetry.
 *
 * Import from '@provide-io/telemetry/react'.
 * React must be installed as a peer dependency (>=18).
 */

import { Component, useEffect } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import { bindContext, unbindContext } from './context';
import { getLogger } from './logger';

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

// ── TelemetryErrorBoundary ───────────────────────────────────────────────────

interface TelemetryErrorBoundaryProps {
  children: ReactNode;
  fallback: ReactNode | ((error: Error, reset: () => void) => ReactNode);
  onError?: (error: Error, info: ErrorInfo) => void;
}

interface TelemetryErrorBoundaryState {
  error: Error | null;
}

/**
 * React error boundary that logs caught render errors via getLogger and renders
 * a fallback UI. Accepts a static ReactNode or a render-prop that receives the
 * caught error and a reset callback.
 *
 * Auto-logs to getLogger('react.error_boundary') on every catch. Call onError
 * for any additional handling (alerting, Sentry, etc.).
 */
export class TelemetryErrorBoundary extends Component<
  TelemetryErrorBoundaryProps,
  TelemetryErrorBoundaryState
> {
  constructor(props: TelemetryErrorBoundaryProps) {
    super(props);
    this.state = { error: null };
    this.reset = this.reset.bind(this);
  }

  static getDerivedStateFromError(error: Error): TelemetryErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    getLogger('react.error_boundary').error({
      event: 'react_error_caught',
      error_message: error.message,
      error_stack: error.stack ?? '',
      component_stack: info.componentStack ?? '',
    });
    this.props.onError?.(error, info);
  }

  reset(): void {
    this.setState({ error: null });
  }

  render(): ReactNode {
    const { error } = this.state;
    if (error !== null) {
      const { fallback } = this.props;
      if (typeof fallback === 'function') {
        return fallback(error, this.reset);
      }
      return fallback;
    }
    return this.props.children;
  }
}
