# Local OSS-Fuzz recipe (not cloud)

Build and run libFuzzer binaries with Google’s **local** OSS-Fuzz helper.
This does **not** enroll the project in Google’s continuous cloud fleet.

## Prerequisites

- Docker (linux/amd64 preferred; on Apple Silicon use Docker’s amd64 emulation
  or a Linux/amd64 machine — native amd64 is much faster)
- A clone of [google/oss-fuzz](https://github.com/google/oss-fuzz)

## One-shot (from this repo)

```bash
# From provide-telemetry repo root:
./scripts/oss-fuzz-local.sh build
./scripts/oss-fuzz-local.sh run FuzzValidateRate
./scripts/oss-fuzz-local.sh run FuzzMaskEndpointURL -- -max_total_time=60
```

`OSS_FUZZ_DIR` defaults to `$HOME/src/oss-fuzz` (or `/tmp/oss-fuzz` if that
exists). Override:

```bash
OSS_FUZZ_DIR=/path/to/oss-fuzz ./scripts/oss-fuzz-local.sh build
```

## Manual helper.py

```bash
git clone --depth 1 https://github.com/google/oss-fuzz.git
mkdir -p oss-fuzz/projects/provide-telemetry
cp infra/oss-fuzz/{project.yaml,Dockerfile,build.sh} oss-fuzz/projects/provide-telemetry/
chmod +x oss-fuzz/projects/provide-telemetry/build.sh

cd oss-fuzz
python3 infra/helper.py build_image provide-telemetry
python3 infra/helper.py build_fuzzers --sanitizer address provide-telemetry /path/to/provide-telemetry
python3 infra/helper.py run_fuzzer provide-telemetry FuzzValidateRate -- -max_total_time=30
ls build/out/provide-telemetry/
```

## What this is / is not

| | |
|--|--|
| **Is** | Same Docker builder + `compile_native_go_fuzzer` path ClusterFuzz uses |
| **Is** | Local (or your machine’s Docker) proof of the recipe |
| **Is not** | Submission to `google/oss-fuzz` or 24/7 Google-hosted fuzzing |

Cloud onboarding remains **shelved**. Day-to-day continuous fuzz stays on
GitHub Actions: `go test -fuzz` via `.github/workflows/ci-go-fuzz.yml`.
