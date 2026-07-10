# OSS-Fuzz project scaffold (provide-telemetry Go)

Copy these files into a PR on
[google/oss-fuzz](https://github.com/google/oss-fuzz) as
`projects/provide-telemetry/{project.yaml,Dockerfile,build.sh}`.

Do **not** merge them into google/oss-fuzz until maintainers have agreed to
onboarding and updated `primary_contact` / `auto_ccs`.

## Files

| File | Role |
|------|------|
| `project.yaml` | Language, contacts, engines, sanitizers |
| `Dockerfile` | `base-builder-go` + clone this repo |
| `build.sh` | `compile_native_go_fuzzer` for each `Fuzz*` target in `go/` |

## Local smoke (optional)

Requires Docker and a checkout of google/oss-fuzz:

```bash
# From google/oss-fuzz clone, after copying projects/provide-telemetry/
python infra/helper.py build_image provide-telemetry
python infra/helper.py build_fuzzers --sanitizer address provide-telemetry
python infra/helper.py run_fuzzer provide-telemetry FuzzValidateRate
```

See: https://google.github.io/oss-fuzz/getting-started/new-project-guide/go-lang/
