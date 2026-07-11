# Go coverage-guided fuzzing

The Go package (`go/`) ships **native Go 1.18+ fuzz targets** for config
parsing and redaction.

## Local

```bash
cd go
make fuzz FUZZTIME=30s    # short
make fuzz FUZZTIME=5m     # longer
```

## Continuous (GitHub Actions)

Workflow: `.github/workflows/ci-go-fuzz.yml`

| Trigger | Duration (per target) |
|---------|------------------------|
| Pull request (Go paths) | `2m` |
| Nightly schedule | `15m` |
| `workflow_dispatch` | configurable (default `10m`) |

Targets: `FuzzParseOTLPHeaders`, `FuzzMaskEndpointURL`, `FuzzValidateRate`,
`FuzzValidatedSignalEndpointURL`, `FuzzParseEnvFloatThenValidateRate`.

On a schedule and on PRs, GitHub-hosted VMs run `go test -fuzz=...` for a
budgeted wall-clock time. Coverage guidance mutates inputs; failures fail CI
and can write minimized cases under `testdata/fuzz/<FuzzName>/`.

## Shelved

**Google OSS-Fuzz / ClusterFuzzLite onboarding is shelved** — not in progress.
If revisited later, use native Go fuzz targets already in `go/fuzz_test.go` as
the surface to instrument.
