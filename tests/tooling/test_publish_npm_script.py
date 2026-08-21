# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""ci/publish-npm.sh must suppress only a positively confirmed existing version."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests.tooling.test_init_go_workspace import _bash_executable, _bash_path

pytestmark = pytest.mark.tooling

_SCRIPT = Path(__file__).resolve().parents[2] / "ci" / "publish-npm.sh"


def _package(tmp_path: Path, *, name: str = "@scope/pkg", version: str = "1.2.3") -> Path:
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    (package_dir / "package.json").write_text(json.dumps({"name": name, "version": version}))
    return package_dir


def _stub_npm(
    tmp_path: Path,
    *,
    view_before: str = "",
    view_after: str = "1.2.3",
    publish_exit: int = 0,
) -> Path:
    """Write a fake `npm` whose `view` answer changes after `publish` runs.

    A single fixed answer cannot express the real sequence: before publishing the
    registry does not have the version, and afterwards it does. Keying off a
    marker file lets one stub drive both the pre-check and the postcondition.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "npm"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$@" >> "{tmp_path}/npm-calls.txt"\n'
        'case "$1" in\n'
        "  view)\n"
        f'    if [[ -f "{tmp_path}/published" ]]; then\n'
        f'      [[ -n "{view_after}" ]] || exit 1\n'
        f'      printf "%s" "{view_after}"; exit 0\n'
        "    fi\n"
        f'    [[ -n "{view_before}" ]] || exit 1\n'
        f'    printf "%s" "{view_before}"; exit 0 ;;\n'
        "  publish)\n"
        f'    [[ {publish_exit} -eq 0 ]] && touch "{tmp_path}/published"\n'
        f"    exit {publish_exit} ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n"
    )
    stub.chmod(0o755)
    return bin_dir


def _run(tmp_path: Path, package_dir: Path, bin_dir: Path) -> subprocess.CompletedProcess[str]:
    # Invoked through bash rather than executed directly: Windows cannot exec a
    # .sh file (WinError 193), but the runners ship Git Bash, so the script's
    # logic stays covered on every OS in the matrix. Same helpers as
    # test_run_uv_sync_with_retry.py.
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["PACKAGE_DIR"] = _bash_path(package_dir)
    return subprocess.run(  # nosec B603 — fixed argv, no shell
        [_bash_executable(), _bash_path(_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _calls(tmp_path: Path) -> str:
    path = tmp_path / "npm-calls.txt"
    return path.read_text() if path.exists() else ""


def test_existing_version_is_a_successful_no_op(tmp_path: Path) -> None:
    package_dir = _package(tmp_path)
    bin_dir = _stub_npm(tmp_path, view_before="1.2.3")
    result = _run(tmp_path, package_dir, bin_dir)
    assert result.returncode == 0, result.stderr
    assert "already-published" in result.stdout
    assert "publish" not in _calls(tmp_path)


def test_absent_version_is_published_and_verified(tmp_path: Path) -> None:
    package_dir = _package(tmp_path)
    bin_dir = _stub_npm(tmp_path, view_before="", view_after="1.2.3")
    result = _run(tmp_path, package_dir, bin_dir)
    assert result.returncode == 0, result.stderr
    assert "published @scope/pkg@1.2.3" in result.stdout
    assert "publish" in _calls(tmp_path)


def test_publish_failure_is_fatal(tmp_path: Path) -> None:
    package_dir = _package(tmp_path)
    bin_dir = _stub_npm(tmp_path, view_before="", publish_exit=1)
    assert _run(tmp_path, package_dir, bin_dir).returncode != 0


def test_publish_that_does_not_land_is_fatal(tmp_path: Path) -> None:
    """A publish exiting 0 without the version appearing is not a release."""
    package_dir = _package(tmp_path)
    bin_dir = _stub_npm(tmp_path, view_before="", view_after="")
    result = _run(tmp_path, package_dir, bin_dir)
    assert result.returncode != 0
    assert "not present after publish" in result.stderr


def test_ambiguous_registry_answer_is_fatal(tmp_path: Path) -> None:
    """A hit reporting a different version is not evidence of anything."""
    package_dir = _package(tmp_path)
    bin_dir = _stub_npm(tmp_path, view_before="9.9.9")
    result = _run(tmp_path, package_dir, bin_dir)
    assert result.returncode != 0
    assert "refusing to guess" in result.stderr
    assert "publish" not in _calls(tmp_path)


def test_missing_package_json_is_fatal(tmp_path: Path) -> None:
    bin_dir = _stub_npm(tmp_path)
    result = _run(tmp_path, tmp_path / "nope", bin_dir)
    assert result.returncode != 0
    assert "no package.json" in result.stderr
