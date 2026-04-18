# Parity Harness OTel Gating — Design

SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc

## Problem

The behavioral parity harness checks Python runner availability with `uv --version`, which
only confirms the `uv` tool is present — not that the OpenTelemetry dependency stack
(`opentelemetry`, `opentelemetry_sdk`, `otlp_http_exporter`) is installed. Two
OTel-dependent probe functions (`_case_per_signal_logs_endpoint`,
`_case_provider_identity_reconfigure` in `spec/parity_probe_support.py`) are registered and
executed unconditionally. When the OTel extras are absent, these probes fail with confusing
assertion errors instead of a clear "install the extra" message.

The pytest test layer has the same gap: two test functions in
`tests/tooling/test_run_behavioral_parity.py` gate on
`pytest.importorskip("opentelemetry")`, which only checks the base package — not the SDK or
exporter. On a system where only the base `opentelemetry` package is installed (but not
`opentelemetry-sdk[otlp]`), the skip is bypassed and the tests fail confusingly.

## Decision

Add a `_has_otel_stack()` helper to `spec/parity_probe_support.py`. Call it in both
OTel-dependent probe functions (fail loudly with an actionable `RuntimeError`) and in both
pytest tests (skip with a clear message). One helper, four callsites, no new abstractions.

## Files Changed

| File | Change |
|------|--------|
| `spec/parity_probe_support.py` | Add `_has_otel_stack()`; add guard at top of `_case_per_signal_logs_endpoint` and `_case_provider_identity_reconfigure` |
| `tests/tooling/test_run_behavioral_parity.py` | Replace two `pytest.importorskip("opentelemetry")` calls with `_has_otel_stack()` skip guards |

No other files change.

## Implementation

### `_OTEL_REQUIRED_CASE_IDS` and `_has_otel_stack()` in `spec/parity_probe_support.py`

Add a module-level constant and a helper near the top of the file, after imports:

```python
# Case IDs whose Python probe subprocess requires the OTel extras to be installed.
_OTEL_REQUIRED_CASE_IDS: frozenset[str] = frozenset(
    {"per_signal_logs_endpoint", "provider_identity_reconfigure"}
)


def _has_otel_stack() -> bool:
    """Return True when the full OpenTelemetry SDK + OTLP exporter stack is importable."""
    import importlib.util

    return all(
        importlib.util.find_spec(pkg) is not None
        for pkg in (
            "opentelemetry",
            "opentelemetry.sdk",
            "opentelemetry.exporter.otlp.proto.http",
        )
    )
```

Uses `importlib.util.find_spec` — no side-effect imports, safe to call at any point.

### Guard in `run_runtime_probe_check()`

The two OTel-sensitive probes are `case_id` values dispatched inside the existing case loop
in `run_runtime_probe_check()`. The guard runs once before the loop begins: if any
OTel-required case is present in the fixture list AND the OTel stack is absent, raise
`RuntimeError` immediately with an actionable message.

```python
def run_runtime_probe_check(...) -> bool:
    runners = [r for r in _runtime_probe_runners(...) if r.name in selected]
    fixtures = _load_runtime_probe_fixtures(fixtures_path)
    cases = fixtures.get("cases", [])

    # Fail early with a clear message if OTel-required cases are present but
    # the opentelemetry-sdk[otlp] extra is not installed.
    otel_case_ids = {str(c["id"]) for c in cases} & _OTEL_REQUIRED_CASE_IDS
    if otel_case_ids and not _has_otel_stack():
        raise RuntimeError(
            f"Runtime probe cases {sorted(otel_case_ids)} require the "
            "opentelemetry-sdk[otlp] extra — run: uv sync --extra otel"
        )

    all_ok = True
    # ... rest of existing loop unchanged ...
```

Raising before the loop aborts the harness cleanly instead of producing confusing
per-runner assertion failures deep in the output.
```

### Test-level guard

In `tests/tooling/test_run_behavioral_parity.py`, replace both occurrences of:

```python
pytest.importorskip("opentelemetry")
```

with:

```python
from spec.parity_probe_support import _has_otel_stack
if not _has_otel_stack():
    pytest.skip("requires opentelemetry-sdk[otlp] (run: uv sync --extra otel)")
```

This gives pytest a proper `SKIPPED` result (green in CI output) with an actionable message,
rather than a cryptic import error or failing assertion.

## Testing the Fix

Add tests to `tests/tooling/test_run_behavioral_parity.py` (or a new
`tests/tooling/test_parity_probe_support.py` if the existing file is near the 500-LOC cap):

### Test 1 — `_has_otel_stack` returns False when a package is missing

```python
def test_has_otel_stack_returns_false_when_package_missing(monkeypatch):
    import importlib.util
    real_find_spec = importlib.util.find_spec

    def patched_find_spec(name):
        if name == "opentelemetry.sdk":
            return None
        return real_find_spec(name)

    monkeypatch.setattr(importlib.util, "find_spec", patched_find_spec)
    from spec.parity_probe_support import _has_otel_stack
    assert not _has_otel_stack()
```

### Test 2 — `run_runtime_probe_check` raises RuntimeError with actionable message when OTel stack missing

```python
def test_run_runtime_probe_check_raises_when_otel_stack_missing(tmp_path, monkeypatch):
    import importlib.util
    monkeypatch.setattr(importlib.util, "find_spec", lambda _: None)

    # Write a minimal fixtures file containing one OTel-required case.
    fixtures = tmp_path / "runtime_probe_fixtures.yaml"
    fixtures.write_text("cases:\n  - id: per_signal_logs_endpoint\n    kind: summary\n    expected: {}\n")

    from spec.parity_probe_support import run_runtime_probe_check
    with pytest.raises(RuntimeError, match="opentelemetry-sdk\\[otlp\\]"):
        run_runtime_probe_check(
            repo=Path("."),
            selected={"python"},
            cargo_bin="cargo",
            cargo_env={},
            probe_env={},
            fixtures_path=fixtures,
        )
```

## Error Handling

- The `RuntimeError` from the probe is intentional: it surfaces in the harness output as a
  clear failure, not a confusing `AssertionError`. Callers that run the harness in CI will see
  the install instruction immediately.
- The `pytest.skip` path means the two test functions appear as `s` (skipped) in pytest
  output rather than `F` (failed) — correct behavior when the dependency is genuinely absent.

## What Does Not Change

- Probe registration logic — probes are still registered unconditionally; the guard is inside
  the probe body, not at registration time (YAGNI: only two probes are affected).
- All non-OTel probes — untouched.
- The `uv --version` runner check — it correctly answers "can we run Python at all?" and is
  not responsible for dep-set checks.
- Any Go, Rust, or TypeScript probe paths.
