// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"bytes"
	"regexp"
	"strings"
	"testing"
)

func TestHandler_PIISanitization_MessageContent_CustomSecretPattern(t *testing.T) {
	setupFullSampling(t)
	resetPII(t)
	RegisterSecretPattern("internal", regexp.MustCompile(`INTSECRET-[A-Z0-9]+`))

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = true

	var buf bytes.Buffer
	newTestLogger(&buf, cfg, "").Info("token INTSECRET-ABC123 leaked") // pragma: allowlist secret
	if strings.Contains(buf.String(), "INTSECRET-ABC123") {            // pragma: allowlist secret
		t.Errorf("custom secret pattern did not scrub message: %s", buf.String())
	}
}
