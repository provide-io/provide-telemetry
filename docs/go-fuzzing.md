# Go coverage-guided fuzzing

The Go package (`go/`) ships **native Go 1.18+ fuzz targets** for config
parsing and redaction.

## Day-to-day: `go test -fuzz`

```bash
cd go
make fuzz FUZZTIME=30s    # short
make fuzz FUZZTIME=5m     # longer
```

Continuous CI: `.github/workflows/ci-go-fuzz.yml` (PR + nightly on GitHub-hosted
VMs). That is *not* Google OSS-Fuzz cloud.

| Trigger | Duration (per target) |
|---------|------------------------|
| Pull request (Go paths) | `2m` |
| Nightly schedule | `15m` |
| `workflow_dispatch` | configurable (default `10m`) |

Targets: `FuzzParseOTLPHeaders`, `FuzzMaskEndpointURL`, `FuzzValidateRate`,
`FuzzValidatedSignalEndpointURL`, `FuzzParseEnvFloatThenValidateRate`.

## Local OSS-Fuzz (libFuzzer binaries via Docker)

Same builder image / `compile_native_go_fuzzer` path ClusterFuzz would use,
run **on your machine** only.

```bash
# From repo root (needs Docker + network to pull base images once):
./scripts/oss-fuzz-local.sh build
./scripts/oss-fuzz-local.sh run FuzzValidateRate
./scripts/oss-fuzz-local.sh list
```

Details: [`infra/oss-fuzz/README.md`](../infra/oss-fuzz/README.md).

**Requirements:** Docker. Prefer **linux/amd64** hosts; Apple Silicon works via
emulation but is slow. `OSS_FUZZ_DIR` points at a local `google/oss-fuzz` clone
(auto-cloned if missing).

## Shelved: Google OSS-Fuzz *cloud*

Submitting `projects/provide-telemetry` to **google/oss-fuzz** for 24/7
Google-hosted ClusterFuzz is **not** planned right now. The local recipe stays
so we can prove and iterate the build without onboarding.
