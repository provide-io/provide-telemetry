// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import "sync/atomic"

// Stage names of the canonical signal pipeline, spec/pipeline_fixtures.yaml.
// hardening, pii, receipt, local and backend have no constant: each leaves a
// mark on the record or the sinks that a test can read directly, so only the
// gates and the bookkeeping around them report through the hook below.
const (
	_stageConsent      = "consent"
	_stageSampling     = "sampling"
	_stageBackpressure = "backpressure"
	_stageHealth       = "health"
	_stageRelease      = "release"
)

// _pipelineStageHook, when set, is told each gate and bookkeeping stage as the
// logs pipeline passes it. Test-only seam, as in the C# SDK: an admission
// refusal leaves no mark on any sink, so without it a test can see that a
// record was refused but not which stages ran before and after the refusal.
var _pipelineStageHook atomic.Pointer[func(string)]

func _pipelineStage(stage string) {
	if hook := _pipelineStageHook.Load(); hook != nil {
		(*hook)(stage)
	}
}

// _closeRefusedLog ends a path that admission control refused. The drop has
// already been counted by the gate that refused it, and no ticket was taken,
// so the release is the ticket accounting the fixture requires on every path
// rather than a queue operation.
func _closeRefusedLog() {
	_pipelineStage(_stageHealth)
	_pipelineStage(_stageRelease)
}
