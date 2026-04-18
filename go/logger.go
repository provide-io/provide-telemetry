// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"cmp"
	"context"
	"fmt"
	"log/slog"
	"os"
	"slices"
	"strings"

	"go.opentelemetry.io/contrib/bridges/otelslog"
)

// LevelTrace is a custom slog level below DEBUG for very verbose output.
const LevelTrace = slog.Level(-8)

// Logger is the package-level default logger. Set by _configureLogger (called from SetupTelemetry).
var Logger *slog.Logger

// _telemetryHandler is a slog.Handler middleware that implements the full processor chain:
// context-field merge → standard fields → trace/span IDs → sampling → schema → PII → base handler.
type _telemetryHandler struct {
	next   slog.Handler
	cfg    *TelemetryConfig
	name   string
	attrs  []slog.Attr
	groups []string
}

// Enabled reports whether the handler should process records at the given level.
// Per-module level overrides take precedence over the global log level.
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
	r = h.applyLoggerName(r)
	r = h.applyStandardFields(r)
	r = h.applyTraceFields(ctx, r)

	// Consent gate: block before any processing when consent level forbids logs.
	if !ShouldAllow(signalLogs, r.Level.String()) {
		return nil
	}

	// Schema validation runs BEFORE sampling so records flagged by
	// validateRequiredKeys / validateEventName don't inflate LogsEmitted.
	// Annotate with _schema_error instead of dropping — preserves telemetry.
	// Cross-language standard (Python/TypeScript/Rust match).
	if err := h.applySchema(r); err != nil {
		r.AddAttrs(slog.String("_schema_error", err.Error()))
	}

	if sampled, _ := ShouldSample(signalLogs, r.Message); !sampled { // signalLogs is a package-level constant; err is always nil
		return nil
	}

	// Backpressure gate: drop when the log queue is full.
	if !TryAcquire(signalLogs) {
		return nil
	}
	defer Release(signalLogs)
	_incLogsEmitted()

	r = h.applyErrorFingerprint(r)
	r = h.applyPII(r)
	return h.next.Handle(ctx, r)
}

// clone returns a shallow copy of the handler.
func (h *_telemetryHandler) clone() *_telemetryHandler {
	cp := *h
	cp.attrs = append([]slog.Attr(nil), h.attrs...)
	cp.groups = append([]string(nil), h.groups...)
	return &cp
}

// applyLoggerName adds the canonical logger_name field when a named logger is in use.
func (h *_telemetryHandler) applyLoggerName(r slog.Record) slog.Record {
	if h.name == "" {
		return r
	}
	nr := slog.NewRecord(r.Time, r.Level, r.Message, r.PC)
	r.Attrs(func(a slog.Attr) bool {
		nr.AddAttrs(a)
		return true
	})
	nr.AddAttrs(slog.String("logger_name", h.name))
	return nr
}

// applyContextFields merges bound context fields into the record.
func (h *_telemetryHandler) applyContextFields(ctx context.Context, r slog.Record) slog.Record {
	fields := GetBoundFields(ctx)
	if len(fields) == 0 {
		return r
	}
	nr := slog.NewRecord(r.Time, r.Level, r.Message, r.PC)
	r.Attrs(func(a slog.Attr) bool {
		nr.AddAttrs(a)
		return true
	})
	for k, v := range fields {
		nr.AddAttrs(slog.Any(k, v))
	}
	return nr
}

