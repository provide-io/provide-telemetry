# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.tooling
_SCRIPT_PATH = Path("scripts/run_mutation_gate.py")
if not _SCRIPT_PATH.exists():
    pytest.skip("scripts/run_mutation_gate.py not available in this test runtime", allow_module_level=True)


def _load_script_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_mutation_gate", _SCRIPT_PATH)
    if spec is None or spec.loader is None:
        msg = "unable to load run_mutation_gate script module"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load_script_module()


def test_uv_mutmut_cmd_uses_optional_python_version() -> None:
    assert gate._uv_mutmut_cmd("3.11", "run") == ["uv", "run", "--python", "3.11", "mutmut", "run"]
    assert gate._uv_mutmut_cmd(None, "run") == ["uv", "run", "mutmut", "run"]


def test_mutmut_env_prefixes_pythonpath(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTHONPATH", "existing/path")
    env = gate._mutmut_env()
    assert env["PYTHONPATH"].endswith(":existing/path")
    assert "/scripts/_mutmut_shims" in env["PYTHONPATH"]


def test_mutmut_env_sets_pythonpath_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PYTHONPATH", raising=False)
    env = gate._mutmut_env()
    assert env["PYTHONPATH"].endswith("/scripts/_mutmut_shims")


def test_third_cpu_count_minimum_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate.os, "cpu_count", lambda: None)
    assert gate._third_cpu_count() == 1


def test_third_cpu_count_divides_available_cores(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate.os, "cpu_count", lambda: 24)
    assert gate._third_cpu_count() == 8


def test_run_mutation_gate_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "mutants").mkdir()
    stats_path = tmp_path / "mutants" / "mutmut-cicd-stats.json"

    states = [
        {
            "total": 10,
            "killed": 7,
            "survived": 3,
            "timeout": 0,
            "segfault": 0,
            "suspicious": 0,
            "no_tests": 0,
            "check_was_interrupted_by_user": 0,
        },
        {
            "total": 10,
            "killed": 9,
            "survived": 0,
            "timeout": 0,
            "segfault": 0,
            "suspicious": 0,
            "no_tests": 0,
            "check_was_interrupted_by_user": 0,
        },
    ]
    calls: list[list[str]] = []

    def _fake_run(cmd: list[str], *, env: dict[str, str] | None = None) -> str:
        assert env is not None
        calls.append(cmd)
        if "export-cicd-stats" in cmd:
            stats_path.parent.mkdir(exist_ok=True)
            stats_path.write_text(json.dumps(states.pop(0)), encoding="utf-8")
        return ""

    monkeypatch.setattr(gate, "_run", _fake_run)
    result = gate.run_mutation_gate("3.11", max_children=4, retries=1, min_mutation_score=80.0)
    assert result["survived"] == 0
    assert any("4" in cmd for cmd in calls)
    assert any("1" in cmd for cmd in calls)


def test_run_mutation_gate_fails_when_stats_never_clean(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "mutants").mkdir()
    stats_path = tmp_path / "mutants" / "mutmut-cicd-stats.json"

    bad_stats = {
        "total": 10,
        "killed": 9,
        "survived": 0,
        "timeout": 0,
        "segfault": 1,
        "suspicious": 0,
        "no_tests": 0,
        "check_was_interrupted_by_user": 0,
    }

    def _fake_run(cmd: list[str], *, env: dict[str, str] | None = None) -> str:
        assert env is not None
        if "export-cicd-stats" in cmd:
            stats_path.parent.mkdir(exist_ok=True)
            stats_path.write_text(json.dumps(bad_stats), encoding="utf-8")
        return ""

    monkeypatch.setattr(gate, "_run", _fake_run)
    with pytest.raises(RuntimeError, match="mutation gate failed"):
        gate.run_mutation_gate("3.11", max_children=2, retries=1, min_mutation_score=80.0)


def test_run_mutation_gate_fails_when_score_too_low(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "mutants").mkdir()
    stats_path = tmp_path / "mutants" / "mutmut-cicd-stats.json"

    low_score_stats = {
        "total": 10,
        "killed": 5,
        "survived": 5,
        "timeout": 0,
        "segfault": 0,
        "suspicious": 0,
        "no_tests": 0,
        "check_was_interrupted_by_user": 0,
    }

    def _fake_run(cmd: list[str], *, env: dict[str, str] | None = None) -> str:
        assert env is not None
        if "export-cicd-stats" in cmd:
            stats_path.parent.mkdir(exist_ok=True)
            stats_path.write_text(json.dumps(low_score_stats), encoding="utf-8")
        return ""

    monkeypatch.setattr(gate, "_run", _fake_run)
    with pytest.raises(RuntimeError, match="min_required"):
        gate.run_mutation_gate("3.11", max_children=2, retries=0, min_mutation_score=80.0)


