# Capability Matrix

This matrix separates core guaranteed behavior from idiomatic differences and
feature-gated OTLP paths.

Legend:

- `core` — guaranteed by the shared semantic contract and parity suite
- `idiomatic` — intentionally language-specific surface difference
- `feature-gated` — supported, but only when the language-specific OTLP feature
  path is enabled

| Capability | Python | TypeScript | Go | Rust | Contract |
| --- | --- | --- | --- | --- | --- |
| Canonical JSON log envelope (`service`, `env`, `version`, `logger_name`, trace/span IDs, timestamp policy) | core | core | core | core | core guaranteed |
| Lazy logger init uses effective env config | core | core | core | core | core guaranteed |
| Strict-schema rejection emits `_schema_error` instead of dropping the record | core | core | core | core | core guaranteed |
| Required-key rejection emits `_schema_error` instead of dropping the record | core | core | core | core | core guaranteed |
| Invalid config fails fast at setup | core | core | core | core | core guaranteed |
| Fail-open exporter initialization degrades to fallback without marking providers installed | core | core | core | feature-gated | core guaranteed when OTLP path is enabled |
| Shutdown followed by setup restores the same runtime-status shape | core | core | core | core | core guaranteed |
| `get_runtime_config()` returns effective config before or after explicit setup | core | core | core | core | core guaranteed |
| `get_runtime_status()` exposes `setup_done`, `signals`, `providers`, `fallback`, and `setup_error` | core | core | core | core | core guaranteed |
| Real OTLP traces export | core | core | core | feature-gated | feature/dependency gated |
| Real OTLP metrics export | core | core | core | feature-gated | feature/dependency gated |
| Real OTLP logs export | core | core | core | feature-gated | feature/dependency gated |
| Guard-based context restoration | idiomatic | no | no | idiomatic | idiomatic language difference |
| Browser log capture / React helpers | no | idiomatic | no | no | idiomatic language difference |

Notes:

- Rust OTLP export requires the `otel` cargo feature.
- TypeScript OTLP export requires the optional OpenTelemetry peer dependencies.
- Python OTLP export requires the `otel` extras.
- Go OTLP export is built into the module, but still follows fail-open setup and
  runtime fallback semantics when provider construction fails.
