// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"log/slog"
	"slices"
	"sync"
)

// Reporting reserved root fields whose caller value a stamped value replaced
// (reserved_root_fields.replacement_reporting in spec/telemetry-api.yaml).
//
// Replacing a field silently loses the caller's data — a "version" meaning a
// schema version, say — so each replacement adds to
// HealthSnapshot.ReservedFieldReplacements, and the first replacement of each
// field in the process logs one warning naming the field, never its value.
//
// Handle stamps before admission and reports after it, so a record refused by
// consent, sampling or backpressure is neither counted nor warned about. The
// warning goes through the same handler just before the record it explains.

const _reservedWarningEvent = "logger.reserved_field.replaced"

// _reservedWarningLogger names the warning's logger, as the other SDKs do.
const _reservedWarningLogger = "provide.telemetry.logger"

// _reservedWireOrder is the canonical order replacements are warned about in.
var _reservedWireOrder = []string{_wireService, _wireEnv, _wireVersion, _wireTraceID, _wireSpanID}

var (
	_reservedWarnedMu sync.Mutex
	_reservedWarned   = map[string]bool{}
)

// _reservedWarningKey marks the context of a warning record. The warning is an
// ordinary record and runs the same stamping, so a reserved field bound to the
// caller's context would otherwise count again, against a record the caller
// never wrote.
type _reservedWarningKey struct{}

// _replacedRootFields returns the wire names of the stamped fields that
// replace a different caller value on r, under either spelling.
func _replacedRootFields(r slog.Record, stamped []slog.Attr) []string {
	var replaced []string
	r.Attrs(func(a slog.Attr) bool {
		for _, s := range stamped {
			wire := _reservedWireNames[s.Key]
			if (s.Key == a.Key || wire == a.Key) && !a.Value.Resolve().Equal(s.Value) && !slices.Contains(replaced, wire) {
				replaced = append(replaced, wire)
			}
		}
		return true
	})
	return replaced
}

// reportReservedReplacements counts replaced and logs a warning for each field
// replaced for the first time in this process.
func (h *_telemetryHandler) reportReservedReplacements(ctx context.Context, r slog.Record, replaced []string) {
	if len(replaced) == 0 || ctx.Value(_reservedWarningKey{}) != nil {
		return
	}
	_reservedReplaced.Add(int64(len(replaced)))
	first := _firstReservedWarnings(replaced)
	if len(first) == 0 {
		return
	}
	warner := h.clone()
	warner.bound = nil
	warner.name = _reservedWarningLogger
	wctx := context.WithValue(ctx, _reservedWarningKey{}, true)
	for _, field := range first {
		wr := slog.NewRecord(r.Time, slog.LevelWarn, _reservedWarningEvent, 0)
		wr.AddAttrs(slog.String("field", field))
		_ = warner.Handle(wctx, wr)
	}
}

// _firstReservedWarnings marks and returns, in canonical order, the fields in
// replaced that have not been warned about yet.
func _firstReservedWarnings(replaced []string) []string {
	_reservedWarnedMu.Lock()
	defer _reservedWarnedMu.Unlock()
	var first []string
	for _, field := range _reservedWireOrder {
		if slices.Contains(replaced, field) && !_reservedWarned[field] {
			_reservedWarned[field] = true
			first = append(first, field)
		}
	}
	return first
}

func _resetReservedWarnings() {
	_reservedWarnedMu.Lock()
	defer _reservedWarnedMu.Unlock()
	clear(_reservedWarned)
}
