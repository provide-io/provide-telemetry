// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { setupTelemetry, _resetConfig } from '../src/config';
import {
  EventSchemaError,
  event,
  eventName,
  getStrictSchema,
  setStrictSchema,
  validateEventName,
  validateRequiredKeys,
  _resetStrictSchemaForTests,
} from '../src/schema';
import { TelemetryError } from '../src/exceptions';

describe('setStrictSchema / getStrictSchema', () => {
  afterEach(() => {
    _resetStrictSchemaForTests();
    _resetConfig();
  });

  it('getStrictSchema returns config value when no override is set', () => {
    _resetStrictSchemaForTests();
    setupTelemetry({ strictSchema: false });
    expect(getStrictSchema()).toBe(false);
    _resetConfig();
    setupTelemetry({ strictSchema: true });
    expect(getStrictSchema()).toBe(true);
  });

  it('setStrictSchema overrides config and getStrictSchema returns override', () => {
    setupTelemetry({ strictSchema: false });
    setStrictSchema(true);
    expect(getStrictSchema()).toBe(true);
  });

  it('setStrictSchema(false) override takes precedence over config true', () => {
    setupTelemetry({ strictSchema: true });
    setStrictSchema(false);
    expect(getStrictSchema()).toBe(false);
  });

  it('_resetStrictSchemaForTests clears the override', () => {
    setStrictSchema(true);
    _resetStrictSchemaForTests();
    // After reset, falls back to config; default config has strictSchema: false
    _resetConfig();
    expect(getStrictSchema()).toBe(false);
  });

  it('setStrictSchema(true) causes event() to reject non-conforming segments', () => {
    setStrictSchema(true);
    expect(() => event('Auth', 'login', 'success')).toThrow(EventSchemaError);
  });

  it('setStrictSchema(false) causes event() to accept non-conforming segments', () => {
    setStrictSchema(false);
    const rec = event('Auth', 'Login', 'Success');
    expect(rec.event).toBe('Auth.Login.Success');
  });
});

describe('EventSchemaError', () => {
  it('is a TelemetryError', () => {
    const e = new EventSchemaError('bad');
    expect(e).toBeInstanceOf(TelemetryError);
    expect(e.name).toBe('EventSchemaError');
  });
});

describe('eventName', () => {
  beforeEach(() => {
    setupTelemetry({ strictSchema: true });
  });

  afterEach(() => {
    _resetConfig();
  });

  it('joins valid segments with dots', () => {
    expect(eventName('app', 'user', 'login')).toBe('app.user.login');
    expect(eventName('service', 'api', 'request', 'ok')).toBe('service.api.request.ok');
    expect(eventName('a', 'b', 'c', 'd', 'e')).toBe('a.b.c.d.e');
  });

  it('throws with too few segments', () => {
    expect(() => eventName('a', 'b')).toThrow(EventSchemaError);
    expect(() => eventName('a')).toThrow(EventSchemaError);
    expect(() => eventName()).toThrow(EventSchemaError);
  });

  it('throws with too many segments', () => {
    expect(() => eventName('a', 'b', 'c', 'd', 'e', 'f')).toThrow(EventSchemaError);
  });

  it('throws with invalid segment characters', () => {
    expect(() => eventName('App', 'user', 'login')).toThrow(EventSchemaError); // uppercase
    expect(() => eventName('app', 'user-login', 'event')).toThrow(EventSchemaError); // hyphen
    expect(() => eventName('0app', 'user', 'login')).toThrow(EventSchemaError); // starts with digit
    expect(() => eventName('app user', 'x', 'y')).toThrow(EventSchemaError); // space
  });

  it('allows digits and underscores in non-first position', () => {
    expect(eventName('app2', 'user_v2', 'login_ok')).toBe('app2.user_v2.login_ok');
  });
});

