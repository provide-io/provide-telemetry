// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"errors"
	"testing"
)

const (
	testDefaultEndpoint = "http://generic:4317"
	testLogLevel        = "INFO"
	testDebugLevel      = "DEBUG"
)

// ---- Helper ----

func assertConfigError(t *testing.T, err error) {
	t.Helper()
	if err == nil {
		t.Fatal("expected *ConfigurationError, got nil")
	}
	var cfgErr *ConfigurationError
	if !errors.As(err, &cfgErr) {
		t.Errorf("expected *ConfigurationError, got %T: %v", err, err)
	}
}
