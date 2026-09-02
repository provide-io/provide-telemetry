// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"log/slog"
	"runtime"
	"strings"
)

// Canonical callsite field names.
//
// The record fields are gated by PROVIDE_LOG_INCLUDE_CALLER, the code.*
// attributes by PROVIDE_LOG_CODE_ATTRIBUTES, and the two gates are independent:
// they select different outputs from one capture, so asking for code attributes
// alone must not drag filename/lineno onto the record and vice versa.
//
// code.filepath and code.lineno were deprecated in semconv 1.27 and are not
// emitted; code.namespace is not emitted either, having no cross-language
// meaning — Go's frame name is already fully qualified.
const (
	_fieldFilename        = "filename"
	_fieldLineno          = "lineno"
	_attrCodeFilePath     = "code.file.path"
	_attrCodeFunctionName = "code.function.name"
	_attrCodeLineNumber   = "code.line.number"
)

// _callsiteFrame resolves the frame a record's program counter points at.
//
// slog captures the PC in Logger.log, before any handler runs, so it names the
// caller of Info/Warn/Log rather than anything inside this SDK — the processor
// chain only has to preserve it, which every rebuild in logger.go does by
// passing r.PC to slog.NewRecord.
//
// Two PCs carry no callsite: the zero value, which is what a hand-built
// slog.NewRecord(..., 0) carries and what slog itself uses when PC capture is
// disabled, and one the runtime cannot map to a function. Both report false
// rather than a frame, so a record gets no callsite fields at all instead of an
// empty filename and a zero line number.
func _callsiteFrame(pc uintptr) (runtime.Frame, bool) {
	if pc == 0 {
		return runtime.Frame{}, false
	}
	frame, _ := runtime.CallersFrames([]uintptr{pc}).Next()
	if frame.File == "" {
		return runtime.Frame{}, false
	}
	return frame, true
}

// _callsiteBaseName reduces a source path to its final component.
//
// The record field is deliberately a base name: runtime.Frame.File is the
// absolute path the file had on the machine that compiled the binary, so
// reporting it whole stamps that machine's directory layout onto every record
// the process ever emits. Both separators are trimmed because a Windows build
// can record either.
func _callsiteBaseName(file string) string {
	normalized := strings.ReplaceAll(file, `\`, "/")
	if idx := strings.LastIndex(normalized, "/"); idx >= 0 {
		return normalized[idx+1:]
	}
	return normalized
}

// applyCallsite attaches the caller's file, line and function to the record,
// in whichever of the two shapes the config asked for.
//
// It runs at the end of the processor chain, after sanitization, for the same
// reason Python appends CallsiteParameterAdder after sanitize_sensitive_fields:
// a source path is not user data, and passing it through hardening would let the
// attribute-count cap or value truncation mangle it.
//
// The fields are attached here, in the shared middleware, rather than through
// slog.HandlerOptions.AddSource on the base handler. AddSource emits a `source`
// group of {function, file, line}, which is not the canonical shape and would
// have to be taken apart again in ReplaceAttr; more decisively, HandlerOptions
// reaches only the JSON and text renderers. The pretty renderer builds no
// HandlerOptions at all and the backend log bridge is a sibling handler under
// multiHandler, so both would have been left without a callsite. Attaching to
// the record instead means all three renderers and the OTLP bridge see the same
// fields.
func (h *_telemetryHandler) applyCallsite(r slog.Record) slog.Record {
	logging := h.cfg.Logging
	if !logging.IncludeCaller && !logging.LogCodeAttributes {
		return r
	}
	frame, ok := _callsiteFrame(r.PC)
	if !ok {
		return r
	}
	callsite := _callsiteAttrs(frame, logging)

	// The callsite shadows a caller's own attribute of the same name. This is
	// the only processor that runs after applyPII, and applyPII is where every
	// earlier step's duplicate keys are collapsed by its map round trip — so
	// appending blindly is the one way this chain can emit a key twice, and
	// `filename` is an ordinary thing for an application to log. Python resolves
	// the same collision the same way, by assigning into the event dict.
	shadowed := make(map[string]struct{}, len(callsite))
	for _, a := range callsite {
		shadowed[a.Key] = struct{}{}
	}

	nr := slog.NewRecord(r.Time, r.Level, r.Message, r.PC)
	r.Attrs(func(a slog.Attr) bool {
		if _, taken := shadowed[a.Key]; !taken {
			nr.AddAttrs(a)
		}
		return true
	})
	nr.AddAttrs(callsite...)
	return nr
}

// _callsiteAttrs renders frame into whichever of the two field shapes the
// logging config asked for. Both, one, or — when neither gate is on, which
// applyCallsite has already ruled out — none.
func _callsiteAttrs(frame runtime.Frame, logging LoggingConfig) []slog.Attr {
	attrs := make([]slog.Attr, 0, 5)
	if logging.IncludeCaller {
		attrs = append(attrs,
			slog.String(_fieldFilename, _callsiteBaseName(frame.File)),
			slog.Int(_fieldLineno, frame.Line),
		)
	}
	if logging.LogCodeAttributes {
		attrs = append(attrs,
			slog.String(_attrCodeFilePath, frame.File),
			slog.String(_attrCodeFunctionName, frame.Function),
			slog.Int(_attrCodeLineNumber, frame.Line),
		)
	}
	return attrs
}