describe('validateEventName', () => {
  it('passes valid strict names', () => {
    expect(() => validateEventName('app.user.login')).not.toThrow();
    expect(() => validateEventName('a.b.c.d.e')).not.toThrow();
  });

  it('throws for invalid strict names', () => {
    expect(() => validateEventName('app.user')).toThrow(EventSchemaError); // only 2 segments
    expect(() => validateEventName('App.user.login')).toThrow(EventSchemaError); // uppercase
    expect(() => validateEventName('a.b.c.d.e.f')).toThrow(EventSchemaError); // 6 segments
    expect(() => validateEventName('app..login')).toThrow(EventSchemaError); // empty segment
  });

  it('relaxed mode accepts any non-empty segments', () => {
    expect(() => validateEventName('Foo.Bar', false)).not.toThrow();
    expect(() => validateEventName('one', false)).not.toThrow();
    expect(() => validateEventName('a.b.c.d.e.f.g', false)).not.toThrow();
  });

  it('relaxed mode rejects empty segments', () => {
    expect(() => validateEventName('a..b', false)).toThrow(EventSchemaError);
    expect(() => validateEventName('', false)).toThrow(EventSchemaError);
  });
});

describe('validateRequiredKeys', () => {
  it('passes when all keys are present', () => {
    expect(() => validateRequiredKeys({ a: 1, b: 2, c: 3 }, ['a', 'b'])).not.toThrow();
  });

  it('throws listing missing keys (sorted)', () => {
    const err = (() => {
      try {
        validateRequiredKeys({ a: 1 }, ['z', 'b', 'a']);
      } catch (e) {
        return e;
      }
    })();
    expect(err).toBeInstanceOf(EventSchemaError);
    expect((err as EventSchemaError).message).toContain('b');
    expect((err as EventSchemaError).message).toContain('z');
  });

  it('passes with empty required keys', () => {
    expect(() => validateRequiredKeys({}, [])).not.toThrow();
  });
});

describe('eventName / validateEventName — error message content (mutation kills)', () => {
  beforeEach(() => {
    setupTelemetry({ strictSchema: true });
  });

  afterEach(() => {
    _resetConfig();
  });

  it('segment count error mentions segment count', () => {
    // Kills: StringLiteral mutation that empties the error message
    expect(() => eventName('a', 'b')).toThrow(/got 2/);
    expect(() => eventName('a', 'b', 'c', 'd', 'e', 'f')).toThrow(/got 6/);
  });

  it('invalid segment error mentions the segment index', () => {
    // Kills: StringLiteral mutation that empties the segment error
    expect(() => eventName('valid', 'INVALID', 'seg')).toThrow(/segment\[1\]/);
  });

  it('validateEventName relaxed mode error mentions segment', () => {
    expect(() => validateEventName('valid..empty', false)).toThrow(/segment/i);
  });
});

describe('validateRequiredKeys — error message content (mutation kills)', () => {
  it('lists missing keys in sorted order', () => {
    // Kills: StringLiteral + sort-removal mutations
    const obj = { a: 1 };
    expect(() => validateRequiredKeys(obj, ['z', 'a', 'm'])).toThrow(/m, z/); // sorted, only missing ones
  });
});

describe('validateEventName — strict mode error message content (kills StringLiteral at schema.ts:52)', () => {
  it('error message mentions segment count when too few segments', () => {
    // Kills: StringLiteral mutation that empties validateEventName strict-mode error message
    let msg = '';
    try {
      validateEventName('app.user');
    } catch (e) {
      msg = (e as Error).message;
    }
    expect(msg).toMatch(/expected 3-5 segments/);
    expect(msg).toMatch(/got 2/);
  });

  it('error message mentions segment count when too many segments', () => {
    let msg = '';
    try {
      validateEventName('a.b.c.d.e.f');
    } catch (e) {
      msg = (e as Error).message;
    }
    expect(msg).toMatch(/expected 3-5 segments/);
    expect(msg).toMatch(/got 6/);
  });
});

