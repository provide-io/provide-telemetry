module github.com/provide-io/provide-telemetry/go/tracer

go 1.25.0

require (
	github.com/provide-io/provide-telemetry/go/logger v0.0.0
	go.opentelemetry.io/otel/trace v1.43.0
)

require (
	github.com/cespare/xxhash/v2 v2.3.0 // indirect
	go.opentelemetry.io/otel v1.43.0 // indirect
)

replace github.com/provide-io/provide-telemetry/go/logger => ../logger
