// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"bytes"
	"context"
	"io"
	"log/slog"
	"sync"
)

// _sinkHandler is the base handler whenever a host writer is installed. It
// renders each record into a private buffer and only then hands the finished
// line to the sink, so no renderer lock is held while the host's writer runs.
//
// That matters for re-entrance. slog's JSON and text handlers hold a mutex,
// shared by every clone, across their call to the writer. A writer that reports
// its own trouble through slog.Default — which SetupTelemetry points at this
// SDK — would otherwise block on that mutex, held by its own goroutine, before
// the sink's re-entrance guard ever saw the call. Rendering into a buffer moves
// the only lock held around the host's code into the sink, which knows how to
// refuse a nested write instead of waiting for it.
//
// Each buffer comes with its own renderer bound to it, pooled together, so a
// record costs a pool round trip rather than a renderer construction. A nested
// record takes a different pair from the pool, because its caller still holds
// the outer one.
type _sinkHandler struct {
	sink   *_logSink
	render func(io.Writer) slog.Handler
	probe  slog.Handler // answers Enabled; never written to
	pool   *sync.Pool
}

// _sinkRendering is one pooled buffer and the renderer that writes into it.
type _sinkRendering struct {
	buf bytes.Buffer
	h   slog.Handler
}

// _sinkBufferMaxRetain is the largest buffer returned to the pool. One huge
// record should not pin its buffer for the life of the process.
const _sinkBufferMaxRetain = 64 << 10

func _newSinkHandler(sink *_logSink, render func(io.Writer) slog.Handler) *_sinkHandler {
	h := &_sinkHandler{sink: sink, render: render, probe: render(io.Discard)}
	h.pool = &sync.Pool{New: func() any {
		r := &_sinkRendering{}
		r.h = render(&r.buf)
		return r
	}}
	return h
}

func (h *_sinkHandler) Enabled(ctx context.Context, level slog.Level) bool {
	return h.probe.Enabled(ctx, level)
}

func (h *_sinkHandler) Handle(ctx context.Context, r slog.Record) error {
	rendering := h.pool.Get().(*_sinkRendering) //nolint:forcetypeassert // the pool holds nothing else
	defer func() {
		if rendering.buf.Cap() <= _sinkBufferMaxRetain {
			h.pool.Put(rendering)
		}
	}()
	rendering.buf.Reset()
	if err := rendering.h.Handle(ctx, r); err != nil {
		return err
	}
	_, err := h.sink.Write(rendering.buf.Bytes())
	return err
}

// WithAttrs and WithGroup derive the renderer, not the buffers: the derived
// handler gets a pool of its own whose renderers carry the attrs or group.
// The telemetry handler folds bound attributes into each record rather than
// passing them down, so in practice neither is reached through GetLogger.
func (h *_sinkHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	render := h.render
	return _newSinkHandler(h.sink, func(w io.Writer) slog.Handler { return render(w).WithAttrs(attrs) })
}

func (h *_sinkHandler) WithGroup(name string) slog.Handler {
	render := h.render
	return _newSinkHandler(h.sink, func(w io.Writer) slog.Handler { return render(w).WithGroup(name) })
}
