module github.com/provide-io/provide-telemetry/go/logger

go 1.25.0

require github.com/provide-io/provide-telemetry/go/internal v0.3.0

retract v0.3.0 // broken go.mod: unresolvable internal dependency
