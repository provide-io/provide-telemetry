# Performance budget gate

`provide-telemetry` enforces a coarse per-language performance budget in CI:
each hot-path benchmark must complete within `baseline_ns × tolerance_multiplier`
nanoseconds. The gate is **smoke-grade**, not micro-benchmark — it catches
catastrophic regressions (5×–10× slowdowns) without flaking on cloud-CI noise.

## When the gate fires

A `performance-smoke` job runs on every push that touches the language's source
files, across all three CI runner OSes (Linux, macOS, Windows). Each job:

1. Runs the language's hot-path benchmark suite.
2. Pipes the per-operation timings through `scripts/perf_check.py`.
3. Compares each measurement against `baselines/perf-<lang>.json` for the
   runner's OS bucket (`linux-x86_64`, `macos-arm64`, `windows-x86_64`).
4. Exits 1 if any operation exceeds its budget; exits 0 otherwise.

When a baseline bucket is missing for the current OS (e.g. on a fresh runner
the first time), the gate exits 0 with a hint and the operator seeds the
bucket by hand from the printed measurements.

## Tolerances

The default tolerance is **5×** — fail when measured > baseline × 5. Cloud
runners can vary 30–50% between runs from neighbour noise alone, so tighter
bounds would flake constantly. Per-operation overrides bump that to **10×**
for noise-floor or single-shot measurements:

| Op | Multiplier | Why |
|---|---|---|
| `import()` (TypeScript) | 10× | Single-shot cold-cache measurement |
| `logger.info()` (TypeScript) | 10× | 7ns measurement when logger is silent — noise floor |
| Everything else | 5× | Standard per-iter timing |

The multiplier lives in `baselines/perf-<lang>.json`:

```json
{
  "linux-x86_64": {
    "event_name_ns": {"baseline_ns": 281, "tolerance_multiplier": 5.0}
  }
}
```

## Running the gate locally

```bash
make perf              # all four languages
make perf-python       # one language
make perf-typescript
make perf-go
make perf-rust
```

Local runs use the OS bucket matching your machine. M-series Macs hit
`macos-arm64`, GitHub macOS runners hit `macos-arm64` too, Linux dev boxes
hit `linux-x86_64`, and so on.

## Updating baselines

Baselines are checked into the repo and updated **deliberately** — they do
not auto-regenerate. Two situations call for an update:

1. **Seeding a new OS bucket** (e.g. first time a runner class appears).
2. **Refreshing after a deliberate perf change** (e.g. a refactor that makes
   something legitimately slower or faster — adjust before merging).

To update a baseline:

```bash
make perf-baseline-python   # prints fresh JSON to stdout
```

Copy the printed measurements into `baselines/perf-<lang>.json` under the
appropriate OS bucket. **Do this on the runner class that owns the bucket** —
M2 Mac numbers are not a valid stand-in for an Intel Linux runner.

For Linux/Windows buckets you cannot regenerate locally, push the change and
read the measurements from the CI log. The "missing bucket" branch in
`perf_check.py` prints them in the same format the baseline file uses.

## Adding new benchmarks

Each language's runner emits per-operation timings:

| Language | Runner | Output format |
|---|---|---|
| Python | `scripts/run_performance_smoke.py --emit-json` | `{op_name: ns_per_op, …}` |
| TypeScript | `typescript/scripts/perf-smoke.ts --emit-json` | `{op_name: ns_per_op, …}` |
| Go | `go test -bench=.` (parsed by `scripts/parse_go_bench.py`) | `{operation, ns_per_op}` lines |
| Rust | `cargo bench` (parsed by `scripts/parse_criterion.py`) | `{operation, ns_per_op}` lines |

To add a benchmark, append it to the language's runner. New ops appear in
the gate's output as `missing_baseline_entries` (non-fatal) until you seed
a baseline entry for them via `make perf-baseline-<lang>`.

## Why the gate is coarse on purpose

The smoke-grade design (5×/10× tolerance, no statistical analysis, no
per-commit precision) is a deliberate trade-off:

* **Catches what matters** — any regression that changes the order of
  magnitude of a hot-path op gets caught immediately.
* **Doesn't flake** — runner noise and load do not produce false failures.
* **Cheap to maintain** — baselines are JSON files; no statistical baseline
  store, no comparison logic beyond a single multiplier.

For finer-grained perf work, use the language-native tools directly:

* Python: `pytest-benchmark` with statistical comparison
* TypeScript: `vitest bench` or `tinybench`
* Go: `benchstat` over `go test -bench` results
* Rust: criterion's full report mode (without `--quick`)

These produce richer data for investigation but are not appropriate as
CI gates.
