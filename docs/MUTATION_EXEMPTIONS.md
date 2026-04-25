# Mutation Exemptions

The Python mutation gate (`scripts/run_mutation_gate.py`) targets a 100% kill
score. Some source lines cannot be killed by any reasonable unit test — for
example, ANSI formatting strings inside a log renderer, or a call-site default
that every caller overrides. Those lines carry a `# pragma: no mutate`
annotation so `mutmut` skips them.

Unmanaged exemptions rot. Every exemption therefore MUST carry a short
trailing reason. The `scripts/check_pragma_reasons.py` gate enforces this on
every PR.

## Policy

### When to exempt

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

### When NOT to exempt

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

### Exemption format

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
_logger.debug("otel.import.not_installed")  # pragma: no mutate — debug log string is non-semantic; behaviour lives in the return below
```

Bad (describes the line, not the exemption):

```python
_logger.debug("otel.import.not_installed")  # pragma: no mutate — logs a debug line
```

## Governance

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
  (`uv run python scripts/run_mutation_gate.py --min-mutation-score 100`) is
  unchanged; this policy document is about *who gets to use* `# pragma: no
  mutate` and under what documented justification.

## Current exemption footprint

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
