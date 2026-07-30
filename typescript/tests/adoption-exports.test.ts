// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
// @vitest-environment node

/**
 * Status is not export.
 *
 * The probe tests prove the facade *reports* a host-installed provider, and the
 * cross-language host_provider_adoption case proves all four agree on that
 * reporting. Neither shows a span leaving through it. Go had this covered;
 * TypeScript asserted sampling behaviour against a stub `startSpan`, which
 * cannot tell an exporting provider from an inert one — so a regression that
 * reported adoption while emitting nowhere would have gone unnoticed.
 */

import {
  BasicTracerProvider,
  InMemorySpanExporter,
  SimpleSpanProcessor,
} from '@opentelemetry/sdk-trace-base';
import { trace } from '@opentelemetry/api';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { _resetConfig, setupTelemetry } from '../src/config.js';
import { _resetRuntimeForTests, getRuntimeStatus } from '../src/runtime.js';
import { withTrace } from '../src/tracing.js';

beforeEach(() => {
  trace.disable();
  _resetRuntimeForTests();
  _resetConfig();
});

afterEach(() => {
  trace.disable();
  _resetRuntimeForTests();
  _resetConfig();
});

describe('a host-installed provider actually exports', () => {
  it('routes a facade span to the host provider’s exporter', () => {
    const exporter = new InMemorySpanExporter();
    const hostProvider = new BasicTracerProvider({
      spanProcessors: [new SimpleSpanProcessor(exporter)],
    });
    // The host installs its own provider; we register none of our own.
    trace.setGlobalTracerProvider(hostProvider as never);

    setupTelemetry({ tracingEnabled: true });
    expect(getRuntimeStatus().providers.traces).toBe(true);

    const result = withTrace('adopted.export.span', () => 7);
    expect(result).toBe(7);

    expect(exporter.getFinishedSpans().map((span) => span.name)).toEqual(['adopted.export.span']);
  });
});
