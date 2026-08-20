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

export function loadConsentFromEnv(): void {
  const raw = (process.env['PROVIDE_CONSENT_LEVEL'] ?? 'FULL').trim().toUpperCase() as ConsentLevel;
  const valid: ConsentLevel[] = ['FULL', 'FUNCTIONAL', 'MINIMAL', 'NONE'];
  if (valid.includes(raw)) {
    _consentLevel = raw;
  }
}

export function resetConsentForTests(): void {
  _consentLevel = 'FULL';
}
