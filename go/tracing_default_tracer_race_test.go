// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"sync"
	"testing"
)

// DefaultTracer is written during setup and shutdown and read from every traced
// call, which holds no lock. It is a two-word interface value, so an
// unsynchronized read while it is written can tear into a stale itab paired
// with a new data pointer — dispatching Start on the wrong receiver. Library
// code therefore goes through _loadDefaultTracer/_storeDefaultTracer, and this
// test fails under -race the moment a bare read or write creeps back in.
func TestDefaultTracer_ReadsAndWritesAreSynchronized(t *testing.T) {
	original := _loadDefaultTracer()
	t.Cleanup(func() { _storeDefaultTracer(original) })

	var wg sync.WaitGroup
	stop := make(chan struct{})

	for range 4 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for {
				select {
				case <-stop:
					return
				default:
				}
				_, span := _effectiveTracer().Start(context.Background(), "race.span")
				span.End()
				_ = GetTracer("race")
			}
		}()
	}

	for range 200 {
		_storeDefaultTracer(&_noopTracer{})
	}
	close(stop)
	wg.Wait()
}
