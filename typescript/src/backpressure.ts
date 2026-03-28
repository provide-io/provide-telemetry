// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Bounded queue controls for telemetry signal paths.
 * Mirrors Python provide.telemetry.backpressure.
 */

import { _droppedField, _incrementHealth } from './health';

export interface QueuePolicy {
  maxLogs: number;
  maxTraces: number;
  maxMetrics: number;
}

export interface QueueTicket {
  signal: 'logs' | 'traces' | 'metrics';
  token: number;
}

const DEFAULT_POLICY: QueuePolicy = { maxLogs: 0, maxTraces: 0, maxMetrics: 0 };

let _policy: QueuePolicy = { ...DEFAULT_POLICY };
let _tokenCounter = 1;
const _acquired: Map<string, Set<number>> = new Map([
  ['logs', new Set()],
  ['traces', new Set()],
  ['metrics', new Set()],
]);

export function setQueuePolicy(policy: Partial<QueuePolicy>): void {
  _policy = { ..._policy, ...policy };
}

export function getQueuePolicy(): QueuePolicy {
  return { ..._policy };
}

function _maxFor(signal: QueueTicket['signal']): number {
  if (signal === 'logs') return _policy.maxLogs;
  if (signal === 'traces') return _policy.maxTraces;
  return _policy.maxMetrics;
}

export function tryAcquire(signal: QueueTicket['signal']): QueueTicket | null {
  const max = _maxFor(signal);
  if (max <= 0) return { signal, token: 0 };
  const set = _acquired.get(signal);
  /* v8 ignore next */
  if (!set) return null;
  if (set.size >= max) return null;
  const token = _tokenCounter++;
  set.add(token);
  return { signal, token };
}

export function release(ticket: QueueTicket): void {
  // Stryker disable next-line ConditionalExpression: token=0 is the unlimited-queue sentinel; delete(0) from set is always a no-op
  if (ticket.token === 0) return;
  // Stryker disable next-line OptionalChaining: signal is always a key in _acquired (initialized in the Map constructor)
  _acquired.get(ticket.signal)?.delete(ticket.token);
}

export function _resetBackpressureForTests(): void {
  _policy = { ...DEFAULT_POLICY };
  _tokenCounter = 1;
  for (const set of _acquired.values()) set.clear();
}
