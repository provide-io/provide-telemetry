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

const _VALID_LEVELS: readonly ConsentLevel[] = ['FULL', 'FUNCTIONAL', 'MINIMAL', 'NONE'];

/** Read PROVIDE_CONSENT_LEVEL, or undefined when unset or outside a Node-like runtime. */
// Stryker disable BlockStatement
function _rawConsentEnv(): string | undefined {
  try {
    // process.env is not available in browser builds after tree-shaking,
    // but some bundlers (esbuild, Vite) leave process.env.X inline replacements.
    // Stryker disable next-line ConditionalExpression,StringLiteral: process is always defined in Node.js/test environments
    return typeof process !== 'undefined' ? process.env['PROVIDE_CONSENT_LEVEL'] : undefined;
  } catch {
    return undefined;
  }
}
// Stryker enable BlockStatement

/**
 * Apply `PROVIDE_CONSENT_LEVEL` to the active consent level.
 *
 * The value is trimmed and upper-cased; FULL, FUNCTIONAL, MINIMAL and NONE
 * are applied. An unset or unrecognised variable leaves the current level
 * untouched — it never resets to FULL — so a level set programmatically
 * survives a later call from setup or the lazy logger. Every SDK shares this
 * rule.
 *
 * Called by setupTelemetry / setupTelemetryAsync, and by the lazy logger path
 * before any setup has run.
 */
export function loadConsentFromEnv(): void {
  const raw = _rawConsentEnv();
  if (raw === undefined) return;
  const candidate = raw.trim().toUpperCase();
  if ((_VALID_LEVELS as readonly string[]).includes(candidate)) {
    _consentLevel = candidate as ConsentLevel;
  }
}

export function resetConsentForTests(): void {
  _consentLevel = 'FULL';
}
