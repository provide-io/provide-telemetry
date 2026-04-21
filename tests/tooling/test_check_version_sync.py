# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for scripts/check_version_sync.py."""

from __future__ import annotations

import importlib.util
import subprocess  # nosec
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.tooling

_REPO_ROOT = Path(__file__).parent.parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "check_version_sync.py"
_GO_INTERNAL_MODULE = "github.com/provide-io/provide-telemetry/go/internal"
_GO_LOGGER_MODULE = "github.com/provide-io/provide-telemetry/go/logger"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("check_version_sync_test_module", str(_SCRIPT))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_minimal_repo(
    tmp_path: Path,
    *,
    logger_internal_version: str = "0.4.0",
    tracer_logger_version: str = "0.4.0",
) -> Path:
    _write(tmp_path / "VERSION", "0.4.0\n")
    _write(tmp_path / "go" / "VERSION", "0.4.0\n")
    _write(tmp_path / "go" / "internal" / "VERSION", "0.4.0\n")
    _write(tmp_path / "go" / "logger" / "VERSION", "0.4.0\n")
    _write(tmp_path / "go" / "tracer" / "VERSION", "0.4.0\n")
    _write(
        tmp_path / "go" / "logger" / "go.mod",
        "\n".join(
            [
                f"module {_GO_LOGGER_MODULE}",
                "",
                "go 1.25.0",
                "",
                f"require {_GO_INTERNAL_MODULE} v{logger_internal_version}",
                "",
            ]
        ),
    )
    _write(
        tmp_path / "go" / "tracer" / "go.mod",
        "\n".join(
            [
                "module github.com/provide-io/provide-telemetry/go/tracer",
                "",
                "go 1.25.0",
                "",
                "require (",
                f"\t{_GO_LOGGER_MODULE} v{tracer_logger_version}",
                "\tgo.opentelemetry.io/otel/trace v1.43.0",
                ")",
                "",
            ]
        ),
    )
    return tmp_path


def test_version_sync_passes() -> None:
    """All language packages should share the same major.minor as VERSION."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, f"Version sync failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"


def test_version_sync_fails_when_go_logger_dep_mismatches_internal_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo_root = _make_minimal_repo(tmp_path, logger_internal_version="0.3.0")
    module = _load_script_module()
    monkeypatch.setattr(module, "_REPO_ROOT", repo_root)

    assert module.main() == 1

    output = capsys.readouterr().out
    assert "go/logger dependency" in output
    assert "v0.3.0" in output
    assert "v0.4.0" in output


def test_version_sync_fails_when_go_tracer_dep_mismatches_logger_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo_root = _make_minimal_repo(tmp_path, tracer_logger_version="0.2.6")
    module = _load_script_module()
    monkeypatch.setattr(module, "_REPO_ROOT", repo_root)

    assert module.main() == 1

    output = capsys.readouterr().out
    assert "go/tracer dependency" in output
    assert "v0.2.6" in output
    assert "v0.4.0" in output
