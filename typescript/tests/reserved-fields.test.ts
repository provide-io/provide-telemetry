// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// reserved_root_fields.replacement_reporting in spec/telemetry-api.yaml, and
// the contract case reserved_root_fields_replacement_reported.

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { _resetConfig, setupTelemetry } from '../src/config.js';
import { _resetContext, bindContext } from '../src/context.js';
import { _resetHealthForTests, getHealthSnapshot } from '../src/health.js';
import { _resetRootLogger, getLogger } from '../src/logger.js';
import {
  RESERVED_WARNING_EVENT,
  RESERVED_WARNING_LOGGER,
  _resetReservedWarningsForTests,
  reportReservedReplacements,
  stampReserved,
} from '../src/reserved-fields.js';
import { _resetSamplingForTests, setSamplingPolicy } from '../src/sampling.js';
import { setTraceContext } from '../src/tracing.js';

type Rec = Record<string, unknown>;

function records(): Rec[] {
  return (window as unknown as Record<string, Rec[]>)['__pinoLogs'];
}

function emit(fields: Rec): Rec[] {
  (window as unknown as Record<string, unknown>)['__pinoLogs'] = [];
  getLogger('caller').info({ event: 'reserved.fields.ok', ...fields });
  return records();
}

function warned(out: Rec[]): unknown[] {
  return out.filter((r) => r['message'] === RESERVED_WARNING_EVENT).map((r) => r['field']);
}

const replacements = () => getHealthSnapshot().reservedFieldReplacements;

function configure(version = '1.2.3'): void {
  _resetConfig();
  _resetRootLogger();
  setupTelemetry({
    serviceName: 'svc',
    environment: 'stage',
    version,
    logLevel: 'debug',
    captureToWindow: true,
  });
}

beforeEach(() => {
  _resetHealthForTests();
  _resetReservedWarningsForTests();
  _resetSamplingForTests();
  _resetContext();
  configure();
});

afterEach(() => {
  setTraceContext(undefined, undefined);
  _resetContext();
  _resetSamplingForTests();
  _resetConfig();
  _resetRootLogger();
});

describe('reserved field replacement reporting', () => {
  it('counts a replaced field and warns about it once, before the record', () => {
    const first = emit({ version: '9.9.9', env: 'forged' });
    expect(warned(first)).toEqual(['env', 'version']);
    const last = first[first.length - 1];
    expect(last['message']).toBe('reserved.fields.ok');
    expect(last['version']).toBe('1.2.3');
    expect(replacements()).toBe(2);

    expect(warned(emit({ version: '8.8.8' }))).toEqual([]);
    expect(replacements()).toBe(3);
  });

  it('names the field in a WARN record and never the caller value', () => {
    const warning = emit({ version: 'secret-build-7' })[0];
    expect(warning['message']).toBe(RESERVED_WARNING_EVENT);
    expect(warning['field']).toBe('version');
    expect(warning['level']).toBe('WARN');
    expect(warning['name']).toBe(RESERVED_WARNING_LOGGER);
    expect(JSON.stringify(warning)).not.toContain('secret-build-7');
  });

  it('does not count a caller value equal to the stamped one', () => {
    expect(warned(emit({ version: '1.2.3', service: 'svc' }))).toEqual([]);
    expect(replacements()).toBe(0);
  });

  it('does not count where the SDK stamps nothing', () => {
    configure('');
    const out = emit({ version: '9.9.9' });
    expect(out[out.length - 1]['version']).toBe('9.9.9');
    expect(replacements()).toBe(0);
  });

  it('counts trace ids only while a span is live', () => {
    emit({ trace_id: 'caller-trace', span_id: 'caller-span' });
    expect(replacements()).toBe(0);

    setTraceContext('aabbccdd11223344aabbccdd11223344', 'aabb001122334455');
    expect(warned(emit({ trace_id: 'caller-trace', span_id: 'caller-span' }))).toEqual([
      'trace_id',
      'span_id',
    ]);
    expect(replacements()).toBe(2);
  });

  it('counts a bound value once, not again for its own warning', () => {
    bindContext({ version: 'bound' });
    expect(warned(emit({}))).toEqual(['version']);
    expect(replacements()).toBe(1);
  });

  it('neither counts nor warns about a record refused at admission', () => {
    setSamplingPolicy('logs', { defaultRate: 0 });
    expect(emit({ version: '9.9.9' })).toEqual([]);
    expect(replacements()).toBe(0);
  });

  it('forgets which fields were warned about on reset', () => {
    expect(warned(emit({ version: '9.9.9' }))).toEqual(['version']);
    _resetReservedWarningsForTests();
    expect(warned(emit({ version: '9.9.9' }))).toEqual(['version']);
  });
});

describe('stampReserved and reportReservedReplacements', () => {
  it('stamps only a value it has, and notes only a different caller value', () => {
    const record: Rec = { env: 'caller', version: 2 };
    const replaced: string[] = [];
    stampReserved(record, 'service', '', replaced);
    stampReserved(record, 'env', 'prod', replaced);
    stampReserved(record, 'version', '2', replaced);
    stampReserved(record, 'trace_id', 'abc', replaced);
    expect(record).toEqual({ env: 'prod', version: '2', trace_id: 'abc' });
    expect(replaced).toEqual(['env', 'version']);
  });

  it('warns in canonical order and leaves the guard clear after a throwing warner', () => {
    const order: string[] = [];
    reportReservedReplacements(['span_id', 'service'], (field) => order.push(field));
    expect(order).toEqual(['service', 'span_id']);
    expect(() =>
      reportReservedReplacements(['env'], () => {
        throw new Error('warner failed');
      }),
    ).toThrow('warner failed');
    const after: string[] = [];
    reportReservedReplacements(['version'], (field) => after.push(field));
    expect(after).toEqual(['version']);
  });
});
