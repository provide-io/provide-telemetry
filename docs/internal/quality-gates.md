# Quality Gates

How the repository's performance, mutation-exemption, and fuzzing gates
work, and the policy behind each. Merged from the former PERFORMANCE.md,
MUTATION_EXEMPTIONS.md, and go-fuzzing.md.

## Performance budget gate

`provide-telemetry` enforces a coarse per-language performance budget in CI:
each hot-path benchmark must complete within `baseline_ns × tolerance_multiplier`
nanoseconds. The gate is **smoke-grade**, not micro-benchmark — it catches
catastrophic regressions (5×–10× slowdowns) without flaking on cloud-CI noise.

### When the gate fires

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

### Tolerances

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

### Running the gate locally

```bash
make perf              # Python, TypeScript, Go, Rust, C#
make perf-python       # one language
make perf-typescript
make perf-go
make perf-rust
make perf-csharp
```

Local runs use the OS bucket matching your machine. M-series Macs hit
`macos-arm64`, GitHub macOS runners hit `macos-arm64` too, Linux dev boxes
hit `linux-x86_64`, and so on.

### Updating baselines

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

### Adding new benchmarks

Each language's runner emits per-operation timings:

| Language | Runner | Output format |
|---|---|---|
| Python | `scripts/run_performance_smoke.py --emit-json` | `{op_name: ns_per_op, …}` |
| TypeScript | `typescript/scripts/perf-smoke.ts --emit-json` | `{op_name: ns_per_op, …}` |
| Go | `go test -bench=.` (parsed by `scripts/parse_go_bench.py`) | `{operation, ns_per_op}` lines |
| Rust | `cargo bench` (parsed by `scripts/parse_criterion.py`) | `{operation, ns_per_op}` lines |
| C# | `csharp/perf/Provide.Telemetry.Perf --emit-json` | `{op_name: ns_per_op, …}` |

To add a benchmark, append it to the language's runner. New ops appear in
the gate's output as `missing_baseline_entries` (non-fatal) until you seed
a baseline entry for them via `make perf-baseline-<lang>`.

### Why the gate is coarse on purpose

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
* C#: BenchmarkDotNet

These produce richer data for investigation but are not appropriate as
CI gates.

### Why the C# runner is hand-rolled

`csharp/perf/Provide.Telemetry.Perf` is a plain timing loop rather than a
BenchmarkDotNet harness, for the same reason the Python and TypeScript runners
are: the gate consumes one number per operation and compares it against a 5×
budget, so BenchmarkDotNet's statistics would be precision nobody reads, paid
for with a per-benchmark process launch on three runner OSes. It also keeps the
benchmark building from the same dependency set as the SDK itself. Reach for
BenchmarkDotNet when you are optimising a specific path, not when you are
gating one.

The project turns **tiered compilation off**
(`<TieredCompilation>false</TieredCompilation>`). .NET re-JITs hot methods on a
background thread, and whether that compile lands before a measurement loop
ends is a race — with the default settings the sanitize timings came out
bimodal across identical runs (~440 ns vs ~1320 ns for `sanitize_small_ns`, a
3× swing owing nothing to the SDK). With it off, repeated runs on the same
build agree to within ~15%.

## Mutation Exemptions

The Python mutation gate (`scripts/run_mutation_gate.py`) requires a **100%
kill**: `_is_clean()` passes only on zero survivors, zero timeouts, zero
suspicious and zero no-tests results. The `--min-mutation-score` floor
(default 95) is an *additional* guard, not the bar — it exists so a run that
somehow reports no survivors but an implausibly short total fails on the score
instead of passing silently. A run at 99% with one survivor fails.

Some source lines cannot be killed by any reasonable unit test — for example,
ANSI formatting strings inside a log renderer, or a call-site default that
every caller overrides. Those lines carry a `# pragma: no mutate` annotation
so `mutmut` skips them.

Unmanaged exemptions rot. Every exemption therefore MUST carry a short
trailing reason. The `scripts/check_pragma_reasons.py` gate enforces this on
every PR.

### Policy

#### When to exempt

Exempt a mutation only when *all* reasonable mutants of the line are
observably equivalent to the original. Typical candidates:

- **Log / warning message strings** — the text is operator-visible only; it
  does not influence control flow or data. Prefer asserting structured
  fields over asserting exact copy.
- **Formatting-only defaults and constants** — e.g. ANSI color escapes, level
  padding widths, join separators in renderers, timestamp format codes.
- **Call-site defaults that every caller overrides** — changing the default
  has no observable effect because no code path reaches it.
- **Typing-only `cast()` calls** — `typing.cast` is a no-op at runtime;
  mutating its type argument cannot change behaviour.
- **Import fallbacks under optional extras** — e.g. `try: import otel
  except ImportError: _logger.debug("otel.unavailable")`. The fallback is
  exercised by otel-off tests; the debug message is not load-bearing.
- **Defensive invariants behind already-proven guards** — e.g. a second
  `isinstance` check after upstream recursion already narrowed the type.
  The mutant's true branch is unreachable.
