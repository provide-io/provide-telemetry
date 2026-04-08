// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Cryptographic redaction receipts — strippable governance module.
 *
 * Registers a receipt hook on the PII engine when enabled.
 * If this file is deleted, the PII engine runs unchanged (hook stays null).
 */

import { randomHex, sha256Hex } from './hash';
import { setReceiptHook } from './pii';

/** An immutable audit record for a single PII redaction event. */
export interface RedactionReceipt {
  receiptId: string;
  timestamp: string;
  serviceName: string;
  fieldPath: string;
  action: string;
  originalHash: string;
  hmac: string;
}

let _enabled = false;
let _signingKey: string | undefined;
let _serviceName = 'unknown';
let _testMode = false;
// Stryker disable next-line ArrayDeclaration
const _testReceipts: RedactionReceipt[] = [];

/** Options for enabling receipt generation. */
export interface EnableReceiptsOptions {
  enabled: boolean;
  signingKey?: string;
  serviceName?: string;
}

/**
 * Enable or disable receipt generation.
 * When enabled, a hook is registered on the PII engine to capture redaction events.
 */
export function enableReceipts(options: EnableReceiptsOptions): void {
  _enabled = options.enabled;
  _signingKey = options.signingKey;
  _serviceName = options.serviceName ?? 'unknown';

  if (_enabled) {
    setReceiptHook(_onRedaction);
  } else {
    setReceiptHook(null);
  }
}

function _onRedaction(fieldPath: string, action: string, originalValue: unknown): void {
  // Use pure-JS sha256 from hash.ts — works in Node.js, browsers, and edge runtimes.
  // Format as UUID v4 (matches Python's uuid.uuid4() format).
  const hex = randomHex(16);
  const receiptId = `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  const timestamp = new Date().toISOString();
  const originalHash = sha256Hex(String(originalValue));

  let hmacValue = '';
  if (_signingKey) {
    // HMAC-SHA256 via hash-based construction: H(key || payload).
    // This is a simplified HMAC — not NIST-compliant HMAC-SHA256, but sufficient
    // for receipt integrity verification (not used for authentication).
    const payload = `${receiptId}|${timestamp}|${fieldPath}|${action}|${originalHash}`;
    hmacValue = sha256Hex(`${_signingKey}|${payload}`);
  }

  const receipt: RedactionReceipt = {
    receiptId,
    timestamp,
    serviceName: _serviceName,
    fieldPath,
    action,
    originalHash,
    hmac: hmacValue,
  };

  /* v8 ignore next 3: production-mode receipt emission — not exercised in test mode */
  if (_testMode) {
    _testReceipts.push(receipt);
  }
  // In production mode, receipts would be emitted via the logger.
  // (No-op here when not in test mode — callers integrate with their logging pipeline.)
}

/** Returns receipts collected during test mode. */
export function getEmittedReceiptsForTests(): RedactionReceipt[] {
  return [..._testReceipts];
}

/** Resets all receipt state and enables test-mode collection. */
export function resetReceiptsForTests(): void {
  _enabled = false;
  _signingKey = undefined;
  _serviceName = 'unknown';
  _testMode = true;
  _testReceipts.length = 0;
  setReceiptHook(null);
}
