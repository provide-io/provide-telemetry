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

  it('leaves a filesystem path alone', () => {
    const line = 'make -C /home/deploy/apps/production/current/native/capture install';
    expect(redactSecretSpans(line)).toBe(line);
  });
});
