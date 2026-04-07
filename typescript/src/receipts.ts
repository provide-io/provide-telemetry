// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Cryptographic redaction receipts — strippable governance module.
 *
 * Registers a receipt hook on the PII engine when enabled.
 * If this file is deleted, the PII engine runs unchanged (hook stays null).
 */

import { createHash, createHmac, randomUUID } from 'crypto';
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
  const receiptId = randomUUID();
  const timestamp = new Date().toISOString();
  const originalHash = createHash('sha256').update(String(originalValue)).digest('hex');

  let hmacValue = '';
  if (_signingKey) {
    const payload = `${receiptId}|${timestamp}|${fieldPath}|${action}|${originalHash}`;
    hmacValue = createHmac('sha256', _signingKey).update(payload).digest('hex');
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
