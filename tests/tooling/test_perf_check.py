# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Unit tests for scripts/perf_check.py — the cross-language perf budget gate."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import types  # used by the imported module's return type hints
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "perf_check.py"


def _load_perf_check() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("perf_check", str(SCRIPT_PATH))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["perf_check"] = mod
    spec.loader.exec_module(mod)
    return mod


perf_check = _load_perf_check()


# ── detect_os_key ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("system", "machine", "expected"),
    [
        ("Linux", "x86_64", "linux-x86_64"),
        ("Darwin", "arm64", "macos-arm64"),
        ("Darwin", "aarch64", "macos-arm64"),
        ("Windows", "AMD64", "windows-x86_64"),
        ("Linux", "aarch64", "linux-arm64"),
    ],
)
def test_detect_os_key_normalises(monkeypatch: pytest.MonkeyPatch, system: str, machine: str, expected: str) -> None:
    monkeypatch.setattr(perf_check.platform, "system", lambda: system)
    monkeypatch.setattr(perf_check.platform, "machine", lambda: machine)
    assert perf_check.detect_os_key() == expected


# ── parse_measurements ────────────────────────────────────────────────────────


def test_parse_measurements_single_object() -> None:
    payload = json.dumps({"event_name_ns": 142.5, "should_sample_ns": 13.2})
    out = perf_check.parse_measurements(io.StringIO(payload))
    assert out == {"event_name_ns": 142.5, "should_sample_ns": 13.2}


def test_parse_measurements_skips_non_numeric_fields() -> None:
    # The Python runner historically embeds non-numeric metadata (e.g. "ci_detected": True).
    # Those fields must not crash the parser; only numeric values are kept.
    payload = json.dumps({"event_name_ns": 100.0, "ci_detected": True, "label": "smoke"})
    out = perf_check.parse_measurements(io.StringIO(payload))
    assert out == {"event_name_ns": 100.0, "ci_detected": 1.0}  # bool is a numeric subtype


def test_parse_measurements_line_oriented() -> None:
    payload = (
        '{"operation": "event_name", "ns_per_op": 142.5}\n'
        '{"operation": "should_sample", "ns_per_op": 13.2}\n'
        "non-json garbage line\n"
    )
    out = perf_check.parse_measurements(io.StringIO(payload))
    assert out == {"event_name": 142.5, "should_sample": 13.2}


def test_parse_measurements_empty_raises() -> None:
    with pytest.raises(ValueError, match="no input"):
        perf_check.parse_measurements(io.StringIO(""))


def test_parse_measurements_picks_last_object_with_trailing_text() -> None:
    # Some runners print the measurements then a status line; the last
    # decodable JSON object is the canonical measurements blob.
    payload = '{"event_name_ns": 142.5}\nDONE\n'
    out = perf_check.parse_measurements(io.StringIO(payload))
    assert out == {"event_name_ns": 142.5}


# ── evaluate ──────────────────────────────────────────────────────────────────


def _bucket(op: str, baseline_ns: float, tolerance: float = 5.0) -> dict[str, dict[str, float]]:
    return {op: {"baseline_ns": baseline_ns, "tolerance_multiplier": tolerance}}


def test_evaluate_passes_within_budget() -> None:
    failures, missing = perf_check.evaluate({"event_name_ns": 400.0}, _bucket("event_name_ns", 100.0))
    assert failures == []
    assert missing == []


def test_evaluate_fails_outside_budget() -> None:
    # 600ns measured > 100 * 5.0 = 500ns budget
    failures, _ = perf_check.evaluate({"event_name_ns": 600.0}, _bucket("event_name_ns", 100.0))
    assert len(failures) == 1
    assert "event_name_ns" in failures[0]
    assert "500.0" in failures[0]


def test_evaluate_passes_at_exact_budget_boundary() -> None:
    # Boundary check: equal to budget must pass (strict > comparison).
    failures, _ = perf_check.evaluate({"event_name_ns": 500.0}, _bucket("event_name_ns", 100.0))
    assert failures == []


