// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"os"
	"sort"
	"strings"
	"sync"
)

// ANSI escape codes for the pretty renderer. Inlined to avoid a new module
// dependency; cross-language parity with src/provide/telemetry/logger/pretty.py.
const (
	_ansiReset = "\x1b[0m"
	_ansiDim   = "\x1b[2m"
	_ansiBold  = "\x1b[1m"

	_ansiRed    = "\x1b[31m"
	_ansiGreen  = "\x1b[32m"
	_ansiYellow = "\x1b[33m"
	_ansiBlue   = "\x1b[34m"
	_ansiCyan   = "\x1b[36m"
	_ansiWhite  = "\x1b[37m"

	_ansiBoldRed = "\x1b[31;1m"

	// _prettyLevelPad aligns level tokens; "critical" (8) pads to 9 like Python.
	_prettyLevelPad = 9
)

// _levelColorMap returns the ANSI color for a lowercased level name.
func _levelColorMap(levelLower string) string {
	switch levelLower {
	case "critical":
		return _ansiBoldRed
	case "error":
		return _ansiRed
	case "warning", "warn":
		return _ansiYellow
	case "info":
		return _ansiGreen
	case "debug":
		return _ansiBlue
	case "trace":
		return _ansiCyan
	default:
		return ""
	}
}

// _resolveNamedColor maps friendly color names (matching Python NAMED_COLORS)
// to ANSI escape sequences. Unknown or empty names resolve to "".
func _resolveNamedColor(name string) string {
	switch strings.ToLower(strings.TrimSpace(name)) {
	case "dim":
		return _ansiDim
	case "bold":
		return _ansiBold
	case "red":
		return _ansiRed
	case "green":
		return _ansiGreen
	case "yellow":
		return _ansiYellow
	case "blue":
		return _ansiBlue
	case "cyan":
		return _ansiCyan
	case "white":
		return _ansiWhite
	case "", "none":
		return ""
	default:
		return ""
	}
}

// _isTerminalFile returns true when the given *os.File refers to a character
// device (terminal). Uses only stdlib: a regular pipe/file never has the
// ModeCharDevice bit set, but an interactive TTY does.
func _isTerminalFile(f *os.File) bool {
	if f == nil {
		return false
	}
	info, err := f.Stat()
	if err != nil {
		return false
	}
	return info.Mode()&os.ModeCharDevice != 0
}

// _prettyHandler is a slog.Handler that emits ANSI-coloured log lines.
// Field ordering mirrors the Python PrettyRenderer:
//
//	<dim timestamp> [<level>] <message> key=value key=value ...
//
// Colors activate only when colorsEnabled (TTY detection performed by caller).
type _prettyHandler struct {
	w                io.Writer
	mu               *sync.Mutex
	level            slog.Leveler
	colors           bool
	includeTimestamp bool
	keyColor         string // ANSI escape or "" for plain
	valueColor       string // ANSI escape or "" for plain
	fields           map[string]struct{}
	attrs            []slog.Attr
	groups           []string
}

// newPrettyHandler builds a _prettyHandler for cfg. Colors are gated on w being
// a TTY when w is an *os.File; otherwise colors are disabled.
func newPrettyHandler(w io.Writer, cfg *TelemetryConfig) *_prettyHandler {
	colors := false
	if f, ok := w.(*os.File); ok {
		colors = _isTerminalFile(f)
	}
	return newPrettyHandlerWithColors(w, cfg, colors)
}

// newPrettyHandlerWithColors is the test-friendly constructor that lets callers
// force the color flag regardless of the writer type.
func newPrettyHandlerWithColors(w io.Writer, cfg *TelemetryConfig, colors bool) *_prettyHandler {
	fieldFilter := map[string]struct{}{}
	for _, f := range cfg.Logging.PrettyFields {
		fieldFilter[f] = struct{}{}
	}
	return &_prettyHandler{
		w:                w,
		mu:               &sync.Mutex{},
		level:            LevelTrace,
		colors:           colors,
		includeTimestamp: cfg.Logging.IncludeTimestamp,
		keyColor:         _resolveNamedColor(cfg.Logging.PrettyKeyColor),
		valueColor:       _resolveNamedColor(cfg.Logging.PrettyValueColor),
		fields:           fieldFilter,
	}
}

// Enabled implements slog.Handler.
func (h *_prettyHandler) Enabled(_ context.Context, lvl slog.Level) bool {
	return lvl >= h.level.Level()
}

// WithAttrs implements slog.Handler. Attrs accumulate; groups are prefixed to keys.
func (h *_prettyHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	cp := h.clone()
	cp.attrs = append(cp.attrs, attrs...)
	return cp
}

