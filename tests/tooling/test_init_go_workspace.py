# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Regression tests for ci/init-go-workspace.sh."""

from __future__ import annotations

import ntpath
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


def _write_go_module(path: Path, module_path: str, go_version: str = "1.26.0") -> None:
    _write(path / "go.mod", f"module {module_path}\n\ngo {go_version}\n")


def _bash_path(path: Path) -> str:
    raw = str(path)
    drive, tail = ntpath.splitdrive(raw)
    if not drive:
        return raw
    normalized_tail = tail.replace("\\", "/")
    return f"/{drive.rstrip(':').lower()}{normalized_tail}"


def _run_workspace_script(
    repo_root: Path,
    tmp_path: Path,
    extra_shims: dict[str, str] | None = None,
) -> tuple[str, str]:
    shim_dir = tmp_path / "shim-bin"
    shim_dir.mkdir()
    blocked_go = shim_dir / "go"
    blocked_go.write_text("#!/usr/bin/env bash\nexit 97\n", encoding="utf-8")
    blocked_go.chmod(0o755)
    for name, content in (extra_shims or {}).items():
        shim = shim_dir / name
        shim.write_text(content, encoding="utf-8")
        shim.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{shim_dir}{os.pathsep}{env.get('PATH', '')}"
    workspace_dir = tmp_path / "workspace"
    result = subprocess.run(
        ["bash", _bash_path(SCRIPT), _bash_path(repo_root), _bash_path(workspace_dir)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    workfile = workspace_dir / "go.work"
    assert workfile.exists()
    return result.stdout.strip(), workfile.read_text(encoding="utf-8")


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

    _, workfile = _run_workspace_script(repo_root, tmp_path)

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

    _, workfile = _run_workspace_script(repo_root, tmp_path)

    assert str(repo_root / "go") in workfile
    assert str(repo_root / "go" / "otel") in workfile
    assert str(repo_root / "go" / "internal") not in workfile
    assert str(repo_root / "go" / "logger") not in workfile
    assert str(repo_root / "go" / "tracer") not in workfile


def test_workspace_script_uses_highest_module_go_version(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _write_go_module(repo_root / "go", "github.com/provide-io/provide-telemetry/go", go_version="1.26.0")
    _write_go_module(
        repo_root / "go" / "cmd" / "e2e_cross_language_client",
        "github.com/provide-io/provide-telemetry/go/cmd/e2e_cross_language_client",
        go_version="1.26.1",
    )

    _, workfile = _run_workspace_script(repo_root, tmp_path)

    assert "go 1.26.1" in workfile


def test_workspace_script_uses_windows_paths_when_cygpath_is_available(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _write_go_module(repo_root / "go", "github.com/provide-io/provide-telemetry/go")
    _write_go_module(repo_root / "go" / "otel", "github.com/provide-io/provide-telemetry/go/otel")

    cygpath_shim = """#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" != "-am" ]; then
  exit 64
fi
path="${2:?path required}"
path="${path#/}"
printf 'C:/%s\\n' "${path}"
"""

    stdout_path, workfile = _run_workspace_script(
        repo_root,
        tmp_path,
        extra_shims={"cygpath": cygpath_shim},
    )

    expected_root = f"C:/{repo_root.as_posix().lstrip('/')}"
    assert stdout_path == f"C:/{(tmp_path / 'workspace').as_posix().lstrip('/')}/go.work"
    assert f"\t{expected_root}/go" in workfile
    assert f"\t{expected_root}/go/otel" in workfile


def test_bash_path_converts_windows_paths() -> None:
    assert _bash_path(Path("C:/Users/runneradmin/work/repo")) == "/c/Users/runneradmin/work/repo"
