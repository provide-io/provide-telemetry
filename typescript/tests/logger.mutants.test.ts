// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Targeted mutation-killing tests for `src/logger.ts`.
 *
 * These tests pin behaviour that otherwise looked indistinguishable from
 * Stryker-injected mutants:
 *   - CONSENT_LEVEL_MAP entries per pino level (L42–L48)
 *   - `_rootConfigVersion` initial sentinel (L64)
 *   - consent-gate level-label resolution (L85)
 *   - sampling-key composition from event/message (L90)
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { _resetConfig, setupTelemetry } from '../src/config';
import { _resetContext } from '../src/context';
import * as consent from '../src/consent';
import { resetConsentForTests, setConsentLevel } from '../src/consent';
import { _resetRootLogger, getLogger, makeWriteHook } from '../src/logger';
import { _resetSamplingForTests, setSamplingPolicy } from '../src/sampling';

function freshCfg(overrides?: Parameters<typeof setupTelemetry>[0]) {
  _resetConfig();
  _resetRootLogger();
  _resetContext();
  resetConsentForTests();
  _resetSamplingForTests();
  setupTelemetry({
    serviceName: 'test-svc',
    logLevel: 'trace',
    captureToWindow: true,
    ...overrides,
  });
  (window as unknown as Record<string, unknown>)['__pinoLogs'] = [];
}

beforeEach(() => {
  freshCfg();
});

afterEach(() => {
  _resetConfig();
  _resetRootLogger();
  _resetContext();
  resetConsentForTests();
  _resetSamplingForTests();
  vi.restoreAllMocks();
});

/* -----------------------------------------------------------------------
 * CONSENT_LEVEL_MAP — L42 (ObjectLiteral), L43-L48 (per-level StringLiteral)
 *
 * Kills each pino level → consent-label mapping by forcing a consent
 * threshold that draws the line precisely between two labels, then
 * asserting only the expected level is dropped / allowed.
 * ---------------------------------------------------------------------*/

describe('CONSENT_LEVEL_MAP mapping (pino level → consent label)', () => {
  // Spy on shouldAllow to observe the exact label the hook passes.  This pins
  // per-level StringLiteral mutants that mapped the values to ''.
  const labelsSeen: Array<[string, string | undefined]> = [];
  beforeEach(() => {
    labelsSeen.length = 0;
    vi.spyOn(consent, 'shouldAllow').mockImplementation(
      (signal: string, logLevel?: string): boolean => {
        labelsSeen.push([signal, logLevel]);
        return true;
      },
    );
  });

  it.each([
    [10, 'trace'],
    [20, 'debug'],
    [30, 'info'],
    [40, 'warn'],
    [50, 'error'],
    [60, 'error'],
  ])('level %i resolves to consent label %s', (pinoLevel, expectedLabel) => {
    const hook = makeWriteHook();
    hook({ level: pinoLevel, event: 'level_mapping_probe' });
    const entry = labelsSeen.find(([sig]) => sig === 'logs');
    expect(entry).toBeDefined();
    const [, label] = entry as [string, string | undefined];
    expect(label).toBe(expectedLabel);
  });

  it('unmapped pino level falls through to "info" (kills ?? "" mutant)', () => {
    const hook = makeWriteHook();
    hook({ level: 999, event: 'unmapped_level' });
    const entry = labelsSeen.find(([sig]) => sig === 'logs');
    expect(entry).toBeDefined();
    // Must be the literal 'info' — not '' and not undefined.
    const [, label] = entry as [string, string | undefined];
    expect(label).toBe('info');
  });

  it('map object is non-empty — ObjectLiteral: {} replacement drops every mapping', () => {
    // When CONSENT_LEVEL_MAP is {} every lookup produces undefined, so the
    // fallback becomes 'info' for every level, including level 50 (error).
    // The spy assertion on level 50 → 'error' above would already detect
    // this, but we pin it independently with an in-hook observation.
    const hook = makeWriteHook();
    hook({ level: 50, event: 'err_probe' });
    const last = labelsSeen[labelsSeen.length - 1];
    expect(last[0]).toBe('logs');
    expect(last[1]).toBe('error'); // NOT 'info'
  });
});

