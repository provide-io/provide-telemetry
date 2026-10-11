// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Stage names of the canonical signal pipeline, spec/pipeline_fixtures.yaml,
 * and the test-only hook that reports them.
 *
 * hardening, pii, receipt and local have no reporting call: each leaves a mark
 * on the record or the sinks that a test can read directly. The gates, the
 * backend bridge and the bookkeeping around them report here, because an
 * admission refusal leaves no mark anywhere else — without the hook a test can
 * see that a record was refused but not which stages ran around the refusal.
 */

export type PipelineStage =
  'consent' | 'sampling' | 'backpressure' | 'backend' | 'health' | 'release';

let _hook: ((stage: PipelineStage) => void) | null = null;

/** Install, or with null remove, the stage hook. Test-only seam, as in C# and Go. */
export function _setPipelineStageHook(hook: ((stage: PipelineStage) => void) | null): void {
  _hook = hook;
}

export function pipelineStage(stage: PipelineStage): void {
  if (_hook !== null) _hook(stage);
}

/**
 * End a path admission control refused. The gate that refused has already
 * counted the drop, and no ticket was taken, so the release is the ticket
 * accounting the fixture requires on every path rather than a queue operation.
 */
export function closeRefused(): void {
  pipelineStage('health');
  pipelineStage('release');
}