- **Sentinel defaults that disable a feature** — a parameter like
  `auto_slo: bool = False` where the `True` path is covered by explicit
  call sites.

#### When NOT to exempt

Do *not* reach for `# pragma: no mutate` to silence a mutant that points at
a real test gap. In particular:

- **Business logic branches** — comparison operators, boolean combinators,
  numeric boundaries on application data.
- **Conditional branches in the hot path** — sampling cut-offs, rate limits,
  backpressure thresholds, cardinality guards.
- **Error-recovery paths** — retry counts, circuit-breaker thresholds,
  half-open probe state.
- **Security- or governance-enforcing lines** — PII matchers, consent
  predicates, secret detection patterns.
- **Any line whose mutant would change an exported value** — wire-format
  fields, metric names, span names, public attribute keys.

If a mutant on one of these lines is surviving, the right fix is to add a
test that observes the behaviour, not to pin the line.

#### Exemption format

The gate accepts four reason separators:

```python
x = 1  # pragma: no mutate — reason text
x = 1  # pragma: no mutate -- reason text
x = 1  # pragma: no mutate  # reason text
x = 1  # pragma: no mutate: reason text
```

The em-dash form is preferred for readability. Reasons should be one phrase
(roughly ten words or fewer). They should be *factual*, describing *why* the
mutant is equivalent — not describing what the line does.

Good:

```python
_logger.debug(
    "otel.import.not_installed"
)  # pragma: no mutate — debug log string is non-semantic; behaviour lives in the return below
```

Bad (describes the line, not the exemption):

```python
_logger.debug("otel.import.not_installed")  # pragma: no mutate — logs a debug line
```

### Governance

- `scripts/check_pragma_reasons.py` scans `src/provide/telemetry/**/*.py` and
  exits non-zero if any `# pragma: no mutate` lacks a reason. Run it locally
  before submitting a PR:

  ```bash
  uv run python scripts/check_pragma_reasons.py
  ```

- The gate also supports checking `# pragma: no cover`. Opt in with
  `--kinds "no cover"` or `--kinds "no mutate" "no cover"`.

- Unit tests for the gate live at `tests/tooling/test_check_pragma_reasons.py`
  and run under the `tooling` pytest marker.

- The mutation gate itself
  (`uv run python scripts/run_mutation_gate.py --min-mutation-score 95`, where
  that floor sits on top of the zero-survivor requirement rather than replacing
  it) is unchanged; this policy document is about *who gets to use*
  `# pragma: no mutate` and under what documented justification.

### Current exemption footprint

The Python tree carries roughly 220 `# pragma: no mutate` annotations. They
cluster around four buckets:

| Bucket | Representative files | Typical reason |
| --- | --- | --- |
| Pretty / console rendering | `logger/pretty.py`, `logger/processors.py` | ANSI/formatting strings are non-semantic |
| Optional OTel wiring | `_otel.py`, `metrics/provider.py`, `tracing/provider.py`, `resilient_exporter.py` | Import / fallback branch only reachable under otel extra |
| Event-loop resilience | `resilience.py`, `setup.py`, `metrics/provider.py`, `tracing/provider.py` | `warnings.warn` wording, stacklevel tuning, best-effort warning emission |
| Logging pipeline scaffolding | `logger/core.py`, `logger/processors.py`, `pii.py` | Default values overridden by live runtime config; typing casts; hash-digest contract |

Remaining exemptions are small-count items scattered across `asgi/`,
`backpressure.py`, `cardinality.py`, `consent.py`, `propagation.py`,
`sampling.py`, `receipts.py`, and `health.py`. Each carries an inline reason
that the gate validates.

New files added to the tree inherit the policy automatically: the gate scans
`src/provide/telemetry/**/*.py`, so fresh annotations are checked on the
next run.

## Go coverage-guided fuzzing

The Go package (`go/`) ships **native Go 1.18+ fuzz targets** for config
parsing and redaction.

### Day-to-day: `go test -fuzz`

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

### Local OSS-Fuzz (libFuzzer binaries via Docker)

Same builder image / `compile_native_go_fuzzer` path ClusterFuzz would use,
run **on your machine** only.

```bash
# From repo root (needs Docker + network to pull base images once):
./scripts/oss-fuzz-local.sh build
./scripts/oss-fuzz-local.sh run FuzzValidateRate
./scripts/oss-fuzz-local.sh list
```

Details: [`infra/oss-fuzz/README.md`](../../infra/oss-fuzz/README.md).

**Requirements:** Docker. Prefer **linux/amd64** hosts; Apple Silicon works via
emulation but is slow. `OSS_FUZZ_DIR` points at a local `google/oss-fuzz` clone
(auto-cloned if missing).

### Shelved: Google OSS-Fuzz *cloud*

Submitting `projects/provide-telemetry` to **google/oss-fuzz** for 24/7
Google-hosted ClusterFuzz is **not** planned right now. The local recipe stays
so we can prove and iterate the build without onboarding.
