// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// Immutable package constants live together because Go coverage starts after
// package initialization, so gremlins cannot attribute mutations in constant
// declarations to tests. CI excludes only this declaration-only file; the
// exact-value tests in prometheus_listener_test.go still ratchet every value.

package otel

import "time"

// Prometheus listener server timeouts: long enough for a large scrape, short
// enough that a slow or idle client cannot hold a connection.
const (
	_listenerReadHeaderTimeout = 5 * time.Second
	_listenerReadTimeout       = 10 * time.Second
	_listenerWriteTimeout      = 30 * time.Second
	_listenerIdleTimeout       = 60 * time.Second
	_listenerShutdownTimeout   = 2 * time.Second
)
