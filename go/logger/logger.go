// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package logger

import (
	"cmp"
	"context"
	"fmt"
	"log/slog"
	"os"
	"slices"
	"strings"
)

// LevelTrace is a custom slog level below DEBUG for very verbose output.
const LevelTrace = slog.Level(-8)

// Logger is the package-level default logger. Set by Configure.
var Logger *slog.Logger //nolint:gochecknoglobals

// _samplingFn is an optional per-call sampling hook injected by the main package.
// When nil every record is forwarded. Signature: (signal, key string) bool.
var _samplingFn func(signal, key string) bool //nolint:gochecknoglobals

// SetSamplingFunc injects a sampling decision function called for every log record.
// Pass nil to disable (always sample).  The main telemetry package calls this
// during SetupTelemetry to wire in its probabilistic sampler.
func SetSamplingFunc(fn func(signal, key string) bool) { _samplingFn = fn }

// _cfg is the active logging configuration.
var _cfg = DefaultLogConfig() //nolint:gochecknoglobals

// Configure replaces the active logging configuration and rebuilds Logger.
func Configure(cfg LogConfig) {
	// Clone ModuleLevels so callers cannot mutate it after the fact.
	if len(cfg.ModuleLevels) > 0 {
		cloned := make(map[string]string, len(cfg.ModuleLevels))
		for k, v := range cfg.ModuleLevels {
			cloned[k] = v
		}
		cfg.ModuleLevels = cloned
	}
	_cfg = cfg
	_configureLogger(cfg)
}

// _telemetryHandler is a slog.Handler middleware that implements the full
// processor chain: context-field merge → standard fields → trace/span IDs →
// sampling → schema → PII → base handler.
type _telemetryHandler struct {
	next   slog.Handler
	cfg    LogConfig
	name   string
	attrs  []slog.Attr
	groups []string
}

// Enabled reports whether the handler should process records at the given level.
func (h *_telemetryHandler) Enabled(_ context.Context, level slog.Level) bool {
	return level >= _effectiveLevel(h.name, h.cfg)
}

// WithAttrs returns a new handler with the given attributes pre-attached.
func (h *_telemetryHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	cp := h.clone()
	cp.attrs = append(cp.attrs, attrs...)
	cp.next = h.next.WithAttrs(attrs)
	return cp
}

// WithGroup returns a new handler scoped to the named group.
func (h *_telemetryHandler) WithGroup(name string) slog.Handler {
	cp := h.clone()
	cp.groups = append(cp.groups, name)
	cp.next = h.next.WithGroup(name)
	return cp
}

// Handle executes the processor chain and forwards to the base handler.
func (h *_telemetryHandler) Handle(ctx context.Context, r slog.Record) error {
	r = h.applyContextFields(ctx, r)
	r = h.applyStandardFields(r)
	r = h.applyTraceFields(ctx, r)

	if fn := _samplingFn; fn != nil {
		if !fn("logs", r.Message) {
			return nil
		}
	}

	if err := h.applySchema(r); err != nil {
		return nil //nolint:nilerr // schema violation drops the record
	}

	r = h.applyErrorFingerprint(r)
	r = h.applyPII(r)
	return h.next.Handle(ctx, r)
}

func (h *_telemetryHandler) clone() *_telemetryHandler {
	cp := *h
	cp.attrs = append([]slog.Attr(nil), h.attrs...)
	cp.groups = append([]string(nil), h.groups...)
	return &cp
}

func (h *_telemetryHandler) applyContextFields(ctx context.Context, r slog.Record) slog.Record {
	fields := GetBoundFields(ctx)
	if len(fields) == 0 {
		return r
	}
	nr := slog.NewRecord(r.Time, r.Level, r.Message, r.PC)
	r.Attrs(func(a slog.Attr) bool { nr.AddAttrs(a); return true })
	for k, v := range fields {
		nr.AddAttrs(slog.Any(k, v))
	}
	return nr
}

func (h *_telemetryHandler) applyStandardFields(r slog.Record) slog.Record {
	cfg := h.cfg
	if cfg.ServiceName == "" && cfg.Environment == "" && cfg.Version == "" {
		return r
	}
	nr := slog.NewRecord(r.Time, r.Level, r.Message, r.PC)
	r.Attrs(func(a slog.Attr) bool { nr.AddAttrs(a); return true })
	if cfg.ServiceName != "" {
		nr.AddAttrs(slog.String("service.name", cfg.ServiceName))
	}
	if cfg.Environment != "" {
		nr.AddAttrs(slog.String("service.env", cfg.Environment))
	}
	if cfg.Version != "" {
		nr.AddAttrs(slog.String("service.version", cfg.Version))
	}
	return nr
}

func (h *_telemetryHandler) applyTraceFields(ctx context.Context, r slog.Record) slog.Record {
	traceID, spanID := GetTraceContext(ctx)
	if traceID == "" && spanID == "" {
		return r
	}
	nr := slog.NewRecord(r.Time, r.Level, r.Message, r.PC)
	r.Attrs(func(a slog.Attr) bool { nr.AddAttrs(a); return true })
	if traceID != "" {
		nr.AddAttrs(slog.String("trace.id", traceID))
	}
	if spanID != "" {
		nr.AddAttrs(slog.String("span.id", spanID))
	}
	return nr
}

