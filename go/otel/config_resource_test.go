// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"testing"

	telemetry "github.com/provide-io/provide-telemetry/go"
	"go.opentelemetry.io/otel/attribute"
	sdkresource "go.opentelemetry.io/otel/sdk/resource"
)

// attrString returns the string value of key on r, or "" if unset.
func attrString(r *sdkresource.Resource, key string) (string, bool) {
	v, ok := r.Set().Value(attribute.Key(key))
	return v.AsString(), ok
}

// _buildResource must honor OTEL_SERVICE_NAME / OTEL_RESOURCE_ATTRIBUTES (parity
// with Python, Rust, and the TypeScript buildOtelResource), with env attributes
// winning on key conflict while config-only keys survive.
func TestBuildResource_HonorsEnvAttributes(t *testing.T) {
	t.Setenv("OTEL_SERVICE_NAME", "env-service")
	t.Setenv("OTEL_RESOURCE_ATTRIBUTES", "host.name=web-1")

	cfg := &telemetry.TelemetryConfig{
		ServiceName: "cfg-service",
		Version:     "1.2.3",
		Environment: "prod",
	}
	r := _buildResource(cfg)

	// Additive env-only key proves the env detector ran and merged.
	if got, ok := attrString(r, "host.name"); !ok || got != "web-1" {
		t.Fatalf("host.name = %q (ok=%v); want %q", got, ok, "web-1")
	}
	// Env wins on conflict: OTEL_SERVICE_NAME overrides the config service.name.
	if got, _ := attrString(r, "service.name"); got != "env-service" {
		t.Fatalf("service.name = %q; want env to win with %q", got, "env-service")
	}
	// Config-only keys are untouched by env.
	if got, _ := attrString(r, "service.version"); got != "1.2.3" {
		t.Fatalf("service.version = %q; want %q", got, "1.2.3")
	}
	if got, _ := attrString(r, "deployment.environment"); got != "prod" {
		t.Fatalf("deployment.environment = %q; want %q", got, "prod")
	}
}

// _buildResource without any env vars keeps the pure config identity.
func TestBuildResource_ConfigOnly(t *testing.T) {
	cfg := &telemetry.TelemetryConfig{ServiceName: "cfg-service", Version: "9.9.9", Environment: "dev"}
	r := _buildResource(cfg)

	if got, _ := attrString(r, "service.name"); got != "cfg-service" {
		t.Fatalf("service.name = %q; want %q", got, "cfg-service")
	}
	if got, _ := attrString(r, "service.version"); got != "9.9.9" {
		t.Fatalf("service.version = %q; want %q", got, "9.9.9")
	}
}

// _mergeResources blends env attributes onto base when schema URLs are
// compatible (env carries the empty schema URL, so no conflict).
func TestMergeResources_MergesCompatible(t *testing.T) {
	base := sdkresource.NewWithAttributes(
		"https://opentelemetry.io/schemas/1.26.0",
		attribute.String("service.name", "svc"),
	)
	env := sdkresource.NewSchemaless(attribute.String("extra", "value"))

	merged := _mergeResources(base, env)

	if got, ok := attrString(merged, "extra"); !ok || got != "value" {
		t.Fatalf("extra = %q (ok=%v); want %q — merge must include env attrs", got, ok, "value")
	}
	if got, _ := attrString(merged, "service.name"); got != "svc" {
		t.Fatalf("service.name = %q; want %q", got, "svc")
	}
}

// _mergeResources falls back to base (not a schemaless blend) when the two
// resources carry conflicting non-empty schema URLs — the only case
// resource.Merge reports an error for.
func TestMergeResources_SchemaConflictReturnsBase(t *testing.T) {
	base := sdkresource.NewWithAttributes(
		"https://opentelemetry.io/schemas/1.26.0",
		attribute.String("service.name", "svc"),
	)
	env := sdkresource.NewWithAttributes(
		"https://opentelemetry.io/schemas/1.0.0",
		attribute.String("extra", "value"),
	)

	merged := _mergeResources(base, env)

	// Base identity survives...
	if got, _ := attrString(merged, "service.name"); got != "svc" {
		t.Fatalf("service.name = %q; want base %q on schema conflict", got, "svc")
	}
	// ...and the conflicting env attribute is dropped (proves base, not blend).
	if _, ok := attrString(merged, "extra"); ok {
		t.Fatalf("extra should be absent on schema conflict; got present")
	}
}