// applyStandardFields adds service.name, service.env, and service.version from config.
func (h *_telemetryHandler) applyStandardFields(r slog.Record) slog.Record {
	cfg := h.cfg
	if cfg.ServiceName == "" && cfg.Environment == "" && cfg.Version == "" {
		return r
	}
	nr := slog.NewRecord(r.Time, r.Level, r.Message, r.PC)
	r.Attrs(func(a slog.Attr) bool {
		nr.AddAttrs(a)
		return true
	})
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

// applyTraceFields adds trace.id and span.id if available in context.
func (h *_telemetryHandler) applyTraceFields(ctx context.Context, r slog.Record) slog.Record {
	traceID, spanID := _getTraceSpanFromContext(ctx)
	if traceID == "" && spanID == "" {
		return r
	}
	nr := slog.NewRecord(r.Time, r.Level, r.Message, r.PC)
	r.Attrs(func(a slog.Attr) bool {
		nr.AddAttrs(a)
		return true
	})
	if traceID != "" {
		nr.AddAttrs(slog.String("trace.id", traceID))
	}
	if spanID != "" {
		nr.AddAttrs(slog.String("span.id", spanID))
	}
	return nr
}

// applySchema validates the event name and required keys when strict mode is enabled.
// Returns an error if validation fails; the caller drops the record on error.
func (h *_telemetryHandler) applySchema(r slog.Record) error {
	if len(h.cfg.EventSchema.RequiredKeys) > 0 {
		attrs := _attrsToMap(r)
		if err := ValidateRequiredKeys(attrs, h.cfg.EventSchema.RequiredKeys); err != nil {
			return err
		}
	}
	if !_readStrictSchema() {
		return nil
	}
	if err := ValidateEventName(r.Message); err != nil {
		return err
	}
	return nil
}

// applyPII sanitizes all record attributes through the PII engine.
func (h *_telemetryHandler) applyPII(r slog.Record) slog.Record {
	payload := _attrsToMap(r)
	sanitized := SanitizePayload(payload, h.cfg.Logging.Sanitize, 0)
	nr := slog.NewRecord(r.Time, r.Level, r.Message, r.PC)
	for _, a := range _mapToAttrs(sanitized) {
		nr.AddAttrs(a)
	}
	return nr
}

// _attrsToMap converts a slog.Record's attributes into a flat map[string]any.
func _attrsToMap(r slog.Record) map[string]any {
	m := make(map[string]any)
	r.Attrs(func(a slog.Attr) bool {
		m[a.Key] = a.Value.Any()
		return true
	})
	return m
}

// _mapToAttrs converts a map[string]any back into a []slog.Attr slice.
func _mapToAttrs(m map[string]any) []slog.Attr {
	attrs := make([]slog.Attr, 0, len(m))
	for k, v := range m {
		attrs = append(attrs, slog.Any(k, v))
	}
	return attrs
}

// _effectiveLevel returns the slog.Level for the given logger name by checking
// per-module overrides (longest prefix match) before falling back to the global level.
func _effectiveLevel(name string, cfg *TelemetryConfig) slog.Level {
	if cfg == nil {
		return slog.LevelInfo
	}
	globalLevel := _parseLevel(cfg.Logging.Level)

	type _match struct {
		moduleLen int
		level     slog.Level
	}
	var matches []_match
	for module, levelStr := range cfg.Logging.ModuleLevels {
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

// _isPrefixMatch returns true if name equals module or starts with module + ".".
func _isPrefixMatch(name, module string) bool {
	if module == "" {
		return true
	}
	if name == module {
		return true
	}
	return strings.HasPrefix(name, module+".")
}

// _parseLevel converts a level string to a slog.Level.
// Recognises TRACE, DEBUG, INFO, WARN, WARNING, ERROR, CRITICAL.
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

// _newTelemetryHandler wraps base with a _telemetryHandler for the given config and name.
func _newTelemetryHandler(base slog.Handler, cfg *TelemetryConfig, name string) slog.Handler {
	return &_telemetryHandler{
		next: base,
		cfg:  cfg,
		name: name,
	}
}

// _baseLogHandler builds the base slog.Handler (JSON or text) for the given config.
func _baseLogHandler(cfg *TelemetryConfig) slog.Handler {
	opts := &slog.HandlerOptions{
		Level: LevelTrace,
		ReplaceAttr: func(_ []string, a slog.Attr) slog.Attr {
			if !cfg.Logging.IncludeTimestamp && a.Key == slog.TimeKey {
				return slog.Attr{}
			}
			if a.Key == slog.MessageKey {
				a.Key = "message"
			}
			return a
		},
	}
	if cfg.Logging.Format == LogFormatJSON {
		return slog.NewJSONHandler(os.Stderr, opts)
	}
	return slog.NewTextHandler(os.Stderr, opts)
}

// _attachTraceContext adds trace.id / span.id from ctx to logger when present.
func _attachTraceContext(logger *slog.Logger, ctx context.Context) *slog.Logger {
	traceID, spanID := _getTraceSpanFromContext(ctx)
	if traceID == "" && spanID == "" {
		return logger
	}
	var attrs []any
	if traceID != "" {
		attrs = append(attrs, slog.String("trace.id", traceID))
	}
	if spanID != "" {
		attrs = append(attrs, slog.String("span.id", spanID))
	}
	return logger.With(attrs...)
}

// _configureLogger builds the Logger package var from cfg and sets it as slog's default.
func _configureLogger(cfg *TelemetryConfig) {
	Logger = slog.New(_newTelemetryHandler(_baseLogHandler(cfg), cfg, ""))
	slog.SetDefault(Logger)
}

// GetLogger returns a *slog.Logger with the telemetry handler chain bound to name.
// name is used for per-module level overrides (longest-prefix match).
// If ctx carries an active trace context (OTel span or manual SetTraceContext), the
// returned logger pre-attaches trace.id and span.id so they appear on every log line
// even when callers use the context-free Logger.Info(...) form.
func GetLogger(ctx context.Context, name string) *slog.Logger {
	cfg, err := ConfigFromEnv()
	if err != nil {
		cfg = DefaultTelemetryConfig()
	}
	if Logger != nil {
		if liveCfg, ok := _telemetryConfigFromHandler(Logger.Handler()); ok {
			cfg = liveCfg
		}
	}
	_setupMu.Lock()
	loggerProvider := _otelLoggerProvider
	_setupMu.Unlock()
	handler := _newTelemetryHandler(_baseLogHandler(cfg), cfg, name)
	if loggerProvider != nil {
		bridgeName := cmp.Or(name, cfg.ServiceName)
		handler = newMultiHandler(
			handler,
			otelslog.NewHandler(bridgeName, otelslog.WithLoggerProvider(loggerProvider)),
		)
	}
	return _attachTraceContext(slog.New(handler), ctx)
}

func _telemetryConfigFromHandler(handler slog.Handler) (*TelemetryConfig, bool) {
	switch h := handler.(type) {
	case *_telemetryHandler:
		return h.cfg, true
	case *multiHandler:
		for _, child := range h.handlers {
			if cfg, ok := _telemetryConfigFromHandler(child); ok {
				return cfg, true
			}
		}
	}
	return nil, false
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

// applyErrorFingerprint adds error_fingerprint when error attributes are present.
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
	fp := ComputeErrorFingerprintFromParts(excName, nil)
	nr := slog.NewRecord(r.Time, r.Level, r.Message, r.PC)
	r.Attrs(func(a slog.Attr) bool {
		nr.AddAttrs(a)
		return true
	})
	nr.AddAttrs(slog.String("error_fingerprint", fp))
	return nr
}
