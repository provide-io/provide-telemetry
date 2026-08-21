// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

import { afterEach, describe, expect, it } from 'vitest';
import {
  EventSchemaError,
  event,
  eventName,
  setStrictSchema,
  validateEventName,
} from '../src/schema.js';

// Executable evidence for the event_name_contract fixtures in
// spec/behavioral_fixtures.yaml — one `it` per case, in fixture order.

afterEach(() => setStrictSchema(false));

describe('parity: event_name_contract', () => {
  it('relaxed_single_segment_ok', () => {
    expect(eventName('startup')).toBe('startup');
  });

  it('relaxed_two_segments_ok', () => {
    expect(eventName('app', 'ready')).toBe('app.ready');
  });

  it('relaxed_six_segments_ok', () => {
    expect(eventName('a', 'b', 'c', 'd', 'e', 'f')).toBe('a.b.c.d.e.f');
  });

  it('relaxed_grammar_not_enforced', () => {
    expect(eventName('User', 'Login-OK')).toBe('User.Login-OK');
  });

  it('relaxed_zero_segments_error', () => {
    expect(() => eventName()).toThrow(EventSchemaError);
  });

  it('relaxed_empty_segment_error', () => {
    expect(() => eventName('user', '', 'ok')).toThrow(EventSchemaError);
  });

  it('strict_three_segments_ok', () => {
    setStrictSchema(true);
    expect(eventName('user', 'login', 'ok')).toBe('user.login.ok');
  });

  it('strict_five_segments_ok', () => {
    setStrictSchema(true);
    expect(eventName('a', 'b', 'c', 'd', 'e')).toBe('a.b.c.d.e');
  });

  it('strict_two_segments_error', () => {
    setStrictSchema(true);
    expect(() => eventName('too', 'few')).toThrow(EventSchemaError);
  });

  it('strict_six_segments_error', () => {
    setStrictSchema(true);
    expect(() => eventName('a', 'b', 'c', 'd', 'e', 'f')).toThrow(EventSchemaError);
  });

  it('strict_grammar_enforced', () => {
    setStrictSchema(true);
    expect(() => eventName('user', 'Login', 'ok')).toThrow(EventSchemaError);
  });

  it('strict_zero_segments_error', () => {
    setStrictSchema(true);
    expect(() => eventName()).toThrow(EventSchemaError);
  });

  it('validate_relaxed_single_segment_ok', () => {
    expect(() => validateEventName('startup', false)).not.toThrow();
  });

  it('validate_relaxed_empty_string_error', () => {
    expect(() => validateEventName('', false)).toThrow(EventSchemaError);
  });

  it('validate_relaxed_interior_empty_segment_error', () => {
    expect(() => validateEventName('a..b', false)).toThrow(EventSchemaError);
  });

  it('validate_relaxed_grammar_not_enforced', () => {
    expect(() => validateEventName('User.Login-OK', false)).not.toThrow();
  });

  it('validate_strict_grammar_enforced', () => {
    expect(() => validateEventName('user.Login.ok', true)).toThrow(EventSchemaError);
  });

  it('validate_strict_two_segments_error', () => {
    expect(() => validateEventName('too.few', true)).toThrow(EventSchemaError);
  });

  // event() is out of scope: its count rule belongs to the DAS/DARS record
  // shape, not to the name, so relaxing the name contract must not move it.
  it('event_count_rule_unchanged_by_relaxed_mode', () => {
    expect(() => event('only', 'two')).toThrow(EventSchemaError);
    expect(() => event('a', 'b', 'c', 'd', 'e')).toThrow(EventSchemaError);
  });
});
