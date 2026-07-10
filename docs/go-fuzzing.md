# Go coverage-guided fuzzing

The Go package (`go/`) ships **native Go 1.18+ fuzz targets** for config
parsing and redaction. Locally and in GitHub Actions they use:

```bash
cd go
make fuzz FUZZTIME=30s    # short
make fuzz FUZZTIME=5m     # longer
```

CI workflow: `.github/workflows/ci-go-fuzz.yml`

| Trigger | Duration (per target) |
|---------|------------------------|
| Pull request (Go paths) | `2m` |
| Nightly schedule | `15m` |
| `workflow_dispatch` | configurable (default `10m`) |

Targets: `FuzzParseOTLPHeaders`, `FuzzMaskEndpointURL`, `FuzzValidateRate`,
`FuzzValidatedSignalEndpointURL`, `FuzzParseEnvFloatThenValidateRate`.

## What “continuous cloud fuzzing” means

There are two layers:

### 1. What we run today — GitHub Actions continuous fuzz

- On a **schedule** and on **PRs**, GitHub spins **cloud VMs** (`ubuntu-latest`).
- Those VMs run `go test -fuzz=... -fuzztime=...` for a budgeted wall-clock time.
- Coverage guidance mutates inputs and keeps “interesting” cases that hit new edges.
- If an invariant fails, CI fails and Go writes a minimized failing input under
  `testdata/fuzz/<FuzzName>/` for replay.

That is continuous and it is in the cloud — but the **budget is our CI minutes**
and the **corpus does not automatically grow across days** unless we persist it
(artifact / storage repo).

### 2. OSS-Fuzz — Google’s continuous fuzzing *fleet*

[OSS-Fuzz](https://google.github.io/oss-fuzz/) is a **free Google service** for
critical open-source projects. Once a project is **accepted**:

1. Maintainers add a project under
   [`google/oss-fuzz`](https://github.com/google/oss-fuzz) (`projects/<name>/`
   with `project.yaml`, `Dockerfile`, `build.sh`).
2. Google’s **ClusterFuzz** infrastructure builds the fuzzers from that recipe
   on every relevant change and runs them **continuously** on a large pool of
   machines (not a single 15‑minute CI job).
3. Corpora are stored and **reused forever** — coverage compounds over weeks.
4. Crashes are filed automatically (private bugs until fixed, with a disclosure
   window). Security-relevant issues get tracked as such.
5. Native Go fuzz targets are compiled via
   [`compile_native_go_fuzzer`](https://google.github.io/oss-fuzz/getting-started/new-project-guide/go-lang/#native-go-fuzzing-support)
   into libFuzzer binaries so they plug into the same ClusterFuzz pipeline.

**In short:** OSS-Fuzz = *Google runs your fuzzers 24/7 on their hardware and
keeps the corpus*. GitHub Actions fuzz = *we rent short bursts of GitHub VMs*.

### ClusterFuzzLite

[ClusterFuzzLite](https://google.github.io/clusterfuzzlite/) is the **self-hosted
CI cousin**: PR + batch fuzz on *your* CI (GitHub Actions, etc.) with optional
corpus storage. It uses the same build integration style as OSS-Fuzz
(Dockerfile + build.sh). For pure native `go test -fuzz` targets, the workflow
above is usually simpler; ClusterFuzzLite pays off when you want OSS-Fuzz-style
artifacts, SARIF, and corpus repos without joining OSS-Fuzz.

## Applying to OSS-Fuzz (when ready)

Scaffold lives in [`infra/oss-fuzz/`](../infra/oss-fuzz/README.md). Steps:

1. Open a PR against **google/oss-fuzz** adding `projects/provide-telemetry/`
   from that scaffold (adjust contact emails, repo URL).
2. Wait for OSS-Fuzz onboarding review.
3. After merge, ClusterFuzz builds and runs continuously; watch
   [OSS-Fuzz issues](https://bugs.chromium.org/p/oss-fuzz/issues/list) for reports.

Projects must be open source and widely used; acceptance is not automatic.
