# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 MindTenet LLC
# This file is part of Undef Telemetry.
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


def test_half_cpu_count_minimum_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate.os, "cpu_count", lambda: None)
    assert gate._half_cpu_count() == 1


def test_half_cpu_count_divides_available_cores(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate.os, "cpu_count", lambda: 24)
    assert gate._half_cpu_count() == 12


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

    def _fake_run(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
        assert env is not None
        calls.append(cmd)
        if "export-cicd-stats" in cmd:
            stats_path.parent.mkdir(exist_ok=True)
            stats_path.write_text(json.dumps(states.pop(0)), encoding="utf-8")

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

    def _fake_run(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
        assert env is not None
        if "export-cicd-stats" in cmd:
            stats_path.parent.mkdir(exist_ok=True)
            stats_path.write_text(json.dumps(bad_stats), encoding="utf-8")

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

    def _fake_run(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
        assert env is not None
        if "export-cicd-stats" in cmd:
            stats_path.parent.mkdir(exist_ok=True)
            stats_path.write_text(json.dumps(low_score_stats), encoding="utf-8")

    monkeypatch.setattr(gate, "_run", _fake_run)
    with pytest.raises(RuntimeError, match="min_required"):
        gate.run_mutation_gate("3.11", max_children=2, retries=0, min_mutation_score=80.0)


def test_is_clean_ignores_timeout_but_rejects_segfault() -> None:
    assert gate._is_clean({"total": 10, "timeout": 5, "segfault": 0, "suspicious": 0, "no_tests": 0}) is True
    assert gate._is_clean({"total": 10, "timeout": 0, "segfault": 1, "suspicious": 0, "no_tests": 0}) is False


def test_run_forwards_env_to_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_subprocess_run(
        cmd: list[str], *, check: bool, env: dict[str, str] | None
    ) -> object:  # pragma: no cover - closure
        captured["cmd"] = cmd
        captured["check"] = check
        captured["env"] = env

        class _Done:
            returncode = 0

        return _Done()

    monkeypatch.setattr(gate.subprocess, "run", _fake_subprocess_run)
    env = {"A": "1"}
    gate._run(["echo", "ok"], env=env)
    assert captured["cmd"] == ["echo", "ok"]
    assert captured["check"] is False
    assert captured["env"] == env
