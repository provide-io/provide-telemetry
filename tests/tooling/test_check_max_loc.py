# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.tooling
_SCRIPT_PATH = Path("scripts/check_max_loc.py")
if not _SCRIPT_PATH.exists():
    pytest.skip("scripts/check_max_loc.py not available in this test runtime", allow_module_level=True)


def _load_script_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_max_loc", _SCRIPT_PATH)
    if spec is None or spec.loader is None:
        msg = "unable to load check_max_loc script module"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_MODULE = _load_script_module()
find_loc_offenders = _MODULE.find_loc_offenders
DEFAULT_EXTENSIONS = _MODULE.DEFAULT_EXTENSIONS


def test_find_loc_offenders_flags_files_over_limit(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    ok_file = src / "ok.py"
    bad_file = src / "bad.py"
    ok_file.write_text("x = 1\n" * 10, encoding="utf-8")
    bad_file.write_text("x = 1\n" * 12, encoding="utf-8")

    offenders, grandfathered = find_loc_offenders(
        [src], max_lines=10, extensions=DEFAULT_EXTENSIONS, allowlist={}, repo_root=tmp_path
    )
    assert offenders == [(bad_file, 12)]
    assert grandfathered == []


def test_find_loc_offenders_skips_excluded_dirs(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    excluded = root / "mutants"
    excluded.mkdir()
    (excluded / "too_long.py").write_text("x = 1\n" * 1000, encoding="utf-8")

    offenders, grandfathered = find_loc_offenders(
        [root], max_lines=10, extensions=DEFAULT_EXTENSIONS, allowlist={}, repo_root=tmp_path
    )
    assert offenders == []
    assert grandfathered == []


def test_find_loc_offenders_scans_all_polyglot_extensions(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "big.ts").write_text("// line\n" * 600, encoding="utf-8")
    (src / "big.go").write_text("// line\n" * 600, encoding="utf-8")
    (src / "big.rs").write_text("// line\n" * 600, encoding="utf-8")
    (src / "big.py").write_text("# line\n" * 600, encoding="utf-8")

    offenders, _ = find_loc_offenders(
        [src], max_lines=500, extensions=DEFAULT_EXTENSIONS, allowlist={}, repo_root=tmp_path
    )
    paths = sorted(p.name for p, _ in offenders)
    assert paths == ["big.go", "big.py", "big.rs", "big.ts"]


def test_allowlist_grandfathers_existing_violators_under_ceiling(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    grand = src / "large.go"
    grand.write_text("// line\n" * 700, encoding="utf-8")

    offenders, grandfathered = find_loc_offenders(
        [src],
        max_lines=500,
        extensions=DEFAULT_EXTENSIONS,
        allowlist={"src/large.go": 800},
        repo_root=tmp_path,
    )
    assert offenders == []
    assert grandfathered == [(grand, 700)]


def test_allowlist_does_not_let_files_grow_past_ceiling(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    grand = src / "large.go"
    grand.write_text("// line\n" * 700, encoding="utf-8")

    offenders, grandfathered = find_loc_offenders(
        [src],
        max_lines=500,
        extensions=DEFAULT_EXTENSIONS,
        allowlist={"src/large.go": 600},  # ceiling lower than current size
        repo_root=tmp_path,
    )
    assert offenders == [(grand, 700)]
    assert grandfathered == []


def test_node_modules_and_target_excluded(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "node_modules").mkdir()
    (root / "node_modules" / "huge.ts").write_text("// line\n" * 5000, encoding="utf-8")
    (root / "target").mkdir()
    (root / "target" / "huge.rs").write_text("// line\n" * 5000, encoding="utf-8")

    offenders, _ = find_loc_offenders(
        [root], max_lines=10, extensions=DEFAULT_EXTENSIONS, allowlist={}, repo_root=tmp_path
    )
    assert offenders == []


def test_filenames_without_extension_are_scanned(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "Makefile").write_text("\n".join(["x"] * 12))
    (root / "notes.txt").write_text("\n".join(["x"] * 12))
    offenders, _ = find_loc_offenders(
        [root], max_lines=10, extensions=DEFAULT_EXTENSIONS, allowlist={}, repo_root=tmp_path, filenames=("Makefile",)
    )
    assert [p.name for p, _ in offenders] == ["Makefile"]


def test_explicit_file_list_replaces_root_walk(tmp_path: Path) -> None:
    """A tracked-file list is the scan set; files outside it are not walked."""
    root = tmp_path / "repo"
    root.mkdir()
    tracked = root / "tracked.py"
    tracked.write_text("\n".join(["x"] * 12))
    (root / "untracked.py").write_text("\n".join(["x"] * 12))
    offenders, _ = find_loc_offenders(
        [root], max_lines=10, extensions=DEFAULT_EXTENSIONS, allowlist={}, repo_root=tmp_path, files=[tracked]
    )
    assert [p for p, _ in offenders] == [tracked]


def test_explicit_file_list_still_filters_by_extension_and_exclusion(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "node_modules").mkdir(parents=True)
    vendored = root / "node_modules" / "big.js"
    vendored.write_text("\n".join(["x"] * 12))
    readme = root / "README.md"
    readme.write_text("\n".join(["x"] * 12))
    offenders, _ = find_loc_offenders(
        [root], max_lines=10, extensions=DEFAULT_EXTENSIONS, allowlist={}, repo_root=tmp_path, files=[vendored, readme]
    )
    assert offenders == []


def test_git_tracked_files_lists_the_repo(tmp_path: Path) -> None:
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "a.py").write_text("print()\n")
    (repo / "b.py").write_text("print()\n")
    subprocess.run(["git", "add", "a.py"], cwd=repo, check=True)
    tracked = _MODULE.git_tracked_files(repo)
    assert tracked == [repo / "a.py"]


def test_git_tracked_files_is_none_outside_a_repo(tmp_path: Path) -> None:
    assert _MODULE.git_tracked_files(tmp_path) is None


def test_git_tracked_files_is_none_without_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _missing(*_args: object, **_kwargs: object) -> object:
        raise OSError("git not found")

    monkeypatch.setattr(_MODULE.subprocess, "run", _missing)
    assert _MODULE.git_tracked_files(tmp_path) is None


def test_default_roots_cover_every_tracked_source_file() -> None:
    """The git scan is primary, but the fallback roots must agree with it."""
    repo_root = _SCRIPT_PATH.resolve().parent.parent
    tracked = _MODULE.git_tracked_files(repo_root)
    if tracked is None:
        pytest.skip("git unavailable")
    roots = [repo_root / r for r in _MODULE.DEFAULT_ROOTS]
    walked = set(_MODULE._iter_source_files(roots, DEFAULT_EXTENSIONS, _MODULE.DEFAULT_FILENAMES))
    expected = {
        p
        for p in tracked
        if p.is_file()
        and _MODULE._is_source_file(p, DEFAULT_EXTENSIONS, _MODULE.DEFAULT_FILENAMES)
        and not _MODULE._is_excluded(p.relative_to(repo_root))
        and p.parent != repo_root  # top-level files (Makefile) have no directory root
    }
    missing = sorted(str(p.relative_to(repo_root)) for p in expected - walked)
    assert missing == []
