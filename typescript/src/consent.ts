// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Consent-aware telemetry collection.
 * When deleted, all signals pass through unchanged.
 */

import { LogSeverity, levelOrder } from './levels.js';

export type ConsentLevel = 'FULL' | 'FUNCTIONAL' | 'MINIMAL' | 'NONE';

// Stryker disable next-line StringLiteral: initial value is overwritten by resetConsentForTests before any test observes it
let _consentLevel: ConsentLevel = 'FULL';

export function setConsentLevel(level: ConsentLevel): void {
  _consentLevel = level;
}

export function getConsentLevel(): ConsentLevel {
  return _consentLevel;
}

export function shouldAllow(signal: string, logLevel?: string): boolean {
  const level = _consentLevel;
  if (level === 'FULL') return true;
  if (level === 'NONE') return false;
  if (level === 'FUNCTIONAL') {
    if (signal === 'logs') {
      return levelOrder(logLevel) >= LogSeverity.Warn;
    }
    if (signal === 'context') return false;
    return true;
  }
  // MINIMAL
  if (signal === 'logs') {
    return levelOrder(logLevel) >= LogSeverity.Error;
  }
  return false;
}

const _CONSENT_ENV_VAR = 'PROVIDE_CONSENT_LEVEL';
const _VALID_LEVELS: readonly ConsentLevel[] = ['FULL', 'FUNCTIONAL', 'MINIMAL', 'NONE'];

/** Read PROVIDE_CONSENT_LEVEL, or undefined when unset or outside a Node-like runtime. */
// Stryker disable BlockStatement
function _rawConsentEnv(): string | undefined {
  try {
    // process.env is not available in browser builds after tree-shaking,
    // but some bundlers (esbuild, Vite) leave process.env.X inline replacements.
    // Stryker disable next-line ConditionalExpression,StringLiteral: process is always defined in Node.js/test environments
    return typeof process !== 'undefined' ? process.env[_CONSENT_ENV_VAR] : undefined;
  } catch {
    return undefined;
  }
}
// Stryker enable BlockStatement

/**
 * Apply `PROVIDE_CONSENT_LEVEL` to the active consent level.
 *
 * The value is trimmed and upper-cased; FULL, FUNCTIONAL, MINIMAL and NONE
 * are applied. An unset or blank (empty or whitespace-only) variable leaves
 * the current level untouched — it never resets to FULL — so a level set
 * programmatically survives a later call from setup or the lazy logger. A
 * set, non-empty, unrecognised value fails closed: consent becomes NONE and a
 * warning naming the raw value goes to `console.warn` once per process,
 * outside the SDK's own logger so the NONE it just applied cannot drop it.
 * The variable is an opt-out control, and the one failure an opt-out must not
 * have is a typo that silently leaves collection on. Every SDK shares this
 * rule.
 *
 * Called by setupTelemetry / setupTelemetryAsync, and by the lazy logger path
 * before any setup has run.
 */
export function loadConsentFromEnv(): void {
  const raw = _rawConsentEnv();
  if (raw === undefined) return;
  const candidate = raw.trim().toUpperCase();
  if (candidate === '') return;
  if ((_VALID_LEVELS as readonly string[]).includes(candidate)) {
    _consentLevel = candidate as ConsentLevel;
    return;
  }
  _consentLevel = 'NONE';
  _warnInvalidConsentEnvOnce(raw);
}

let _invalidEnvWarned = false;

function _warnInvalidConsentEnvOnce(raw: string): void {
  if (_invalidEnvWarned) return;
  _invalidEnvWarned = true;
  console.warn(
    `[provide-telemetry] ${_CONSENT_ENV_VAR}="${raw}" is not one of FULL, FUNCTIONAL, MINIMAL, NONE; consent set to NONE (fail-closed)`,
  );
}

export function resetConsentForTests(): void {
  _consentLevel = 'FULL';
  _invalidEnvWarned = false;
}