def test_is_clean_rejects_timeout_and_segfault() -> None:
    assert gate._is_clean({"total": 10, "timeout": 5, "segfault": 0, "suspicious": 0, "no_tests": 0}) is False
    assert gate._is_clean({"total": 10, "timeout": 0, "segfault": 1, "suspicious": 0, "no_tests": 0}) is False


def test_is_clean_rejects_survivors() -> None:
    """The documented contract is a 100% kill score, not a high one.

    Without this a run with live survivors passed as long as the score cleared
    --min-mutation-score, which is an additional floor and not the bar.
    """
    assert gate._is_clean({"total": 100, "killed": 98, "survived": 2}) is False
    assert gate._is_clean({"total": 100, "killed": 100, "survived": 0}) is True


def test_run_forwards_env_to_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_subprocess_run(
        cmd: list[str],
        *,
        check: bool,
        env: dict[str, str] | None,
        capture_output: bool = False,
        text: bool = False,
    ) -> object:  # pragma: no cover - closure
        captured["cmd"] = cmd
        captured["check"] = check
        captured["env"] = env
        captured["capture_output"] = capture_output

        class _Done:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Done()

    monkeypatch.setattr(gate.subprocess, "run", _fake_subprocess_run)
    env = {"A": "1"}
    gate._run(["echo", "ok"], env=env)
    assert captured["cmd"] == ["echo", "ok"]
    assert captured["check"] is False
    assert captured["env"] == env


def test_main_uses_default_python_mutation_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate, "_third_cpu_count", lambda: 4)
    monkeypatch.setattr(gate, "run_mutation_gate", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        gate.argparse.ArgumentParser,
        "parse_args",
        lambda _self: gate.argparse.Namespace(
            python_version="3.11",
            max_children=None,
            retries=1,
            min_mutation_score=gate.DEFAULT_MIN_MUTATION_SCORE,
        ),
    )
    assert gate.main() == 0


class TestExecFailureDetection:
    """A mutant whose test command never ran must not count as killed.

    mutmut raises BadTestExecutionCommandsException inside the forked child
    when its per-mutant pytest invocation exits 4 (usage error). The raise
    happens before ``os._exit(result)``, so the child dies on an uncaught
    exception with a nonzero status — and nonzero is precisely how mutmut
    records "the tests detected this mutant". The run then reports 100% and
    exits 0 while some mutants were never actually tested.

    Observed at 110 occurrences in a 4767-mutant run: two parametrize ids held
    raw CR/LF, pytest re-escaped them on its second in-process collection, and
    the ids mutmut had recorded during the first one no longer matched anything.
    Replaying the argument list in a fresh process exited 0, which is why the
    forked child looked like the culprit — the real difference was that mutmut's
    process had already collected once. The ids are fixed at the source (see
    tests/tooling/test_parametrize_id_stability.py); this counter remains as the
    backstop for the next unearned kill, whatever causes it.
    """

    def test_counts_one_failure_per_occurrence(self) -> None:
        from scripts.run_mutation_gate import count_exec_failures

        # The marker appears twice per occurrence: once in the traceback frame
        # and once in the raised message.
        one = (
            '  File "mutmut/__main__.py", line 416, in execute_pytest\n'
            "    raise BadTestExecutionCommandsException(params)\n"
            "mutmut.__main__.BadTestExecutionCommandsException: Failed to run pytest\n"
        )
        assert count_exec_failures(one) == 1
        assert count_exec_failures(one * 3) == 3

    def test_a_clean_run_counts_none(self) -> None:
        from scripts.run_mutation_gate import count_exec_failures

        assert count_exec_failures("2734 passed, 43 skipped\nmutation_score=100.00\n") == 0

    def test_the_marker_is_the_one_mutmut_actually_raises(self) -> None:
        # Guard against the marker drifting from mutmut's real exception name,
        # which would make this check silently stop detecting anything — the
        # same class of failure it exists to catch.
        import mutmut.__main__ as mutmut_main

        from scripts.run_mutation_gate import _EXEC_FAILURE_MARKER

        assert hasattr(mutmut_main, _EXEC_FAILURE_MARKER)