// WithGroup implements slog.Handler. Groups prefix subsequent attr keys with "group.".
func (h *_prettyHandler) WithGroup(name string) slog.Handler {
	cp := h.clone()
	if name != "" {
		cp.groups = append(cp.groups, name)
	}
	return cp
}

// clone returns a shallow copy suitable for With*.
func (h *_prettyHandler) clone() *_prettyHandler {
	cp := *h
	cp.attrs = append([]slog.Attr(nil), h.attrs...)
	cp.groups = append([]string(nil), h.groups...)
	return &cp
}

// Handle implements slog.Handler. Writes the formatted line plus newline under a mutex.
func (h *_prettyHandler) Handle(_ context.Context, r slog.Record) error {
	line := h.formatLine(r)
	h.mu.Lock()
	defer h.mu.Unlock()
	_, err := io.WriteString(h.w, line+"\n")
	return err
}

// formatLine renders a slog.Record into the pretty text form.
func (h *_prettyHandler) formatLine(r slog.Record) string {
	var parts []string
	if h.includeTimestamp && !r.Time.IsZero() {
		ts := r.Time.UTC().Format("2006-01-02T15:04:05.000Z")
		parts = append(parts, h.wrap(ts, _ansiDim))
	}
	parts = append(parts, h.formatLevel(r.Level))
	parts = append(parts, r.Message)
	parts = append(parts, h.formatAttrs(r)...)
	return strings.Join(parts, " ")
}

// formatLevel renders "[level]" padded for alignment, wrapped in level color.
func (h *_prettyHandler) formatLevel(lvl slog.Level) string {
	name := _levelName(lvl)
	padded := name + strings.Repeat(" ", max(0, _prettyLevelPad-len(name)))
	if h.colors {
		color := _levelColorMap(name)
		if color != "" {
			return "[" + color + padded + _ansiReset + "]"
		}
	}
	return "[" + padded + "]"
}

// formatAttrs collects persistent + per-record attributes, optionally filters by
// _prettyFields, and renders them as "key=value" with configured colors.
// Keys are sorted for deterministic output.
func (h *_prettyHandler) formatAttrs(r slog.Record) []string {
	pairs := make(map[string]any)
	for _, a := range h.attrs {
		_collectAttr(pairs, a, h.groups)
	}
	r.Attrs(func(a slog.Attr) bool {
		_collectAttr(pairs, a, h.groups)
		return true
	})

	keys := make([]string, 0, len(pairs))
	for k := range pairs {
		if len(h.fields) > 0 {
			if _, ok := h.fields[k]; !ok {
				continue
			}
		}
		keys = append(keys, k)
	}
	sort.Strings(keys)

	out := make([]string, 0, len(keys))
	for _, k := range keys {
		v := pairs[k]
		vs := _formatValue(v)
		kp := h.wrap(k, h.keyColor)
		vp := h.wrap(vs, h.valueColor)
		out = append(out, kp+"="+vp)
	}
	return out
}

// wrap adds color+reset around s when colors are enabled and color is non-empty.
func (h *_prettyHandler) wrap(s, color string) string {
	if h.colors && color != "" {
		return color + s + _ansiReset
	}
	return s
}

// _collectAttr flattens slog attrs (including groups) into a string-keyed map,
// using dotted paths when groups are active. Empty attrs are skipped.
func _collectAttr(dst map[string]any, a slog.Attr, groups []string) {
	if a.Equal(slog.Attr{}) {
		return
	}
	key := a.Key
	if len(groups) > 0 {
		key = strings.Join(groups, ".") + "." + key
	}
	if a.Value.Kind() == slog.KindGroup {
		subGroups := append([]string(nil), groups...)
		if a.Key != "" {
			subGroups = append(subGroups, a.Key)
		}
		for _, sub := range a.Value.Group() {
			_collectAttr(dst, sub, subGroups)
		}
		return
	}
	dst[key] = a.Value.Any()
}

// _formatValue renders a value for pretty display. Strings get quoted with %q
// (matching Python's repr behaviour for free-form strings).
func _formatValue(v any) string {
	if s, ok := v.(string); ok {
		return fmt.Sprintf("%q", s)
	}
	return fmt.Sprint(v)
}

// _levelName returns the lowercased canonical name used by the pretty renderer.
// Recognises LevelTrace plus standard slog levels.
func _levelName(lvl slog.Level) string {
	switch {
	case lvl <= LevelTrace:
		return "trace"
	case lvl <= slog.LevelDebug:
		return "debug"
	case lvl <= slog.LevelInfo:
		return "info"
	case lvl <= slog.LevelWarn:
		return "warning"
	default:
		return "error"
	}
}
