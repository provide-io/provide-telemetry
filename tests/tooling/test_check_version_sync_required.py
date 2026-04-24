# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for required-vs-optional module handling in check_version_sync.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.tooling

_REPO_ROOT = Path(__file__).parent.parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "check_version_sync.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_version_sync_required_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_repo_without_pyproject(tmp_path: Path) -> Path:
    """Build a fake repo that has VERSION + other languages but NO pyproject.toml."""
    _write(tmp_path / "VERSION", "0.4.0\n")
    # typescript package
    _write(
        tmp_path / "typescript" / "package.json",
        '{"name": "x", "version": "0.4.0"}\n',
    )
    # go + rust minimal
    _write(tmp_path / "go" / "VERSION", "0.4.0\n")
    _write(tmp_path / "rust" / "Cargo.toml", 'version = "0.4.0"\n')
    return tmp_path


def test_missing_pyproject_is_required_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When pyproject.toml is missing, main() must exit nonzero and complain on stderr."""
    repo_root = _make_repo_without_pyproject(tmp_path)
    module = _load()
    monkeypatch.setattr(module, "_REPO_ROOT", repo_root)

    rc = module.main([])
    assert rc != 0
    err = capsys.readouterr().err
    assert "python" in err
    assert "MISSING" in err or "required" in err


def test_missing_optional_modules_do_not_fail_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Optional modules absent from the repo must NOT cause failure in default mode."""
    repo_root = _make_repo_without_pyproject(tmp_path)
    # Add pyproject so required set is satisfied
    _write(
        repo_root / "pyproject.toml",
        '[project]\nname="x"\nversion = "0.4.0"\n',
    )
    module = _load()
    monkeypatch.setattr(module, "_REPO_ROOT", repo_root)

    rc = module.main([])
    assert rc == 0, capsys.readouterr()


def test_missing_optional_modules_fail_under_strict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--strict elevates missing-optional warnings to errors."""
    repo_root = _make_repo_without_pyproject(tmp_path)
    _write(
        repo_root / "pyproject.toml",
        '[project]\nname="x"\nversion = "0.4.0"\n',
    )
    module = _load()
    monkeypatch.setattr(module, "_REPO_ROOT", repo_root)

    rc = module.main(["--strict"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "strict" in err or "MISSING" in err


def test_required_and_optional_modules_categorized() -> None:
    """Sanity-check: the top-level required/optional constants are declared."""
    module = _load()
    assert set(module.REQUIRED_MODULES) >= {"python", "typescript/package", "go", "rust"}
    assert "go/internal" in module.OPTIONAL_MODULES
    assert "typescript/lockfile" in module.OPTIONAL_MODULES
