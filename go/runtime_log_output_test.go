// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"bytes"
	"context"
	"strings"
	"testing"
)

// reconfigureLogger sets telemetry up writing JSON to buf.
func reconfigureLogger(t *testing.T, buf *bytes.Buffer) {
	t.Helper()
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	t.Setenv("PROVIDE_LOG_FORMAT", LogFormatJSON)
	t.Setenv("PROVIDE_LOG_INCLUDE_CALLER", "false")
	if _, err := SetupTelemetry(WithLogOutput(buf)); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
}

// A reconfigure can move the log destination.
//
// The writer used to be reachable only through SetupTelemetry, and
// ReconfigureTelemetry built its option state and then ignored the writer in it
// — so a host that wanted a different destination had to shut the runtime down
// and set it up again, losing every provider with it.
func TestReconfigure_WithLogOutputMovesTheDestination(t *testing.T) {
	var first, second bytes.Buffer
	reconfigureLogger(t, &first)

	GetLogger(context.Background(), "reconfig.test").Info("before.reconfigure")
	if _, err := ReconfigureTelemetry(context.Background(), WithLogOutput(&second)); err != nil {
		t.Fatalf("reconfigure failed: %v", err)
	}
	GetLogger(context.Background(), "reconfig.test").Info("after.reconfigure")

	if !strings.Contains(first.String(), "before.reconfigure") {
		t.Errorf("the first writer never received its record: %s", first.String())
	}
	if strings.Contains(first.String(), "after.reconfigure") {
		t.Errorf("the replaced writer kept receiving records: %s", first.String())
	}
	if !strings.Contains(second.String(), "after.reconfigure") {
		t.Errorf("the new writer received nothing: %s", second.String())
	}
}

// A reconfigure that says nothing about the destination leaves it alone.
//
// Absent means unchanged, not cleared: a host reloading its log level must not
// have its records silently returned to os.Stderr.
func TestReconfigure_WithoutTheOptionKeepsTheWriter(t *testing.T) {
	var buf bytes.Buffer
	reconfigureLogger(t, &buf)

	if _, err := ReconfigureTelemetry(context.Background()); err != nil {
		t.Fatalf("reconfigure failed: %v", err)
	}
	GetLogger(context.Background(), "reconfig.test").Info("after.plain.reconfigure")

	if !strings.Contains(buf.String(), "after.plain.reconfigure") {
		t.Errorf("a reconfigure with no writer option dropped the installed one: %s", buf.String())
	}
}

// A nil writer is rejected here exactly as it is at setup.
func TestReconfigure_ANilWriterIsAConfigurationError(t *testing.T) {
	var buf bytes.Buffer
	reconfigureLogger(t, &buf)

	if _, err := ReconfigureTelemetry(context.Background(), WithLogOutput(nil)); err == nil {
		t.Fatal("a nil writer was accepted")
	}

	GetLogger(context.Background(), "reconfig.test").Info("after.rejected.reconfigure")
	if !strings.Contains(buf.String(), "after.rejected.reconfigure") {
		t.Errorf("a rejected reconfigure disturbed the installed writer: %s", buf.String())
	}
}

// A rejected reconfigure leaves the destination where it found it.
//
// Validation runs before anything is installed, so a caller whose config is
// refused keeps the runtime it had — writer included.
func TestReconfigure_ARejectedTargetLeavesTheWriterInstalled(t *testing.T) {
	var buf, unused bytes.Buffer
	reconfigureLogger(t, &buf)

	bad := GetRuntimeConfig()
	bad.Sampling.TracesRate = -1

	if _, err := ReconfigureTelemetry(context.Background(), WithConfig(bad), WithLogOutput(&unused)); err == nil {
		t.Fatal("an invalid target was accepted")
	}

	GetLogger(context.Background(), "reconfig.test").Info("after.invalid.reconfigure")
	if !strings.Contains(buf.String(), "after.invalid.reconfigure") {
		t.Errorf("a rejected reconfigure moved the destination: %s", buf.String())
	}
	if unused.Len() != 0 {
		t.Errorf("a rejected reconfigure installed its writer anyway: %s", unused.String())
	}
}