/* -----------------------------------------------------------------------
 * CONSENT_LEVEL_MAP — L85 LogicalOperator (?? → &&)
 *
 * With `??`, a defined map value (e.g. 'error') passes through unchanged.
 * With `&&`, any truthy value short-circuits to the RHS ('info'), so the
 * effective label becomes 'info' for every mapped level.  We kill this by
 * using MINIMAL consent + a level-50 record: 'error' would pass, 'info'
 * would be dropped.
 * ---------------------------------------------------------------------*/

describe('consent-gate level label — ?? vs &&', () => {
  it('MINIMAL consent allows level=50 (error) — ?? preserves "error" label', () => {
    setConsentLevel('MINIMAL');
    const hook = makeWriteHook();
    hook({ level: 50, event: 'err.event' });
    const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
    expect(logs).toHaveLength(1);
  });

  it('MINIMAL consent drops level=30 (info)', () => {
    setConsentLevel('MINIMAL');
    const hook = makeWriteHook();
    hook({ level: 30, event: 'info.event' });
    const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
    expect(logs).toHaveLength(0);
  });

  it('FUNCTIONAL consent allows level=40 (warn) but drops level=30 (info)', () => {
    setConsentLevel('FUNCTIONAL');
    const hook = makeWriteHook();
    hook({ level: 40, event: 'warn.event' });
    hook({ level: 30, event: 'info.event' });
    const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
    expect(logs).toHaveLength(1);
    expect((logs[0] as Record<string, unknown>)['event']).toBe('warn.event');
  });
});

/* -----------------------------------------------------------------------
 * L86:22 StringLiteral ""
 *
 * `shouldAllow('logs', ...)` → `shouldAllow('', ...)` would flip the code
 * path inside consent.ts (the '' signal falls into "return false" under
 * FUNCTIONAL / MINIMAL).  Under FULL consent it still returns true, so
 * the NONE case distinguishes: NONE drops 'logs' but, crucially, shouldAllow
 * also returns false for '' under NONE — which is the same result.  The
 * reliable separator is observing the exact signal string passed.
 * ---------------------------------------------------------------------*/

describe('consent-gate signal argument', () => {
  it('passes literal "logs" to shouldAllow', () => {
    const spy = vi.spyOn(consent, 'shouldAllow');
    const hook = makeWriteHook();
    hook({ level: 30, event: 'signal.pin' });
    expect(spy).toHaveBeenCalled();
    const signals = spy.mock.calls.map((c) => c[0]);
    expect(signals).toContain('logs');
    expect(signals).not.toContain('');
  });
});

/* -----------------------------------------------------------------------
 * L64 UnaryOperator — `let _rootConfigVersion = -1`
 *
 * Mutated to `+1`.  _resetRootLogger() sets version back to -1; the very
 * first getLogger() after reset must rebuild because the cached version
 * will not equal getConfig()'s version (which is >= 1 after setupTelemetry).
 * If the sentinel were +1 and config version happened to equal 1 (first
 * setup), the cache check `_root && _rootConfigVersion === currentVersion`
 * would be TRUE even though _root was nulled, BUT since we also null _root
 * in _resetRootLogger the behaviour is preserved.  We instead pin the
 * sentinel by forcing a config-version change AFTER obtaining a logger
 * and observing that the root is rebuilt with the new serviceName.
 * ---------------------------------------------------------------------*/

describe('_rootConfigVersion sentinel (L64 UnaryOperator -1 → +1)', () => {
  // When the module-level sentinel is -1, the very first getLogger() call after
  // _resetRootLogger() cannot hit the `_rootConfigVersion === currentVersion`
  // cache-hit branch because _root is null and currentVersion is >= 1.
  //
  // Under the +1 mutant, if config-version also lands on +1 the cache path
  // would be entered with _root still equal to null, handing back a null
  // logger and producing a TypeError on the first .info() call.  We kill by
  // pinning that the very first call after reset succeeds AND produces a
  // record bound to the configured service name.
  it('first getLogger() after _resetRootLogger() produces a functioning logger with configured service', () => {
    freshCfg({ serviceName: 'sentinel-svc' });
    _resetRootLogger();
    const log = getLogger('probe.sentinel');
    expect(log).toBeDefined();
    log.info({ event: 'sentinel.ok' }, 'sentinel.ok');
    const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
    expect(logs.length).toBeGreaterThan(0);
    const last = logs[logs.length - 1] as Record<string, unknown>;
    expect(last['service']).toBe('sentinel-svc');
    expect(last['name']).toBe('probe.sentinel');
  });
});

