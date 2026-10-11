// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Reserved root fields — the `reserved_root_fields` collision rule in
// spec/telemetry-api.yaml. A field the SDK stamps on a record replaces a
// caller's or a bound value of the same name; one it does not stamp on that
// record leaves the caller's value standing.

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { _resetConfig, setupTelemetry } from '../src/config.js';
import { _resetContext, bindContext } from '../src/context.js';
import { _resetRootLogger, makeWriteHook } from '../src/logger.js';
import { _resetTraceContext, setTraceContext } from '../src/tracing.js';

const TRACE_ID = '0123456789abcdef0123456789abcdef'; // pragma: allowlist secret
const SPAN_ID = '0123456789abcdef'; // pragma: allowlist secret

const FORGED = {
  service: 'forged-service',
  env: 'forged-env',
  version: 'forged-version',
  trace_id: 'forged-trace',
  span_id: 'forged-span',
};

function captured(): Record<string, unknown> {
  const logs = (window as unknown as Record<string, Record<string, unknown>[]>)['__pinoLogs'];
  return logs[logs.length - 1] as Record<string, unknown>;
}

beforeEach(() => {
  _resetConfig();
  _resetRootLogger();
  _resetContext();
  _resetTraceContext();
  (window as unknown as Record<string, unknown>)['__pinoLogs'] = [];
});

afterEach(() => {
  _resetConfig();
  _resetRootLogger();
  _resetContext();
  _resetTraceContext();
});

describe('write hook — reserved root fields', () => {
  it('replaces caller and bound values with every field the SDK stamps', () => {
    setupTelemetry({
      serviceName: 'real-svc',
      environment: 'prod',
      version: '1.2.3',
      captureToWindow: true,
      consoleOutput: false,
    });
    bindContext({ service: 'bound-service' });
    setTraceContext(TRACE_ID, SPAN_ID);

    makeWriteHook()({ level: 30, event: 'reserved.check', ...FORGED });

    expect(captured()).toMatchObject({
      service: 'real-svc',
      env: 'prod',
      version: '1.2.3',
      trace_id: TRACE_ID,
      span_id: SPAN_ID,
    });
  });

  it('leaves the caller value standing for a field the SDK does not stamp', () => {
    setupTelemetry({
      serviceName: '',
      environment: '',
      version: '',
      captureToWindow: true,
      consoleOutput: false,
    });

    makeWriteHook()({ level: 30, event: 'reserved.check', ...FORGED });

    expect(captured()).toMatchObject(FORGED);
  });
});
