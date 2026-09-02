// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"cmp"
	"context"
	"fmt"
	"log/slog"
	"os"
	"regexp"
	"slices"
	"strings"

	"github.com/provide-io/provide-telemetry/go/internal/levelcore"
	"github.com/provide-io/provide-telemetry/go/internal/piicore"
)

// _telemetryHandler is a slog.Handler middleware that implements the full processor chain:
// context-field merge → standard fields → trace/span IDs → sampling → schema → PII →
// callsite → base handler.
type _telemetryHandler struct {
	next  slog.Handler
	cfg   *TelemetryConfig
	name  string
	bound []_boundStep
}

// _boundStep is one WithAttrs or WithGroup call, kept in call order.
//
// The order is the whole point: slog nests an attribute under the groups that
// were open when it was bound, so With(a).WithGroup("g").With(b) puts a at the
// top level and b inside g. Two separate attrs and groups fields cannot express
// that interleaving.
type _boundStep struct {
	group string      // non-empty: opens a group
	attrs []slog.Attr // non-empty: attributes bound at this level
}

// Enabled reports whether the handler should process records at the given level.
// Per-module level overrides take precedence over the global log level.
func (h *_telemetryHandler) Enabled(_ context.Context, level slog.Level) bool {
	return level >= _effectiveLevel(h.name, h.cfg)
}

// WithAttrs returns a new handler with the given attributes pre-attached.
//
// The attributes are recorded here and folded into each record by Handle. They
// are deliberately NOT passed to h.next: the base handler formats what it is
// given straight to the output, which would carry them past sanitization and
// past schema validation — a credential bound once at a request boundary would
// then appear in the clear on every record.
func (h *_telemetryHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	if len(attrs) == 0 {
		return h
	}
	cp := h.clone()
	cp.bound = append(cp.bound, _boundStep{attrs: slices.Clone(attrs)})
	return cp
}

// WithGroup returns a new handler scoped to the named group. Like WithAttrs it
// is applied when the record is built rather than delegated, so the nesting it
// implies is present before any processor runs.
func (h *_telemetryHandler) WithGroup(name string) slog.Handler {
	if name == "" {
		return h
	}
	cp := h.clone()
	cp.bound = append(cp.bound, _boundStep{group: name})
	return cp
}

// Handle executes the processor chain and forwards to the base handler.
func (h *_telemetryHandler) Handle(ctx context.Context, r slog.Record) error {
	// Bound attributes join the record first, so schema validation and PII see
	// them. Fields this middleware adds below stay at the top level rather than
	// landing inside whatever group the caller happened to leave open.
	r = h.applyBoundAttrs(r)
	r = h.applyContextFields(ctx, r)
	r = h.applyLoggerName(r)
	r = h.applyStandardFields(r)
	r = h.applyTraceFields(ctx, r)

	// Consent gate: block before any processing when consent level forbids logs.
	if !ShouldAllow(signalLogs, levelcore.SlogName(r.Level)) {
		return nil
	}

	// Schema validation runs BEFORE sampling so records flagged by
	// validateRequiredKeys / validateEventName don't inflate LogsEmitted.
	// Annotate with _schema_error instead of dropping — preserves telemetry.
	// Cross-language standard (Python/TypeScript/Rust match).
	if err := h.applySchema(r); err != nil {
		r.AddAttrs(slog.String("_schema_error", err.Error()))
	}

	if sampled := _shouldSampleFailOpen(signalLogs, r.Message); !sampled {
		return nil
	}

	// Backpressure gate: drop when the log queue is full.
	ticket := TryAcquire(signalLogs)
	if ticket == nil {
		return nil
	}
	defer Release(ticket)
	_incLogsEmitted()

	r = h.applyErrorFingerprint(r)
	r = h.applyPII(r)

	// After sanitization, deliberately: a source path is not user data, and
	// hardening's attribute cap and value truncation would mangle it. Mirrors
	// Python, which appends CallsiteParameterAdder after sanitize_sensitive_fields.
	r = h.applyCallsite(r)

	// log/slog discards whatever a handler returns, so a destination that
	// refuses the write is invisible to the caller: the record is gone and
	// LogsEmitted has already counted it. Recording the failure is what keeps
	// the health snapshot from asserting a delivery that never happened.
	//
	// export_failures is the canonical bucket for "an export attempt returned
	// an error"; dropped is reserved for records refused before export, by
	// consent, sampling or backpressure, and a record must never count as both
	// emitted and dropped.
	err := h.next.Handle(ctx, r)
	if err != nil {
		_incLogsExportErrors()
	}
	return err
}

// clone returns a shallow copy of the handler. The step slice is copied because
// sibling loggers append to it independently; each step's own attrs are cloned
// when the step is created and never mutated after.
func (h *_telemetryHandler) clone() *_telemetryHandler {
	cp := *h
	cp.bound = slices.Clone(h.bound)
	return &cp
}

