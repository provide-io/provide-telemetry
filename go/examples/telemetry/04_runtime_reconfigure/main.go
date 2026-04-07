// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// 04_runtime_reconfigure — hot-swap policies without restart.
//
// Demonstrates:
//   - GetRuntimeConfig to inspect current configuration
//   - UpdateRuntimeConfig for hot-swap of individual fields
//   - ReconfigureTelemetry for full provider restart
//   - ReloadRuntimeFromEnv to re-read environment variables
package main

import (
	"context"
	"fmt"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

func main() {
	fmt.Println("Runtime Reconfiguration Demo")

	_, err := telemetry.SetupTelemetry()
	if err != nil {
		telemetry.Logger.Error("setup failed", "err", err)
		return
	}
	defer func() { _ = telemetry.ShutdownTelemetry(context.Background()) }()

	ctx := context.Background()
	log := telemetry.GetLogger(ctx, "examples.runtime")

	// Inspect current config
	cfgBefore := telemetry.GetRuntimeConfig()
	if cfgBefore != nil {
		fmt.Printf("Before: logs_rate=%.1f\n", cfgBefore.Sampling.LogsRate)
	}

	beforeEvt, _ := telemetry.Event("example", "runtime", "before")
	log.InfoContext(ctx, beforeEvt.Event, beforeEvt.Attrs()...)

	// Hot-swap sampling rate to 0%
	fmt.Println("\nHot-swapping sampling rate to 0%...")
	err = telemetry.UpdateRuntimeConfig(telemetry.RuntimeOverrides{
		Sampling: &telemetry.SamplingConfig{LogsRate: 0.0, TracesRate: 1.0, MetricsRate: 1.0},
	})
	if err != nil {
		log.ErrorContext(ctx, "update failed", "err", err)
	} else {
		cfgAfter := telemetry.GetRuntimeConfig()
		if cfgAfter != nil {
			fmt.Printf("  After update: logs_rate=%.1f\n", cfgAfter.Sampling.LogsRate)
		}
	}

	// Log an event that will be sampled out at 0%
	droppedEvt, _ := telemetry.Event("example", "runtime", "dropped")
	log.InfoContext(ctx, droppedEvt.Event, droppedEvt.Attrs()...)

	snapshot := telemetry.GetHealthSnapshot()
	fmt.Printf("  Dropped logs: %d\n", snapshot.LogsDropped)

	// Full provider restart via ReconfigureTelemetry
	fmt.Println("\nReconfigureTelemetry() — full shutdown+setup cycle...")
	restarted, err := telemetry.ReconfigureTelemetry(ctx)
	if err != nil {
		log.ErrorContext(ctx, "reconfigure failed", "err", err)
	} else if restarted != nil {
		fmt.Printf("  Restarted: logs_rate=%.1f\n", restarted.Sampling.LogsRate)
	}

	restartedEvt, _ := telemetry.Event("example", "runtime", "restarted")
	log.InfoContext(ctx, restartedEvt.Event, restartedEvt.Attrs()...)

	// Reload hot policy fields from environment. Cold/provider fields are preserved and
	// only reported via warning if they drift from the live config.
	fmt.Println("\nReloadRuntimeFromEnv() — re-reads os.Environ() for hot fields...")
	if reloadErr := telemetry.ReloadRuntimeFromEnv(); reloadErr != nil {
		log.ErrorContext(ctx, "reload failed", "err", reloadErr)
	} else {
		reloaded := telemetry.GetRuntimeConfig()
		if reloaded != nil {
			fmt.Printf("  Reloaded: logs_rate=%.1f\n", reloaded.Sampling.LogsRate)
		}
	}

	fmt.Println("\nDone!")
}
