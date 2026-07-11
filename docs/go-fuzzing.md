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

## Applying to OSS-Fuzz (Google fleet)

Scaffold lives in [`infra/oss-fuzz/`](../infra/oss-fuzz/README.md).

### Smoke (prove the recipe on linux/amd64)

Workflow [`.github/workflows/oss-fuzz-smoke.yml`](../.github/workflows/oss-fuzz-smoke.yml)
clones `google/oss-fuzz`, installs our project files, runs:

```text
python3 infra/helper.py build_fuzzers provide-telemetry <this-repo>
python3 infra/helper.py run_fuzzer provide-telemetry FuzzValidateRate -- -max_total_time=30
```

on **GitHub-hosted ubuntu-latest** (native amd64 — not Mac/qemu). That is the
same builder image and `compile_native_go_fuzzer` path ClusterFuzz uses.

### Onboard to Google continuous fuzzing

1. Ensure `go/fuzz_test.go` is on the default branch of
   `github.com/provide-io/provide-telemetry` (this PR).
2. Open a PR against **google/oss-fuzz** adding
   `projects/provide-telemetry/{project.yaml,Dockerfile,build.sh}` from
   `infra/oss-fuzz/`.
3. OSS-Fuzz maintainers review; after merge, ClusterFuzz builds on every
   relevant change and runs fuzzers **continuously**, keeping a permanent corpus.
4. Crashes appear in the [OSS-Fuzz issue tracker](https://bugs.chromium.org/p/oss-fuzz/issues/list)
   (private until fixed / disclosure window for security bugs).

Projects must be open source; acceptance is not automatic (usage/popularity bar).