describe('eventName — join separator is dot (kills .join mutation at line 29)', () => {
  beforeEach(() => {
    setupTelemetry({ strictSchema: true });
  });

  afterEach(() => {
    _resetConfig();
  });

  it('segments are joined with dots, not other separators', () => {
    const name = eventName('app', 'user', 'login');
    expect(name).toBe('app.user.login');
    // Verify dot is the separator specifically
    expect(name).toContain('.');
    expect(name.split('.').length).toBe(3);
    expect(name.split('.')[0]).toBe('app');
    expect(name.split('.')[1]).toBe('user');
    expect(name.split('.')[2]).toBe('login');
  });

  it('result contains dots between every pair of segments', () => {
    const name = eventName('a', 'b', 'c', 'd', 'e');
    // Verify every adjacent pair is separated by exactly '.'
    expect(name).toBe('a.b.c.d.e');
    expect(name.indexOf('.')).toBe(1);
    expect(name.charAt(1)).toBe('.');
    expect(name.charAt(3)).toBe('.');
  });
});

describe('eventName — strict schema config integration', () => {
  afterEach(() => {
    _resetConfig();
  });

  it('relaxed mode allows 1 segment', () => {
    setupTelemetry({ strictSchema: false });
    expect(eventName('svc')).toBe('svc');
  });

  it('relaxed mode allows 6 segments', () => {
    setupTelemetry({ strictSchema: false });
    expect(eventName('a', 'b', 'c', 'd', 'e', 'f')).toBe('a.b.c.d.e.f');
  });

  it('strict mode rejects 1 segment', () => {
    setupTelemetry({ strictSchema: true });
    expect(() => eventName('svc')).toThrow(EventSchemaError);
  });

  it('0 segments throws even in relaxed mode', () => {
    setupTelemetry({ strictSchema: false });
    expect(() => eventName()).toThrow(EventSchemaError);
  });
});

describe('event()', () => {
  beforeEach(() => {
    setupTelemetry({ strictSchema: true });
  });

  afterEach(() => {
    _resetConfig();
  });

  it('returns structured EventRecord for 3 segments (DAS)', () => {
    const rec = event('auth', 'login', 'success');
    expect(rec).toEqual({
      event: 'auth.login.success',
      domain: 'auth',
      action: 'login',
      status: 'success',
    });
    expect(rec.resource).toBeUndefined();
  });

  it('returns structured EventRecord for 4 segments (DARS)', () => {
    const rec = event('db', 'query', 'orders', 'failure');
    expect(rec).toEqual({
      event: 'db.query.orders.failure',
      domain: 'db',
      action: 'query',
      resource: 'orders',
      status: 'failure',
    });
  });

  it('throws EventSchemaError with 2 segments', () => {
    expect(() => event('a', 'b')).toThrow(EventSchemaError);
    expect(() => event('a', 'b')).toThrow(/requires 3 or 4 segments/);
  });

  it('throws EventSchemaError with 5 segments', () => {
    expect(() => event('a', 'b', 'c', 'd', 'e')).toThrow(EventSchemaError);
    expect(() => event('a', 'b', 'c', 'd', 'e')).toThrow(/requires 3 or 4 segments/);
  });

  it('throws EventSchemaError with 0 segments', () => {
    expect(() => event()).toThrow(EventSchemaError);
  });

  it('throws EventSchemaError with 1 segment', () => {
    expect(() => event('a')).toThrow(EventSchemaError);
  });

  it('strict mode validates segment format', () => {
    expect(() => event('Auth', 'login', 'success')).toThrow(EventSchemaError);
    expect(() => event('auth', 'LOGIN', 'success')).toThrow(/does not match pattern/);
    expect(() => event('auth', 'login', '0bad')).toThrow(EventSchemaError);
  });

  it('relaxed mode skips segment format validation', () => {
    _resetConfig();
    setupTelemetry({ strictSchema: false });
    const rec = event('Auth', 'Login', 'Success');
    expect(rec.event).toBe('Auth.Login.Success');
    expect(rec.domain).toBe('Auth');
  });

  it('eventName() still works as deprecated alias', () => {
    const name = eventName('auth', 'login', 'success');
    expect(name).toBe('auth.login.success');
    expect(typeof name).toBe('string');
  });
});
