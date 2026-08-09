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
    # csharp joined REQUIRED_MODULES with the Provide.Telemetry library, so a
    # fake repo without it fails the required-module check rather than
    # exercising the optional-module path these tests are about.
    _write(tmp_path / "csharp" / "VERSION", "0.4.0\n")
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


class TestCSharpArtifacts:
    """The package split made C# two shippable artifacts, not one.

    ``csharp/VERSION`` short-circuits the C# reader before any project file is
    opened, so the integration package's version was never compared to
    anything. And nothing looked at assembly identity at all: both projects
    shipped ``<Version>0.7.0</Version>`` beside
    ``<AssemblyVersion>0.6.0.0</AssemblyVersion>``, so a 0.7.0 NuGet package
    loaded and reported itself as 0.6.0.0.
    """

    def test_both_csharp_packages_are_checked(self) -> None:
        from scripts.check_version_sync import OPTIONAL_MODULES, REQUIRED_MODULES

        assert "csharp" in REQUIRED_MODULES
        # Optional for the same reason go/otel is: the integration package is a
        # separate artifact and a core-only checkout legitimately lacks it.
        assert "csharp/otel" in OPTIONAL_MODULES

    def test_assembly_identity_matches_the_package_version(self) -> None:
        from scripts.check_version_sync import csharp_assembly_identity_errors

        assert csharp_assembly_identity_errors() == []

    def test_a_drifted_assembly_version_is_reported(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Guard against the check silently passing because it found no files:
        # point it at a tree that definitely has the drift and require a report.
        import scripts.check_version_sync as mod

        project = tmp_path / "csharp" / "src" / "Provide.Telemetry"
        project.mkdir(parents=True)
        (project / "Provide.Telemetry.csproj").write_text(
            "<Project><PropertyGroup>"
            "<Version>0.9.0</Version>"
            "<AssemblyVersion>0.6.0.0</AssemblyVersion>"
            "<FileVersion>0.9.0.0</FileVersion>"
            "</PropertyGroup></Project>",
            encoding="utf-8",
        )
        monkeypatch.setattr(mod, "_REPO_ROOT", tmp_path)
        problems = mod.csharp_assembly_identity_errors()
        assert len(problems) == 1
        assert "<AssemblyVersion> is 0.6.0.0, expected 0.9.0.0" in problems[0]
