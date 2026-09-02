// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
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

// applyCallsite attaches the caller's file and line to the record.
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
	if !h.cfg.Logging.IncludeCaller {
		return r
	}
	frame, ok := _callsiteFrame(r.PC)
	if !ok {
		return r
	}
	return _withCallsiteAttrs(r, []slog.Attr{
		slog.String(_fieldFilename, _callsiteBaseName(frame.File)),
		slog.Int(_fieldLineno, frame.Line),
	})
}

// _withCallsiteAttrs returns r with callsite appended, shadowing any attribute
// the caller supplied under one of the same keys.
//
// applyCallsite is the only processor that runs after applyPII, and applyPII is
// where every earlier step's duplicate keys are collapsed by its map round trip
// — so appending blindly is the one way this chain can emit a key twice, and
// `filename` is an ordinary thing for an application to log. Python resolves the
// same collision the same way, by assigning into the event dict.
func _withCallsiteAttrs(r slog.Record, callsite []slog.Attr) slog.Record {
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

// _codeAttrsHandler attaches the OTel code.* attributes on the way to the log
// bridge, and to nothing else.
//
// PROVIDE_LOG_CODE_ATTRIBUTES is specified as "attach code attributes to OTel
// log records", and Python and TypeScript honour that literally: their console
// output carries no code.* key with the knob on, because the attributes are
// added where the OTLP record is built. Attaching them to the slog.Record
// instead would fan them out to every renderer, printing runtime.Frame.File —
// the absolute path the *compiling* machine had — on every local line, which is
// the leak `filename` reports a base name to avoid.
//
// So this wraps the bridge alone. It sits above the bridge and below the
// telemetry handler, which means the record it sees has already been through
// consent, schema, sampling, backpressure, hardening and PII, and still carries
// the PC slog.Logger.log captured.
type _codeAttrsHandler struct {
	next slog.Handler
}

func (h *_codeAttrsHandler) Enabled(ctx context.Context, level slog.Level) bool {
	return h.next.Enabled(ctx, level)
}

func (h *_codeAttrsHandler) Handle(ctx context.Context, r slog.Record) error {
	frame, ok := _callsiteFrame(r.PC)
	if !ok {
		return h.next.Handle(ctx, r)
	}
	return h.next.Handle(ctx, _withCallsiteAttrs(r, []slog.Attr{
		slog.String(_attrCodeFilePath, frame.File),
		slog.String(_attrCodeFunctionName, frame.Function),
		slog.Int(_attrCodeLineNumber, frame.Line),
	}))
}

func (h *_codeAttrsHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	return &_codeAttrsHandler{next: h.next.WithAttrs(attrs)}
}

func (h *_codeAttrsHandler) WithGroup(name string) slog.Handler {
	return &_codeAttrsHandler{next: h.next.WithGroup(name)}
}