/* -----------------------------------------------------------------------
 * L90 sampling-key composition
 *
 *   const samplingKey = String(o['event'] ?? o['message'] ?? '');
 *
 *   - L90:62 StringLiteral "Stryker was here!" — '' → "Stryker was here!"
 *   - L90:48 StringLiteral ""                  — 'message' → ''
 *   - L90:34 StringLiteral ""                  — 'event' → ''
 *   - L90:32 LogicalOperator (two variants)    — ?? → &&
 *
 * Strategy: stub shouldSample so its invocation records the exact key, then
 * probe several combinations of event/message presence.
 * ---------------------------------------------------------------------*/

describe('sampling-key composition (L90)', () => {
  it('passes event as sampling key when event is present', () => {
    // Per-event override drops records keyed "evt.a" but allows any other key.
    setSamplingPolicy('logs', { defaultRate: 1.0, overrides: { 'evt.a': 0.0 } });
    const hook = makeWriteHook();
    hook({ level: 30, event: 'evt.a', message: 'fallback msg' });
    hook({ level: 30, event: 'evt.b', message: 'fallback msg' });
    const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
    expect(logs).toHaveLength(1);
    expect((logs[0] as Record<string, unknown>)['event']).toBe('evt.b');
  });

  it('falls back to message when event is absent', () => {
    setSamplingPolicy('logs', { defaultRate: 1.0, overrides: { 'msg.dropped': 0.0 } });
    const hook = makeWriteHook();
    hook({ level: 30, message: 'msg.dropped' });
    hook({ level: 30, message: 'msg.kept' });
    const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
    expect(logs).toHaveLength(1);
    expect((logs[0] as Record<string, unknown>)['message']).toBe('msg.kept');
  });

  it('falls back to empty string when both event and message are absent', () => {
    // Override keyed on "" drops; literal 'Stryker was here!' key would NOT be
    // overridden, distinguishing the StringLiteral mutant on the default.
    setSamplingPolicy('logs', { defaultRate: 1.0, overrides: { '': 0.0 } });
    const hook = makeWriteHook();
    hook({ level: 30 });
    const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
    expect(logs).toHaveLength(0);
  });

  it('default fallback is NOT the Stryker sentinel — an unrelated override does not drop', () => {
    // Pins the StringLiteral: "Stryker was here!" mutant — if the code used the
    // sentinel as the fallback, this override would match and drop the record.
    setSamplingPolicy('logs', {
      defaultRate: 1.0,
      overrides: { 'Stryker was here!': 0.0 },
    });
    const hook = makeWriteHook();
    hook({ level: 30 });
    const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
    expect(logs).toHaveLength(1);
  });

  it('prefers event over message when both present (?? semantics, not &&)', () => {
    // Under `o['event'] && o['message']`, the key would be 'm' (message),
    // so dropping "m" would kill the record.  Under `??`, the key is 'e'
    // and the override "m" has no effect.
    setSamplingPolicy('logs', { defaultRate: 1.0, overrides: { m: 0.0 } });
    const hook = makeWriteHook();
    hook({ level: 30, event: 'e', message: 'm' });
    const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
    expect(logs).toHaveLength(1);
    expect((logs[0] as Record<string, unknown>)['event']).toBe('e');
  });

  it('drops when event override matches, independent of message value', () => {
    // Pins the `(o['event'] ?? o['message']) && ''` mutant: that mutant would
    // always produce key '', so an override on 'e' would never match and the
    // record would be kept.  Under the original, key='e' matches and drops.
    setSamplingPolicy('logs', { defaultRate: 1.0, overrides: { e: 0.0 } });
    const hook = makeWriteHook();
    hook({ level: 30, event: 'e', message: 'm' });
    const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
    expect(logs).toHaveLength(0);
  });
});
