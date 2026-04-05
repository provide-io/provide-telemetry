// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import "math/rand"

// _rollBelowRate returns true if a uniform random float in [0,1) is strictly
// less than rate. This comparison is extracted so gremlins can exclude it:
// the CONDITIONALS_BOUNDARY mutation (< vs <=) is mathematically equivalent
// for float64 (P(rand == rate) = 0).
func _rollBelowRate(rate float64) bool {
	return rand.Float64() < rate // #nosec G404 -- probabilistic sampling; crypto/rand not required
}
