// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Cryptographic redaction receipts.
 *
 * Registers a receipt hook on the PII engine when enabled.
 * If this file is deleted, the PII engine runs unchanged (hook stays null).
 *
 * This module carries the two cross-language governance contracts:
 *
 *   * **Canonicalization** — the hashed form of a redacted value is its RFC
 *     8785 (JCS) serialization, not `String(value)`. Hashing the display form
 *     collides across types: the string `"1"` and the number `1` produce the
 *     same digest, so a receipt cannot distinguish them. The canonicaliser
 *     itself lives in `canonical-json.ts` (PII hash mode shares it) and is
 *     re-exported here.
 *   * **Signing** — `receipt_id|timestamp|field_path|action|original_hash`
 *     under real HMAC-SHA256, lowercase hex.
 *
 * Both are pinned by `spec/receipt_fixtures.yaml`, whose vectors were produced
 * by independent implementations (`rfc8785` and Python's `hmac`), so passing
 * them means agreeing with the other SDKs rather than agreeing with ourselves.
 */

import { _incrementHealth } from './health.js';
import { hmacSha256Hex, randomHex, sha256Hex } from './hash.js';
import { setReceiptHook } from './pii.js';
import { canonicalJson } from './canonical-json.js';

export { canonicalJson } from './canonical-json.js';

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

/**
 * Destination for governance receipts.
 *
 * `emit` returns false to reject a receipt; returning false or throwing both
 * increment `receiptFailures`. Implementations must not log — see
 * {@link emitReceipt}.
 */
export interface ReceiptSink {
  emit(receipt: RedactionReceipt): boolean;
}

/** Retention cap for {@link TestReceiptCollector}. */
export const TEST_RECEIPT_CAPACITY = 1024;

/**
 * In-memory sink for tests, bounded at {@link TEST_RECEIPT_CAPACITY} receipts.
 *
 * Only the test collector is capped. A production sink is the caller's own
 * durable destination, and silently discarding audit records to stay under a
 * memory budget is not a decision this library gets to make on their behalf.
 */
export class TestReceiptCollector implements ReceiptSink {
  readonly receipts: RedactionReceipt[] = [];

  emit(receipt: RedactionReceipt): boolean {
    if (this.receipts.length === TEST_RECEIPT_CAPACITY) this.receipts.shift();
    this.receipts.push(receipt);
    return true;
  }
}

/** The canonical receipt payload, in the byte order every SDK signs. */
export function receiptPayload(receipt: {
  receiptId: string;
  timestamp: string;
  fieldPath: string;
  action: string;
  originalHash: string;
}): string {
  return [
    receipt.receiptId,
    receipt.timestamp,
    receipt.fieldPath,
    receipt.action,
    receipt.originalHash,
  ].join('|');
}

/** Inputs to {@link signReceipt} that a caller pins rather than generates. */
export interface SignReceiptOptions {
  receiptId: string;
  timestamp: string;
  fieldPath: string;
  action: string;
  serviceName?: string;
  /** Signing key. Omit to leave `hmac` empty — an unsigned receipt. */
  key?: Uint8Array;
}

/**
 * Build a receipt over `input`, canonicalizing and signing it.
 *
 * Every identity-bearing field is a parameter rather than being generated
 * here, so the fixture vectors can be reproduced exactly.
 */
export function signReceipt(input: unknown, options: SignReceiptOptions): RedactionReceipt {
  const originalHash = sha256Hex(canonicalJson(input));
  const base = {
    receiptId: options.receiptId,
    timestamp: options.timestamp,
    serviceName: options.serviceName ?? 'unknown',
    fieldPath: options.fieldPath,
    action: options.action,
    originalHash,
  };
  const key = options.key;
  return {
    ...base,
    hmac: key ? hmacSha256Hex(key, new TextEncoder().encode(receiptPayload(base))) : '',
  };
}

/**
 * Hand a receipt to its sink, counting refusals.
 *
 * This path must never log. The logger is what produces redactions, redactions
 * are what produce receipts, and a sink that fails on every receipt would then
 * drive an unbounded log→receipt→log cycle. A rejection is therefore recorded
 * only as a counter, which `getHealthSnapshot().receiptFailures` exposes.
 */
export function emitReceipt(receipt: RedactionReceipt, sink: ReceiptSink): void {
  try {
    if (!sink.emit(receipt)) _incrementHealth('receiptFailures');
  } catch {
    // Counted, never logged, and never rethrown: a sink that throws must not
    // take the caller's log call down with it.
    _incrementHealth('receiptFailures');
  }
}

// Stryker disable next-line BooleanLiteral: initial false is overwritten by resetReceiptsForTests() in every test beforeEach — equivalent mutant
let _enabled = false;
let _signingKey: string | undefined;
// Stryker disable next-line StringLiteral: initial value is overwritten by resetReceiptsForTests() in every test beforeEach — equivalent mutant
let _serviceName = 'unknown';
// Stryker disable next-line BooleanLiteral: initial false is overwritten by resetReceiptsForTests() in every test beforeEach — equivalent mutant
let _testMode = false;
let _sink: ReceiptSink | null = null;
const _testCollector = new TestReceiptCollector();

/** Options for enabling receipt generation. */
export interface EnableReceiptsOptions {
  enabled: boolean;
  signingKey?: string;
  serviceName?: string;
  /** Required outside test mode: where accepted receipts are delivered. */
  sink?: ReceiptSink;
}

/** Thrown when receipts are enabled in production without a delivery sink. */
export class MissingReceiptSinkError extends Error {
  constructor() {
    super(
      'receipts are enabled but no receiptSink is configured; ' +
        'generated receipts would be computed and then discarded. ' +
        'Pass a ReceiptSink, or disable receipts.',
    );
    this.name = 'MissingReceiptSinkError';
  }
}

/**
 * Enable or disable receipt generation.
 * When enabled, a hook is registered on the PII engine to capture redaction events.
 *
 * Enabling receipts outside test mode without a sink throws: the previous
 * behavior computed a full signed receipt for every redaction and then dropped
 * it on the floor, so a service could believe it had an audit trail and have
 * none.
 */
export function enableReceipts(options: EnableReceiptsOptions): void {
  if (options.enabled && !_testMode && !options.sink) {
    throw new MissingReceiptSinkError();
  }
  _enabled = options.enabled;
  _signingKey = options.signingKey;
  _serviceName = options.serviceName ?? 'unknown';
  _sink = options.sink ?? null;

  if (_enabled) {
    setReceiptHook(_onRedaction);
  } else {
    setReceiptHook(null);
  }
}

function _onRedaction(fieldPath: string, action: string, originalValue: unknown): void {
  // Format as UUID v4 (matches Python's uuid.uuid4() format).
  const hex = randomHex(16);
  const receiptId = `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  const receipt = signReceipt(originalValue, {
    receiptId,
    timestamp: new Date().toISOString(),
    fieldPath,
    action,
    serviceName: _serviceName,
    key: _signingKey ? new TextEncoder().encode(_signingKey) : undefined,
  });

  // In test mode the built-in collector stands in for a configured sink so the
  // suite never has to run the un-sinked path this module now rejects.
  emitReceipt(receipt, _testMode ? _testCollector : (_sink as ReceiptSink));
}

/** Returns receipts collected during test mode. */
export function getEmittedReceiptsForTests(): RedactionReceipt[] {
  return [..._testCollector.receipts];
}

/** Override _testMode for coverage testing. */
export function _setTestModeForTests(mode: boolean): void {
  _testMode = mode;
}

/** Resets all receipt state and enables test-mode collection. */
export function resetReceiptsForTests(): void {
  // Stryker disable next-line BooleanLiteral: _enabled only gates hook registration in enableReceipts(); reset also calls setReceiptHook(null) so enabled=true has no effect — equivalent
  _enabled = false;
  _signingKey = undefined;
  // Stryker disable next-line StringLiteral: reset serviceName is overwritten by enableReceipts() in every test that checks it — equivalent mutant
  _serviceName = 'unknown';
  _testMode = true;
  _sink = null;
  _testCollector.receipts.length = 0;
  setReceiptHook(null);
}
