// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Consent-aware telemetry collection — strippable governance module.
 * When deleted, all signals pass through unchanged.
 */

export type ConsentLevel = 'FULL' | 'FUNCTIONAL' | 'MINIMAL' | 'NONE';

const LOG_LEVEL_ORDER: Record<string, number> = {
  TRACE: 0,
  DEBUG: 1,
  INFO: 2,
  WARNING: 3,
  WARN: 3,
  ERROR: 4,
  CRITICAL: 5,
};

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
      const order = LOG_LEVEL_ORDER[(logLevel ?? '').toUpperCase()] ?? 0;
      return order >= LOG_LEVEL_ORDER['WARNING'];
    }
    if (signal === 'context') return false;
    return true;
  }
  // MINIMAL
  if (signal === 'logs') {
    const order = LOG_LEVEL_ORDER[(logLevel ?? '').toUpperCase()] ?? 0;
    return order >= LOG_LEVEL_ORDER['ERROR'];
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
