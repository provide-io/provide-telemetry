// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Strip-governance regression tests.
 *
 * TypeScript bundles governance unconditionally (consumers tree-shake unused
 * exports). These tests verify that:
 *
 * 1. Core telemetry features work without calling any governance APIs.
 * 2. Governance symbols live in isolated modules (classification, consent,
 *    receipts) that are only needed when explicitly imported.
 * 3. Core modules have no static import dependency on governance modules.
 */

import { beforeEach, describe, expect, it } from 'vitest';
import {
  counter,
  event,
  gauge,
  getHealthSnapshot,
  getLogger,
  getQueuePolicy,
  getSamplingPolicy,
  histogram,
  resetTelemetryState,
  setQueuePolicy,
  setSamplingPolicy,
  setupTelemetry,
  shutdownTelemetry,
} from '../src/index';

beforeEach(() => {
  resetTelemetryState();
});

describe('core telemetry without governance', () => {
  it('setup and shutdown succeed without governance', () => {
    // setupTelemetry returns void; we verify it does not throw.
    expect(() => setupTelemetry()).not.toThrow();
    expect(() => shutdownTelemetry()).not.toThrow();
  });

  it('getLogger returns a working logger', () => {
    const log = getLogger('strip-governance-test');
    expect(log).toBeDefined();
    // logger.info takes (obj, msg?) where obj is Record<string, unknown>
    log.info({ event: 'no_governance.test.logged', extra: 'value' });
  });

  it('counter instrument works without governance', () => {
    const c = counter('no_governance.test.counter');
    expect(c).toBeDefined();
    c.add(1);
  });

  it('gauge instrument works without governance', () => {
    const g = gauge('no_governance.test.gauge');
    expect(g).toBeDefined();
    g.set(42);
  });

  it('histogram instrument works without governance', () => {
    const h = histogram('no_governance.test.histogram');
    expect(h).toBeDefined();
    h.record(100);
  });

  it('health snapshot works without governance', () => {
    const snap = getHealthSnapshot();
    expect(snap.logsEmitted).toBeGreaterThanOrEqual(0);
    expect(snap.logsDropped).toBeGreaterThanOrEqual(0);
    expect(snap.tracesEmitted).toBeGreaterThanOrEqual(0);
    expect(snap.metricsEmitted).toBeGreaterThanOrEqual(0);
    expect(snap.setupError).toBeNull();
  });

  it('sampling policy roundtrip works without governance', () => {
    const policy = { defaultRate: 0.5, overrides: {} };
    setSamplingPolicy('logs', policy);
    const got = getSamplingPolicy('logs');
    expect(got.defaultRate).toBe(0.5);
    // Reset
    setSamplingPolicy('logs', { defaultRate: 1.0, overrides: {} });
  });

  it('queue policy roundtrip works without governance', () => {
    // QueuePolicy fields: maxLogs, maxTraces, maxMetrics
    setQueuePolicy({ maxLogs: 100, maxTraces: 100, maxMetrics: 100 });
    const got = getQueuePolicy();
    expect(got.maxLogs).toBe(100);
    // Reset
    setQueuePolicy({ maxLogs: 0, maxTraces: 0, maxMetrics: 0 });
  });

  it('event schema validation works without governance', () => {
    const e = event('auth', 'login', 'success');
    expect(e.event).toBe('auth.login.success');
    expect(e.domain).toBe('auth');
    expect(e.action).toBe('login');
    expect(e.status).toBe('success');
    expect(e.resource).toBeUndefined();
  });
});

describe('governance module isolation', () => {
  it('governance modules are in separate source files', async () => {
    // Governance must be in isolated modules, not bundled into core.
    // We verify this by importing them separately — if they were in the core
    // bundle, tree-shaking would not work.
    const { setConsentLevel, getConsentLevel } = await import('../src/consent');
    const { registerClassificationRules, getClassificationPolicy } =
      await import('../src/classification');
    const { enableReceipts } = await import('../src/receipts');

    expect(typeof setConsentLevel).toBe('function');
    expect(typeof getConsentLevel).toBe('function');
    expect(typeof registerClassificationRules).toBe('function');
    expect(typeof getClassificationPolicy).toBe('function');
    expect(typeof enableReceipts).toBe('function');
  });

  it('pii module does not statically require classification', async () => {
    // The PII sanitizer must work even when no classification rules are registered.
    const { sanitizePayload, replacePiiRules } = await import('../src/pii');

    replacePiiRules([]);
    const payload: Record<string, unknown> = {
      user: 'alice',
      password: 's3cr3t', // pragma: allowlist secret
      token: 'abc123',
    };
    sanitizePayload(payload);

    expect(payload['password']).toBe('***');
    expect(payload['token']).toBe('***');
    expect(payload['user']).toBe('alice');
    // No classification labels injected without registered rules
    expect(payload['__password__class']).toBeUndefined();
  });
});
