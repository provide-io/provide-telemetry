# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Regression tests for ci/init-go-workspace.sh."""

from __future__ import annotations

import os
import subprocess  # nosec
from pathlib import Path

import pytest

pytestmark = pytest.mark.tooling

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "ci" / "init-go-workspace.sh"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_go_module(path: Path, module_path: str) -> None:
    _write(path / "go.mod", f"module {module_path}\n\ngo 1.26.0\n")


def _run_workspace_script(repo_root: Path, tmp_path: Path) -> str:
    shim_dir = tmp_path / "shim-bin"
    shim_dir.mkdir()
    blocked_go = shim_dir / "go"
    blocked_go.write_text("#!/usr/bin/env bash\nexit 97\n", encoding="utf-8")
    blocked_go.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{shim_dir}{os.pathsep}{env.get('PATH', '')}"
    result = subprocess.run(
        ["bash", str(SCRIPT), str(repo_root), str(tmp_path / "workspace")],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    workfile = Path(result.stdout.strip())
    assert workfile.exists()
    return workfile.read_text(encoding="utf-8")


def test_workspace_script_supports_legacy_multi_module_layout(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _write_go_module(repo_root / "go", "github.com/provide-io/provide-telemetry/go")
    _write_go_module(repo_root / "go" / "internal", "github.com/provide-io/provide-telemetry/go/internal")
    _write_go_module(repo_root / "go" / "logger", "github.com/provide-io/provide-telemetry/go/logger")
    _write_go_module(repo_root / "go" / "tracer", "github.com/provide-io/provide-telemetry/go/tracer")
    _write_go_module(
        repo_root / "go" / "cmd" / "e2e_cross_language_client",
        "github.com/provide-io/provide-telemetry/go/cmd/e2e_cross_language_client",
    )

    workfile = _run_workspace_script(repo_root, tmp_path)

    assert str(repo_root / "go") in workfile
    assert str(repo_root / "go" / "internal") in workfile
    assert str(repo_root / "go" / "logger") in workfile
    assert str(repo_root / "go" / "tracer") in workfile
    assert str(repo_root / "go" / "cmd" / "e2e_cross_language_client") in workfile
    assert str(repo_root / "go" / "otel") not in workfile


def test_workspace_script_supports_optional_otel_layout(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _write_go_module(repo_root / "go", "github.com/provide-io/provide-telemetry/go")
    _write_go_module(repo_root / "go" / "otel", "github.com/provide-io/provide-telemetry/go/otel")

    workfile = _run_workspace_script(repo_root, tmp_path)

    assert str(repo_root / "go") in workfile
    assert str(repo_root / "go" / "otel") in workfile
    assert str(repo_root / "go" / "internal") not in workfile
    assert str(repo_root / "go" / "logger") not in workfile
    assert str(repo_root / "go" / "tracer") not in workfile
