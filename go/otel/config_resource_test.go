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

// defaultCfg returns a config carrying the framework defaults (nothing set).
func defaultCfg() *telemetry.TelemetryConfig {
	d := telemetry.DefaultTelemetryConfig()
	return &telemetry.TelemetryConfig{
		ServiceName: d.ServiceName,
		Environment: d.Environment,
		Version:     d.Version,
	}
}

// Precedence contract: framework floor < OTEL_* env < explicit config.
// With nothing set, all three identity keys fall back to the framework floor.
func TestBuildResource_FloorWhenUnset(t *testing.T) {
	d := telemetry.DefaultTelemetryConfig()
	r := _buildResource(defaultCfg())

	if got, _ := attrString(r, "service.name"); got != d.ServiceName {
		t.Fatalf("service.name = %q; want floor %q", got, d.ServiceName)
	}
	if got, _ := attrString(r, "deployment.environment"); got != d.Environment {
		t.Fatalf("deployment.environment = %q; want floor %q", got, d.Environment)
	}
	if got, _ := attrString(r, "service.version"); got != d.Version {
		t.Fatalf("service.version = %q; want floor %q", got, d.Version)
	}
}

// env > floor: OTEL_SERVICE_NAME fills a service name left at the default.
func TestBuildResource_EnvFillsUnsetIdentity(t *testing.T) {
	t.Setenv("OTEL_SERVICE_NAME", "env-service")
	t.Setenv("OTEL_RESOURCE_ATTRIBUTES", "deployment.environment=env-environment")

	r := _buildResource(defaultCfg())

	if got, _ := attrString(r, "service.name"); got != "env-service" {
		t.Fatalf("service.name = %q; want env to fill unset with %q", got, "env-service")
	}
	if got, _ := attrString(r, "deployment.environment"); got != "env-environment" {
		t.Fatalf("deployment.environment = %q; want env to fill unset with %q", got, "env-environment")
	}
}

// explicit > env: an explicitly named service is never hijacked by ambient env.
func TestBuildResource_ExplicitBeatsEnv(t *testing.T) {
	t.Setenv("OTEL_SERVICE_NAME", "env-service")
	t.Setenv("OTEL_RESOURCE_ATTRIBUTES", "deployment.environment=env-environment,service.version=8.8.8")

	cfg := &telemetry.TelemetryConfig{
		ServiceName: "app-service",
		Environment: "app-environment",
		Version:     "1.2.3",
	}
	r := _buildResource(cfg)

	if got, _ := attrString(r, "service.name"); got != "app-service" {
		t.Fatalf("service.name = %q; want explicit %q to beat env", got, "app-service")
	}
	if got, _ := attrString(r, "deployment.environment"); got != "app-environment" {
		t.Fatalf("deployment.environment = %q; want explicit %q to beat env", got, "app-environment")
	}
	if got, _ := attrString(r, "service.version"); got != "1.2.3" {
		t.Fatalf("service.version = %q; want explicit %q to beat env", got, "1.2.3")
	}
}

// Additive env keys merge through, and floor identity survives beside them.
func TestBuildResource_AdditiveEnvKeepsFloor(t *testing.T) {
	t.Setenv("OTEL_RESOURCE_ATTRIBUTES", "host.name=web-1")
	d := telemetry.DefaultTelemetryConfig()

	cfg := defaultCfg()
	cfg.Version = "9.9.9" // explicit
	r := _buildResource(cfg)

	if got, ok := attrString(r, "host.name"); !ok || got != "web-1" {
		t.Fatalf("host.name = %q (ok=%v); want additive env %q", got, ok, "web-1")
	}
	if got, _ := attrString(r, "service.version"); got != "9.9.9" {
		t.Fatalf("service.version = %q; want explicit %q", got, "9.9.9")
	}
	if got, _ := attrString(r, "service.name"); got != d.ServiceName {
		t.Fatalf("service.name = %q; want floor %q", got, d.ServiceName)
	}
}

// _explicitResourceAttrs includes only keys whose value differs from the default.
func TestExplicitResourceAttrs(t *testing.T) {
	d := telemetry.DefaultTelemetryConfig()

	if got := _explicitResourceAttrs(defaultCfg()); len(got) != 0 {
		t.Fatalf("all-default config yielded %d explicit attrs; want 0", len(got))
	}

	cfg := &telemetry.TelemetryConfig{
		ServiceName: "svc",         // differs
		Environment: d.Environment, // default → omitted
		Version:     d.Version,     // default → omitted
	}
	attrs := _explicitResourceAttrs(cfg)
	if len(attrs) != 1 || string(attrs[0].Key) != "service.name" || attrs[0].Value.AsString() != "svc" {
		t.Fatalf("explicit attrs = %+v; want only service.name=svc", attrs)
	}
}

// _mergeResources blends env attributes onto base when schema URLs are
// compatible (env carries the empty schema URL, so no conflict).
func TestMergeResources_MergesCompatible(t *testing.T) {
	base := sdkresource.NewWithAttributes(
		_resourceSchemaURL,
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
		_resourceSchemaURL,
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
