// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Cross-language regression: secrets embedded in the log message string must
 * be replaced with the redaction sentinel when sanitize is enabled.
 *
 * Companion tests:
 *   * Python: tests/regression/test_message_pii_cross_language.py (reference)
 *   * Go:     go/logger_handlers_test.go
 *               TestHandler_PIISanitization_MessageContent
 *               TestHandler_PIISanitization_MessageContent_WildcardRule
 *   * Rust:   rust/src/logger/processors.rs (#[cfg(test)] mod tests)
 *
 * TypeScript inherits the desired behaviour for free because sanitize() in
 * pii.ts iterates every top-level string field of the log record (including
 * the 'message' field) and substitutes REDACTED when _detectSecretInValue
 * returns true. These tests pin that contract so a future refactor cannot
 * silently regress to the Go-style "attributes only" bug.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { _resetConfig, setupTelemetry } from '../src/config.js';
import { _resetContext } from '../src/context.js';
import { _resetRootLogger, makeWriteHook } from '../src/logger.js';
import * as otelLogs from '../src/otel-logs.js';
import { redactSecretSpans, registerSecretPattern, resetPiiRulesForTests } from '../src/pii.js';

beforeEach(() => {
  _resetConfig();
  _resetRootLogger();
  _resetContext();
});

afterEach(() => {
  _resetConfig();
  _resetRootLogger();
  _resetContext();
  resetPiiRulesForTests();
  vi.restoreAllMocks();
});

describe('logger message PII — cross-language regression', () => {
  it('redacts a known secret embedded in the message string when logSanitize=true', () => {
    setupTelemetry({ serviceName: 'test-svc', logLevel: 'info', logSanitize: true });
    const spy = vi.spyOn(otelLogs, 'emitLogRecord').mockImplementation(() => {});
    const hook = makeWriteHook();
    hook({ level: 30, message: 'token AKIAIOSFODNN7EXAMPLE leaked' }); // pragma: allowlist secret
    expect(spy).toHaveBeenCalledOnce();
    const record = spy.mock.calls[0][0] as Record<string, unknown>;
    // Span-scoped since 2026-08-16: the credential token is replaced and the
    // surrounding words survive. The contract these tests defend -- the secret
    // must not reach the log -- is asserted above; blanking the whole message
    // was the old mechanism, not the requirement.
    expect(record['message']).toBe('token *** leaked');
    spy.mockRestore();
  });

  it('passes the message through unchanged when logSanitize=false', () => {
    setupTelemetry({ serviceName: 'test-svc', logLevel: 'info', logSanitize: false });
    const spy = vi.spyOn(otelLogs, 'emitLogRecord').mockImplementation(() => {});
    const hook = makeWriteHook();
    hook({ level: 30, message: 'token AKIAIOSFODNN7EXAMPLE leaked' }); // pragma: allowlist secret
    expect(spy).toHaveBeenCalledOnce();
    const record = spy.mock.calls[0][0] as Record<string, unknown>;
    expect(record['message']).toBe('token AKIAIOSFODNN7EXAMPLE leaked'); // pragma: allowlist secret
    spy.mockRestore();
  });

  it('redacts a registered custom secret pattern embedded in the message string', () => {
    registerSecretPattern('internal_token', /INTSECRET-[A-Z0-9]{12,}/);
    setupTelemetry({ serviceName: 'test-svc', logLevel: 'info', logSanitize: true });
    const spy = vi.spyOn(otelLogs, 'emitLogRecord').mockImplementation(() => {});
    const hook = makeWriteHook();
    hook({ level: 30, message: 'token INTSECRET-ABC123XYZ789 leaked' });
    expect(spy).toHaveBeenCalledOnce();
    const record = spy.mock.calls[0][0] as Record<string, unknown>;
    expect(record['message']).toBe('token *** leaked');
    spy.mockRestore();
  });

  it('leaves a message without secret patterns unchanged when logSanitize=true', () => {
    setupTelemetry({ serviceName: 'test-svc', logLevel: 'info', logSanitize: true });
    const spy = vi.spyOn(otelLogs, 'emitLogRecord').mockImplementation(() => {});
    const hook = makeWriteHook();
    hook({ level: 30, message: 'user login succeeded' });
    expect(spy).toHaveBeenCalledOnce();
    const record = spy.mock.calls[0][0] as Record<string, unknown>;
    expect(record['message']).toBe('user login succeeded');
    spy.mockRestore();
  });
});

describe('span-scoped redaction', () => {
  it('removes a whole credential even when the pattern matches only part of it', () => {
    // The jwt pattern matches header.payload; a JWT has THREE dot-separated
    // parts, so redacting the literal match alone would publish the signature.
    const jwt =
      'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9' +
      '.eyJzdWIiOiIxMjM0NTY3ODkwIn0' +
      '.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c';
    const signature = jwt.split('.')[2];

    const out = redactSecretSpans(`auth header ${jwt} rejected`);

    expect(out).not.toContain(signature);
    expect(out).toBe('auth header *** rejected');
  });

  it('removes a credential glued to a prefix at the very start of the value', () => {
    // Every other test puts the secret at a token boundary, where the leftward
    // widening never has to move. Here the match starts five characters in and
    // the token starts the value, so widening must run all the way to index 0.
    //
    // The secret is an AWS key rather than the JWT deliberately: "abcde" plus a
    // JWT header is 41 alphanumeric characters, which long_base64 matches from
    // index 0 on its own. That span has an empty head, so it is immune to a
    // wrong leftward offset and masks the one being tested.
    const secret = 'AKIAIOSFODNN7EXAMPLE'; // pragma: allowlist secret

    const out = redactSecretSpans(`abcde${secret} tail`);

    expect(out).not.toContain(secret);
    expect(out).toBe('*** tail');
  });

  it('leaves a filesystem path alone', () => {
    const line = 'make -C /home/deploy/apps/production/current/native/capture install';
    expect(redactSecretSpans(line)).toBe(line);
  });

  it('redacts every secret in a value, not just the first', () => {
    // Whole-value blanking covered every credential in a field for free.
    // Scoping redaction to one token dropped that guarantee silently: the
    // field is still flagged, but only the first secret goes.
    const first = 'AKIAIOSFODNN7EXAMPLE'; // pragma: allowlist secret
    const second = 'AKIAIOSFODNN7EXAMPLB'; // pragma: allowlist secret

    const out = redactSecretSpans(`first ${first} second ${second}`);

    expect(out).not.toContain(first);
    expect(out).not.toContain(second);
    expect(out).toBe('first *** second ***');
  });

  it('redacts nothing for a pattern that matches the empty string', () => {
    // Scanning every match means a pattern that can match the empty string
    // yields one at every position. Without a guard the walk either never
    // ends or widens a zero-length match to whatever token it landed in,
    // blanking a word that holds no secret.
    registerSecretPattern('empty_matcher', /Z*/);
    const clean = 'the quick brown fox jumps over it';
    expect(redactSecretSpans(clean)).toBe(clean);
  });

  it('does not let a path shadow a secret later in the value', () => {
    // long_base64 matches the path first. Suppressing that match as
    // path-shaped moved the scan on to the next pattern, and long_base64 is
    // the last one, so the real secret behind the path was never looked for.
    // A path prefix must not be a redaction bypass.
    const path = '/home/deploy/apps/production/current/lib/service';
    const secret = 'c2VjcmV0a2V5MTIzNDU2Nzg5MGFiY2RlZmdoaWprbG1ub3A'; // pragma: allowlist secret

    const out = redactSecretSpans(`${path} ${secret}`);

    expect(out).not.toContain(secret);
    expect(out).toBe(`${path} ***`);
  });
});