func (h *_telemetryHandler) applySchema(r slog.Record) error {
	if !h.cfg.StrictSchema {
		return nil
	}
	if err := ValidateEventName(true, r.Message); err != nil {
		return err
	}
	if len(h.cfg.RequiredKeys) > 0 {
		attrs := _attrsToMap(r)
		return ValidateRequiredKeys(attrs, h.cfg.RequiredKeys)
	}
	return nil
}

func (h *_telemetryHandler) applyPII(r slog.Record) slog.Record {
	payload := _attrsToMap(r)
	sanitized := SanitizePayload(payload, h.cfg.Sanitize, h.cfg.PIIMaxDepth)
	nr := slog.NewRecord(r.Time, r.Level, r.Message, r.PC)
	for _, a := range _mapToAttrs(sanitized) {
		nr.AddAttrs(a)
	}
	return nr
}

func (h *_telemetryHandler) applyErrorFingerprint(r slog.Record) slog.Record {
	var excName string
	r.Attrs(func(a slog.Attr) bool {
		switch a.Key {
		case "exc_info", "exc_name", "exception":
			excName = fmt.Sprint(a.Value.Any())
			return false
		}
		return true
	})
	if excName == "" {
		return r
	}
	fp := _computeErrorFingerprintFromParts(excName, nil)
	nr := slog.NewRecord(r.Time, r.Level, r.Message, r.PC)
	r.Attrs(func(a slog.Attr) bool { nr.AddAttrs(a); return true })
	nr.AddAttrs(slog.String("error_fingerprint", fp))
	return nr
}

func _attrsToMap(r slog.Record) map[string]any {
	m := make(map[string]any)
	r.Attrs(func(a slog.Attr) bool {
		m[a.Key] = a.Value.Any()
		return true
	})
	return m
}

func _mapToAttrs(m map[string]any) []slog.Attr {
	attrs := make([]slog.Attr, 0, len(m))
	for k, v := range m {
		attrs = append(attrs, slog.Any(k, v))
	}
	return attrs
}

func _effectiveLevel(name string, cfg LogConfig) slog.Level {
	globalLevel := _parseLevel(cfg.Level)
	type _match struct {
		moduleLen int
		level     slog.Level
	}
	var matches []_match
	for module, levelStr := range cfg.ModuleLevels {
		if _isPrefixMatch(name, module) {
			matches = append(matches, _match{len(module), _parseLevel(levelStr)})
		}
	}
	if len(matches) == 0 {
		return globalLevel
	}
	best := slices.MaxFunc(matches, func(a, b _match) int {
		return cmp.Compare(a.moduleLen, b.moduleLen)
	})
	return best.level
}

func _isPrefixMatch(name, module string) bool {
	if module == "" {
		return true
	}
	if name == module {
		return true
	}
	return strings.HasPrefix(name, module+".")
}

func _parseLevel(s string) slog.Level {
	switch strings.ToUpper(strings.TrimSpace(s)) {
	case LogLevelTrace:
		return LevelTrace
	case LogLevelDebug:
		return slog.LevelDebug
	case LogLevelWarn, LogLevelWarning:
		return slog.LevelWarn
	case LogLevelError, LogLevelCritical:
		return slog.LevelError
	default:
		return slog.LevelInfo
	}
}

func _newTelemetryHandler(base slog.Handler, cfg LogConfig, name string) slog.Handler {
	return &_telemetryHandler{next: base, cfg: cfg, name: name}
}

func _configureLogger(cfg LogConfig) {
	opts := &slog.HandlerOptions{Level: LevelTrace}
	var base slog.Handler
	if cfg.Format == LogFormatJSON {
		base = slog.NewJSONHandler(os.Stderr, opts)
	} else {
		base = slog.NewTextHandler(os.Stderr, opts)
	}
	h := _newTelemetryHandler(base, cfg, "")
	Logger = slog.New(h)
	slog.SetDefault(Logger)
}

// GetLogger returns a *slog.Logger with the telemetry handler chain bound to name.
// If ctx carries trace/span IDs (written by SetTraceContext), they are pre-attached
// so they appear on every log line even when callers use the context-free form.
func GetLogger(ctx context.Context, name string) *slog.Logger {
	cfg := _cfg
	opts := &slog.HandlerOptions{Level: LevelTrace}
	var base slog.Handler
	if cfg.Format == LogFormatJSON {
		base = slog.NewJSONHandler(os.Stderr, opts)
	} else {
		base = slog.NewTextHandler(os.Stderr, opts)
	}
	h := _newTelemetryHandler(base, cfg, name)
	l := slog.New(h)
	traceID, spanID := GetTraceContext(ctx)
	if traceID != "" || spanID != "" {
		var attrs []any
		if traceID != "" {
			attrs = append(attrs, slog.String("trace.id", traceID))
		}
		if spanID != "" {
			attrs = append(attrs, slog.String("span.id", spanID))
		}
		return l.With(attrs...)
	}
	return l
}

// IsDebugEnabled returns true if the package-level Logger would emit DEBUG records.
func IsDebugEnabled() bool {
	if Logger == nil {
		return false
	}
	return Logger.Enabled(context.Background(), slog.LevelDebug)
}

// IsTraceEnabled returns true if the package-level Logger would emit TRACE records.
func IsTraceEnabled() bool {
	if Logger == nil {
		return false
	}
	return Logger.Enabled(context.Background(), LevelTrace)
}