// applyBoundAttrs folds attributes bound with With/WithGroup into the record so
// every processor downstream sees them, rebuilding the nesting the steps imply.
//
// Walking the steps in reverse turns each open group into a single group-valued
// attribute wrapping everything bound after it, which is exactly slog's rule.
func (h *_telemetryHandler) applyBoundAttrs(r slog.Record) slog.Record {
	if len(h.bound) == 0 {
		return r
	}

	cur := make([]slog.Attr, 0, r.NumAttrs())
	r.Attrs(func(a slog.Attr) bool {
		cur = append(cur, a)
		return true
	})

	for i := len(h.bound) - 1; i >= 0; i-- {
		step := h.bound[i]
		if step.group == "" {
			cur = append(slices.Clone(step.attrs), cur...)
			continue
		}
		// slog ignores a group that ends up with no attributes.
		if len(cur) == 0 {
			continue
		}
		cur = []slog.Attr{{Key: step.group, Value: slog.GroupValue(cur...)}}
	}

	nr := slog.NewRecord(r.Time, r.Level, r.Message, r.PC)
	nr.AddAttrs(cur...)
	return nr
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

// applyPII sanitizes record attributes through the PII engine AND scrubs the
// message string for secret patterns. The message is checked separately
// (NOT via the map-based engine) because path-based rules — including the
// wildcard rule `Path: []string{"*"}` — would match any sentinel key we
// might use, dropping the message entirely or letting it fall back to raw.
//
// For free-form text the only meaningful redaction is value-based: detect
// known secret patterns (AWS keys, GitHub tokens, etc.) and replace the
// whole message with the redaction sentinel when one matches. Mirrors
// Python's behaviour where a message containing a secret is emitted as
// "message": "***".
func (h *_telemetryHandler) applyPII(r slog.Record) slog.Record {
	// Hardening runs before the rule engine, not after. The engine only looks
	// inside map[string]any and []any, so a []credentials, a map[string]string
	// or a plain struct would carry its Password field straight past redaction.
	// Normalizing first turns every typed container into something the engine
	// can see into, and bounds depth, width and value length while it is there.
	payload := _hardenAttrs(_attrsToMap(r), _limitsFromConfig(h.cfg))
	sanitized := SanitizePayload(payload, h.cfg.Logging.Sanitize, 0)

	message := r.Message
	if h.cfg.Logging.Sanitize && piicore.DetectSecretInValue(message, _customPIIPatterns()) {
		message = piicore.RedactSecretSpans(message, _customPIIPatterns())
	}

	nr := slog.NewRecord(r.Time, r.Level, message, r.PC)
	for _, a := range _mapToAttrs(sanitized) {
		nr.AddAttrs(a)
	}
	return nr
}

// _shouldSampleFailOpen invokes ShouldSample and returns the sampled bool.
// If ShouldSample returns an error — which only happens when signal is unknown,
// a case our hard-coded callers never trigger — we log the error via slog.Default
// (NOT the telemetry Logger, to avoid recursion through the handler chain) and
// fail-open by returning true. Fail-open matches the library's graceful-
// degradation convention: never drop telemetry on an internal misconfiguration.
func _shouldSampleFailOpen(signal, key string) bool {
	sampled, err := ShouldSample(signal, key)
	if err != nil {
		// Bypass the telemetry Logger so we do not re-enter the handler chain.
		slog.Default().Warn("telemetry.sampling.error",
			slog.String("signal", signal),
			slog.String("error", err.Error()),
		)
		return true
	}
	return sampled
}

// _customPIIPatterns returns the registered custom secret patterns (if any).
// Reads the atomic snapshot published by RegisterSecretPattern /
// _resetSecretPatterns so the hot path — message-body secret scrubbing for
// every log record — avoids both _piiMu.RLock() and a per-call map clone.
// The returned map is a shared immutable snapshot: callers must NOT mutate it.
func _customPIIPatterns() map[string]*regexp.Regexp {
	return _loadCustomSecretPatsSnapshot()
}

// _attrsToMap converts a slog.Record's attributes into a flat map[string]any.
func _attrsToMap(r slog.Record) map[string]any {
	m := make(map[string]any)
	r.Attrs(func(a slog.Attr) bool {
		m[a.Key] = _attrValue(a.Value)
		return true
	})
	return m
}

// _attrValue unwraps a group into a nested map. Value.Any() hands back a
// []slog.Attr, which the PII rule engine cannot see into — it walks
// map[string]any and []any — and which JSON renders as the exported half of
// each Attr struct, destroying the values it was asked to log.
func _attrValue(v slog.Value) any {
	if v.Kind() != slog.KindGroup {
		return v.Any()
	}
	group := v.Group()
	m := make(map[string]any, len(group))
	for _, a := range group {
		m[a.Key] = _attrValue(a.Value)
	}
	return m
}

// _mapToAttrs converts a map[string]any back into a []slog.Attr slice,
// restoring nested maps as the groups they came from so the rendered shape
// matches what the caller logged.
func _mapToAttrs(m map[string]any) []slog.Attr {
	attrs := make([]slog.Attr, 0, len(m))
	for k, v := range m {
		if nested, ok := v.(map[string]any); ok {
			attrs = append(attrs, slog.Attr{Key: k, Value: slog.GroupValue(_mapToAttrs(nested)...)})
			continue
		}
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
	return levelcore.ParseSlog(s, levelcore.Info)
}

// ParseLevel resolves a level string to the slog.Level that carries it.
//
// Exported because adapters that receive a level as data need the conversion
// too, and every one that re-implemented it got a slightly different table.
// Recognises TRACE, DEBUG, INFO, WARN, WARNING, ERROR, CRITICAL and FATAL,
// case-insensitively and ignoring surrounding whitespace; anything else
// resolves to INFO.
func ParseLevel(s string) slog.Level { return _parseLevel(s) }

// LevelName is the canonical spelling of an slog.Level.
//
// slog.Level.String() renders LevelTrace as "DEBUG-4" and LevelCritical as
// "ERROR+4", neither of which any level table recognises.
func LevelName(l slog.Level) string { return levelcore.SlogName(l) }

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
			// slog renders a level it has no name for by arithmetic on the
			// nearest one it does: LevelTrace becomes "DEBUG-4" and
			// LevelCritical "ERROR+4". Neither is a level any consumer or any
			// of this project's other ports recognises, and CRITICAL is
			// reachable through the ordinary Log(ctx, ParseLevel(s), msg) path.
			if a.Key == slog.LevelKey {
				if lvl, ok := a.Value.Any().(slog.Level); ok {
					return slog.String(slog.LevelKey, levelcore.SlogName(lvl))
				}
			}
			return a
		},
	}
	out := _logOutput()
	if cfg.Logging.Format == LogFormatJSON {
		return slog.NewJSONHandler(out, opts)
	}
	if cfg.Logging.Format == LogFormatPretty {
		return newPrettyHandler(out, cfg)
	}
	return slog.NewTextHandler(out, opts)
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

