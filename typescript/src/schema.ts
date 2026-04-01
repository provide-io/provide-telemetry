// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Event schema validation — mirrors Python provide.telemetry.schema.events.
 */

import { getConfig } from './config';
import { TelemetryError } from './exceptions';

// Module-level strict-schema override.
// null = not set; use getConfig().strictSchema / strictEventName.
// true/false = explicitly overridden via setStrictSchema().
let _strictSchemaOverride: boolean | null = null;

/**
 * Enable or disable strict segment-format validation for event() and eventName().
 *
 * When enabled, every segment must match /^[a-z][a-z0-9_]*$/.
 * When disabled (the default), segment format is not validated.
 * Segment count validation is always enforced.
 *
 * This overrides the strictSchema field from config for the lifetime of the
 * module (i.e. until setStrictSchema is called again or resetStrictSchemaForTests).
 */
export function setStrictSchema(enabled: boolean): void {
  _strictSchemaOverride = enabled;
}

/**
 * Return whether strict event-name validation is currently enabled.
 * Returns the override value if set, otherwise falls back to the effective
 * config value: strictSchema || strictEventName.
 */
export function getStrictSchema(): boolean {
  if (_strictSchemaOverride !== null) return _strictSchemaOverride;
  const cfg = getConfig();
  return cfg.strictSchema || cfg.strictEventName;
}

/** Reset the strict-schema override. For use in tests only. */
export function _resetStrictSchemaForTests(): void {
  _strictSchemaOverride = null;
}

export class EventSchemaError extends TelemetryError {
  constructor(message?: string) {
    super(message);
    this.name = 'EventSchemaError';
  }
}

const SEGMENT_RE = /^[a-z][a-z0-9_]*$/;
const MIN_SEGMENTS = 3;
const MAX_SEGMENTS = 5;

/**
 * Build and validate an event name from dot-separated segments.
 * In strict mode (default): enforces 3–5 segments, each matching /^[a-z][a-z0-9_]*$/.
 * In relaxed mode: requires at least 1 segment, skips count and format checks.
 */
export function eventName(...segments: string[]): string {
  if (segments.length === 0) {
    throw new EventSchemaError(`expected ${MIN_SEGMENTS}-${MAX_SEGMENTS} segments, got 0`);
  }
  const strict = getConfig().strictSchema;
  if (strict) {
    if (segments.length < MIN_SEGMENTS || segments.length > MAX_SEGMENTS) {
      throw new EventSchemaError(
        `expected ${MIN_SEGMENTS}-${MAX_SEGMENTS} segments, got ${segments.length}`,
      );
    }
    // Stryker disable next-line EqualityOperator: segments[length] is undefined; SEGMENT_RE.test('undefined') returns true so no extra throw — equivalent
    for (let i = 0; i < segments.length; i++) {
      if (!SEGMENT_RE.test(segments[i])) {
        // Stryker disable next-line StringLiteral
        throw new EventSchemaError(`invalid event segment: segment[${i}]=${segments[i]}`);
      }
    }
  }
  return segments.join('.');
}

/**
 * Validate an already-assembled event name string.
 * In strict mode (default), enforces 3–5 dot-separated lowercase segments.
 * In relaxed mode, only checks that each segment is non-empty.
 */
export function validateEventName(name: string, strict: boolean = true): void {
  const segments = name.split('.');
  if (strict) {
    if (segments.length < MIN_SEGMENTS || segments.length > MAX_SEGMENTS) {
      // Stryker disable next-line StringLiteral
      throw new EventSchemaError(
        `expected ${MIN_SEGMENTS}-${MAX_SEGMENTS} segments, got ${segments.length}`,
      );
    }
    // Stryker disable next-line EqualityOperator: same as above — undefined segment passes SEGMENT_RE
    for (let i = 0; i < segments.length; i++) {
      if (!SEGMENT_RE.test(segments[i])) {
        // Stryker disable next-line StringLiteral
        throw new EventSchemaError(`invalid event segment: segment[${i}]=${segments[i]}`);
      }
    }
  } else {
    // Stryker disable next-line ConditionalExpression: an empty input 'split' always has length >= 1; the `< 1` check is never triggered and is unreachable
    if (segments.length < 1 || segments.some((s) => s.length === 0)) {
      throw new EventSchemaError('event name must have at least one non-empty segment');
    }
  }
}

/**
 * Verify that all required keys are present in obj.
 * Throws EventSchemaError listing the missing keys.
 */
export function validateRequiredKeys(obj: Record<string, unknown>, keys: string[]): void {
  const missing = keys.filter((k) => !(k in obj));
  if (missing.length > 0) {
    throw new EventSchemaError(`missing required keys: ${missing.sort().join(', ')}`);
  }
}
