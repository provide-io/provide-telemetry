// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import {
  EventSchemaError,
  eventName,
  validateEventName,
  validateRequiredKeys,
} from '../src/schema';
import { TelemetryError } from '../src/exceptions';

describe('EventSchemaError', () => {
  it('is a TelemetryError', () => {
    const e = new EventSchemaError('bad');
    expect(e).toBeInstanceOf(TelemetryError);
    expect(e.name).toBe('EventSchemaError');
  });
});

describe('eventName', () => {
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