var _preTelemetryLogger *slog.Logger

// _baseHandlerWithBridge returns the base renderer, fanned out to the backend's
// log bridge when one is installed.
//
// The bridge sits *below* the telemetry handler rather than beside it, so a
// record reaches it only after consent, module level, schema, sampling,
// backpressure, hardening and PII redaction have run. As a sibling it would
// receive the record the caller passed in, and a password masked in the local
// log would leave the process in the clear.
//
// Every construction of the logging chain goes through here. Three of them once
// built it independently, and the two that rebuild on reload quietly lost the
// bridge — the package logger stopped exporting while the config still reported
// the endpoint as enabled.
func _baseHandlerWithBridge(cfg *TelemetryConfig, name string) slog.Handler {
	base := _baseLogHandler(cfg)
	backend := _activeBackend()
	if backend == nil {
		return base
	}
	bridge := backend.LoggerHandler(cmp.Or(name, cfg.ServiceName))
	if bridge == nil {
		return base
	}
	return newMultiHandler(base, bridge)
}

// _configureLogger builds the Logger package var from cfg and sets it as slog's default.
func _configureLogger(cfg *TelemetryConfig) {
	if Logger() == nil {
		_preTelemetryLogger = slog.Default()
	}
	SetLogger(slog.New(_newTelemetryHandler(_baseHandlerWithBridge(cfg, ""), cfg, "")))
	slog.SetDefault(Logger())
}

// _resetLogger clears the package logger and restores the prior slog default.
func _resetLogger() {
	SetLogger(nil)
	if _preTelemetryLogger != nil {
		slog.SetDefault(_preTelemetryLogger)
		_preTelemetryLogger = nil
		return
	}
	// os.Stderr, not Logging.Output: teardown hands logging back to the
	// standard library, whose own default writes there. A caller's writer is
	// scoped to the telemetry runtime that is being torn down.
	slog.SetDefault(slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{})))
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
	if !_runtimeSetupDone() {
		_, _ = SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: cfg.Sampling.LogsRate})
		// The lazy pre-setup logger must honour PROVIDE_CONSENT_LEVEL too, or
		// a process that never calls SetupTelemetry emits under NONE. Only
		// before setup: afterwards a programmatic SetConsentLevel is the
		// authority and must not be overwritten by the environment.
		LoadConsentFromEnv()
	}
	// Prefer the published generation; fall back to whatever logger has been
	// configured without a full setup (the lazy pre-setup path). Both sources
	// are atomics — the exported, caller-assignable Logger variable this
	// replaced could not be read race-free while reconfiguration wrote it.
	if gen := _loadGeneration(); gen != nil {
		cfg = gen.config
	} else if active := Logger(); active != nil {
		if liveCfg, ok := _telemetryConfigFromHandler(active.Handler()); ok {
			cfg = liveCfg
		}
	}
	base := _baseHandlerWithBridge(cfg, name)
	return _attachTraceContext(slog.New(_newTelemetryHandler(base, cfg, name)), ctx)
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
	logger := Logger()
	if logger == nil {
		return false
	}
	return logger.Enabled(context.Background(), slog.LevelDebug)
}

// IsTraceEnabled returns true if the package-level Logger would emit TRACE records.
func IsTraceEnabled() bool {
	logger := Logger()
	if logger == nil {
		return false
	}
	return logger.Enabled(context.Background(), LevelTrace)
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
