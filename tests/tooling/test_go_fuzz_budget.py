# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""The Go fuzz gate must fit its job budget, with room to retry one target.

Five targets at the scheduled fuzztime ran 75 minutes against a 90-minute job
cap — 83% of the budget, leaving no room for the rerun that Go's end-of-run
deadline race requires. This pins the arithmetic so a longer fuzztime or an
extra target cannot quietly reintroduce that, and pins the runner's target list
against the file the targets live in.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.tooling


def _project_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "VERSION").exists():
            return parent
    raise FileNotFoundError("Could not locate project root (no VERSION file found)")


_ROOT = _project_root()
_WORKFLOW = _ROOT / ".github" / "workflows" / "ci-go-fuzz.yml"
_RUNNER = _ROOT / "ci" / "run-go-fuzz.sh"
_FUZZ_TESTS = _ROOT / "go" / "fuzz_test.go"

if not _WORKFLOW.exists() or not _RUNNER.exists():  # pragma: no cover - trimmed sandbox
    pytest.skip("workflow or runner not available in this test runtime", allow_module_level=True)

_MINUTES = re.compile(r"'(\d+)m'")


def _runner_targets() -> list[str]:
    body = _RUNNER.read_text(encoding="utf-8")
    block = body.split("readonly TARGETS=(", 1)[1].split(")", 1)[0]
    return [line.strip() for line in block.splitlines() if line.strip()]


def _declared_fuzz_targets() -> list[str]:
    source = _FUZZ_TESTS.read_text(encoding="utf-8")
    return re.findall(r"^func (Fuzz\w+)\(", source, flags=re.MULTILINE)


def _job() -> dict[str, Any]:
    workflow: dict[str, Any] = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    job: dict[str, Any] = workflow["jobs"]["fuzz"]
    return job


def _scheduled_fuzztime_minutes() -> int:
    steps: list[dict[str, Any]] = _job()["steps"]
    step = next(s for s in steps if "FUZZTIME" in str(s.get("env", "")))
    # The expression is `pull_request && '2m' || inputs.fuzztime || '12m'`; the
    # last literal is what a scheduled or push run actually uses.
    return int(_MINUTES.findall(str(step["env"]["FUZZTIME"]))[-1])


def test_runner_targets_match_the_fuzz_test_file() -> None:
    assert _runner_targets() == _declared_fuzz_targets()


def test_one_retry_still_fits_inside_the_job_timeout() -> None:
    targets = len(_runner_targets())
    fuzztime = _scheduled_fuzztime_minutes()
    cap: int = _job()["timeout-minutes"]
    worst_case = (targets + 1) * fuzztime  # every target once, plus one retry
    assert worst_case <= cap * 0.75, (
        f"{targets} targets x {fuzztime}m + one retry = {worst_case}m, "
        f"which leaves too little of the {cap}m job budget for setup and the go build"
    )
