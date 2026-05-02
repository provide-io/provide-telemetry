// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// vi.resetModules() before each import forces fresh module evaluation so that
// Stryker's perTest V8 coverage attributes the _COLD_FIELDS and
// PROVIDER_CHANGING_FIELDS initialization lines to these tests (not only to
// the tracing.fallback.test.ts module-reset test that happens to import
// runtime.ts transitively first). The direct .toContain() assertions then kill
// every StringLiteral and ArrayDeclaration mutant on L191–284 of runtime.ts.

import { afterEach, describe, expect, it, vi } from 'vitest';

describe('_COLD_FIELDS direct content assertions (kills L191–206 mutants)', () => {
  afterEach(() => {
    vi.resetModules();
  });

  it('contains all 14 expected cold fields and no others', async () => {
    vi.resetModules();
    const { _coldFieldsForTest } = await import('../src/runtime');
    expect(_coldFieldsForTest).toHaveLength(14);
    expect(_coldFieldsForTest).toContain('serviceName');
    expect(_coldFieldsForTest).toContain('environment');
    expect(_coldFieldsForTest).toContain('version');
    expect(_coldFieldsForTest).toContain('otelEnabled');
    expect(_coldFieldsForTest).toContain('tracingEnabled');
    expect(_coldFieldsForTest).toContain('metricsEnabled');
    expect(_coldFieldsForTest).toContain('otlpEndpoint');
    expect(_coldFieldsForTest).toContain('otlpHeaders');
    expect(_coldFieldsForTest).toContain('otlpLogsEndpoint');
    expect(_coldFieldsForTest).toContain('otlpLogsHeaders');
    expect(_coldFieldsForTest).toContain('otlpTracesEndpoint');
    expect(_coldFieldsForTest).toContain('otlpTracesHeaders');
    expect(_coldFieldsForTest).toContain('otlpMetricsEndpoint');
    expect(_coldFieldsForTest).toContain('otlpMetricsHeaders');
  });
});

describe('PROVIDER_CHANGING_FIELDS direct content assertions (kills L269–284 mutants)', () => {
  afterEach(() => {
    vi.resetModules();
  });

  it('contains all 14 expected provider-changing fields and no others', async () => {
    vi.resetModules();
    const { _providerChangingFieldsForTest } = await import('../src/runtime');
    expect(_providerChangingFieldsForTest).toHaveLength(14);
    expect(_providerChangingFieldsForTest).toContain('serviceName');
    expect(_providerChangingFieldsForTest).toContain('environment');
    expect(_providerChangingFieldsForTest).toContain('version');
    expect(_providerChangingFieldsForTest).toContain('otelEnabled');
    expect(_providerChangingFieldsForTest).toContain('tracingEnabled');
    expect(_providerChangingFieldsForTest).toContain('metricsEnabled');
    expect(_providerChangingFieldsForTest).toContain('otlpEndpoint');
    expect(_providerChangingFieldsForTest).toContain('otlpHeaders');
    expect(_providerChangingFieldsForTest).toContain('otlpLogsEndpoint');
    expect(_providerChangingFieldsForTest).toContain('otlpLogsHeaders');
    expect(_providerChangingFieldsForTest).toContain('otlpTracesEndpoint');
    expect(_providerChangingFieldsForTest).toContain('otlpTracesHeaders');
    expect(_providerChangingFieldsForTest).toContain('otlpMetricsEndpoint');
    expect(_providerChangingFieldsForTest).toContain('otlpMetricsHeaders');
  });
});
