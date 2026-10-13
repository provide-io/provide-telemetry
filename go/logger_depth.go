// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"log/slog"
	"runtime"
	"time"
)

// LogDepth logs msg at level through logger, reporting as its callsite the
// frame depth calls above the caller of LogDepth.
//
// It is for adapters that bridge another logging API onto slog — a gRPC
// grpclog.LoggerV2, a database driver's logger interface — where the
// interesting frame is not the adapter's but its caller's. The handler takes
// the callsite from the record's program counter, which slog's own methods set
// to their immediate caller, so a record logged through logger.Info from inside
// an adapter names the adapter. With LogDepth, depth 0 names the function that
// calls LogDepth, and depth 1 the function that called it:
//
//	func (a grpcAdapter) Info(args ...any) {
//		telemetry.LogDepth(context.Background(), a.logger, slog.LevelInfo, 1, fmt.Sprint(args...))
//	}
//
// A nil logger means slog.Default(). Standard library log output bridged with
// slog.NewLogLogger already names the right frame and needs none of this.
func LogDepth(ctx context.Context, logger *slog.Logger, level slog.Level, depth int, msg string, args ...any) {
	if logger == nil {
		logger = slog.Default()
	}
	if ctx == nil {
		ctx = context.Background()
	}
	if !logger.Enabled(ctx, level) {
		return
	}
	if depth < 0 {
		depth = 0
	}
	var pcs [1]uintptr
	// Skip runtime.Callers itself and LogDepth.
	runtime.Callers(depth+2, pcs[:])
	r := slog.NewRecord(time.Now(), level, msg, pcs[0])
	r.Add(args...)
	_ = logger.Handler().Handle(ctx, r)
}
