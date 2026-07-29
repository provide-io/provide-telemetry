// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package tracer_test

import (
	"context"
	"sync"
	"testing"

	"github.com/provide-io/provide-telemetry/go/tracer"
)

// DefaultTracer is a two-word interface value read from every traced call, so
// an unsynchronized read while SetDefaultTracer writes can tear into a stale
// itab paired with a new data pointer. Library reads go through a guarded
// accessor; this fails under -race the moment a bare read creeps back in.
func TestDefaultTracer_ReadsAndWritesAreSynchronized(t *testing.T) {
	original := tracer.GetTracer("")
	t.Cleanup(func() { tracer.SetDefaultTracer(original) })

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
				_ = tracer.Trace(context.Background(), "race.span", func(context.Context) error {
					return nil
				})
				_ = tracer.GetTracer("race")
			}
		}()
	}

	for range 200 {
		tracer.SetDefaultTracer(original)
	}
	close(stop)
	wg.Wait()
}