def test_evaluate_reports_missing_entries() -> None:
    _, missing = perf_check.evaluate({"new_op": 100.0, "known_op": 50.0}, _bucket("known_op", 100.0))
    assert missing == ["new_op"]


def test_evaluate_uses_default_tolerance_when_unset() -> None:
    # No tolerance_multiplier in entry → comparator defaults to 5.0.
    bucket = {"op": {"baseline_ns": 100.0}}
    # 450ns measured ≤ 100 x 5.0 = 500ns budget → pass
    failures, _ = perf_check.evaluate({"op": 450.0}, bucket)
    assert failures == []
    # 600ns measured > 500ns budget → fail
    failures, _ = perf_check.evaluate({"op": 600.0}, bucket)
    assert len(failures) == 1


# ── load_baseline ─────────────────────────────────────────────────────────────


def test_load_baseline_missing_file_returns_empty(tmp_path: Path) -> None:
    assert perf_check.load_baseline(tmp_path / "nope.json") == {}


def test_load_baseline_reads_valid_file(tmp_path: Path) -> None:
    p = tmp_path / "b.json"
    p.write_text(json.dumps({"linux-x86_64": {"op": {"baseline_ns": 100, "tolerance_multiplier": 2.0}}}))
    out = perf_check.load_baseline(p)
    assert out["linux-x86_64"]["op"]["baseline_ns"] == 100


def test_load_baseline_rejects_non_object(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("[]")
    with pytest.raises(ValueError, match="must contain a JSON object"):
        perf_check.load_baseline(p)


# ── main (end-to-end via subprocess) ──────────────────────────────────────────


def _run_main(monkeypatch: pytest.MonkeyPatch, stdin_text: str, argv: list[str]) -> tuple[int, str]:
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_text))
    monkeypatch.setattr(sys, "argv", ["perf_check.py", *argv])
    captured = io.StringIO()
    monkeypatch.setattr(sys, "stdout", captured)
    rc = perf_check.main()
    return rc, captured.getvalue()


def test_main_missing_baseline_bucket_exits_zero_with_hint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    baseline = tmp_path / "perf-x.json"
    baseline.write_text(json.dumps({"other-os": {"op": {"baseline_ns": 100}}}))
    rc, out = _run_main(
        monkeypatch,
        '{"event_name_ns": 142.5}',
        ["--lang", "x", "--baseline-file", str(baseline), "--os-key", "linux-x86_64"],
    )
    assert rc == 0
    payload = json.loads(out)
    assert payload["baseline_status"] == "missing"
    assert payload["measurements"] == {"event_name_ns": 142.5}


def test_main_failures_exit_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    baseline = tmp_path / "perf-x.json"
    baseline.write_text(
        json.dumps({"linux-x86_64": {"event_name_ns": {"baseline_ns": 100.0, "tolerance_multiplier": 2.0}}})
    )
    rc, out = _run_main(
        monkeypatch,
        '{"event_name_ns": 999.0}',
        ["--lang", "x", "--baseline-file", str(baseline), "--os-key", "linux-x86_64"],
    )
    assert rc == 1
    payload = json.loads(out)
    assert payload["failures"]
    assert "event_name_ns" in payload["failures"][0]


def test_main_report_only_never_exits_nonzero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    baseline = tmp_path / "perf-x.json"
    baseline.write_text(
        json.dumps({"linux-x86_64": {"event_name_ns": {"baseline_ns": 100.0, "tolerance_multiplier": 2.0}}})
    )
    rc, _out = _run_main(
        monkeypatch,
        '{"event_name_ns": 999.0}',
        [
            "--lang",
            "x",
            "--baseline-file",
            str(baseline),
            "--os-key",
            "linux-x86_64",
            "--report-only",
        ],
    )
    assert rc == 0


def test_main_input_parse_error_exits_two(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    baseline = tmp_path / "perf-x.json"
    baseline.write_text("{}")
    rc, _ = _run_main(
        monkeypatch,
        "",  # empty stdin
        ["--lang", "x", "--baseline-file", str(baseline), "--os-key", "linux-x86_64"],
    )
    assert rc == 2
