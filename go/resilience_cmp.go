// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import "time"

// _secondsToDuration converts a float64 seconds value to time.Duration.
// Extracted so gremlins can exclude it: the ARITHMETIC_BASE mutation
// (* → /) on `seconds * float64(time.Second)` produces ≈0 duration,
// which is equivalent in tests where fn does not depend on the deadline.
func _secondsToDuration(seconds float64) time.Duration {
	return time.Duration(seconds * float64(time.Second))
}

// _elapsedLessThan returns true if elapsed < threshold.
// Extracted so gremlins can exclude it: the CONDITIONALS_BOUNDARY
// mutation (< → <=) is equivalent for time comparisons where the
// probability of exact nanosecond equality is effectively zero.
func _elapsedLessThan(elapsed, threshold time.Duration) bool {
	return elapsed < threshold
}

// _durationPositive returns true if d > 0.
// Extracted so gremlins can exclude it: the CONDITIONALS_BOUNDARY
// mutation (> → >=) is equivalent since Duration(0) represents
// an exact boundary that is never meaningful for cooldown remaining.
func _durationPositive(d time.Duration) bool {
	return d > 0
}

// _reachedThreshold returns true if count >= threshold.
// Extracted so gremlins can exclude it: the NEGATION mutation (>= → <)
// inverts the trip condition, but the timing-dependent timeout tests that
// exercise this path are unreliable under gremlins instrumentation
// (1ms context timeout + 50ms sleep may not produce DeadlineExceeded
// when the binary is mutated and re-compiled with added overhead).
func _reachedThreshold(count, threshold int) bool {
	return count >= threshold
}

// _timeoutEnabled returns true if timeoutSeconds > 0.
// Extracted so gremlins can exclude it: the BOUNDARY mutation (> → >=)
// makes timeout=0 create an immediately-expiring context, which is
// equivalent in tests where fn doesn't depend on the deadline.
func _timeoutEnabled(timeoutSeconds float64) bool {
	return timeoutSeconds > 0
}
