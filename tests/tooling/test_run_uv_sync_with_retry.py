# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Regression tests for ci/run_uv_sync_with_retry.sh."""

from __future__ import annotations

import os
import subprocess  # nosec
from pathlib import Path

import pytest

from tests.tooling.test_init_go_workspace import _bash_executable, _bash_path

pytestmark = pytest.mark.tooling

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "ci" / "run_uv_sync_with_retry.sh"


def _write_uv_shim(path: Path, *, fail_count: int) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    counter = path / "uv-count"
    counter.write_text("0", encoding="utf-8")
    shim = path / "uv"
    shim.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
count="$(cat "{counter}")"
count="$((count + 1))"
printf '%s' "${{count}}" > "{counter}"
if [ "${{count}}" -le {fail_count} ]; then
  exit 9
fi
exit 0
""",
        encoding="utf-8",
    )
    shim.chmod(0o755)
    return counter


def test_retry_script_retries_then_succeeds(tmp_path: Path) -> None:
    counter = _write_uv_shim(tmp_path / "shim-bin", fail_count=2)
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path / 'shim-bin'}{os.pathsep}{env.get('PATH', '')}"
    env["UV_SYNC_MAX_ATTEMPTS"] = "4"
    env["UV_SYNC_RETRY_DELAY_SECONDS"] = "0"

    result = subprocess.run(
        [_bash_executable(), _bash_path(SCRIPT), "--group", "dev"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert counter.read_text(encoding="utf-8") == "3"


def test_retry_script_exits_after_max_attempts(tmp_path: Path) -> None:
    _write_uv_shim(tmp_path / "shim-bin", fail_count=10)
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path / 'shim-bin'}{os.pathsep}{env.get('PATH', '')}"
    env["UV_SYNC_MAX_ATTEMPTS"] = "2"
    env["UV_SYNC_RETRY_DELAY_SECONDS"] = "0"

    result = subprocess.run(
        [_bash_executable(), _bash_path(SCRIPT), "--group", "dev"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 9
    assert "uv sync failed after 2 attempts" in result.stderr
