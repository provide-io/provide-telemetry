# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for the accepted-gaps schema and glob-based discovery in
spec/check_fixture_coverage.py (renamed from fixture_coverage_allowlist.yaml)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.tooling

_REPO_ROOT = Path(__file__).parent.parent.parent
_SCRIPT = _REPO_ROOT / "spec" / "check_fixture_coverage.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_fixture_coverage_gaps_test", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# expires_on schema
# ---------------------------------------------------------------------------


def test_entry_without_expires_on_is_rejected(tmp_path: Path) -> None:
    """An accepted-gap entry missing expires_on should produce a schema error."""
    module = _load_module()
    gaps = tmp_path / "accepted_gaps.yaml"
    gaps.write_text(
        "accepted_gaps:\n  - lang: rust\n    category: config_headers\n    reason: pending\n    owner: provide-io\n",
        encoding="utf-8",
    )
    pairs, entries, errors = module._load_accepted_gaps(gaps)
    assert pairs == set()
    assert entries == []
    assert any("missing required 'expires_on'" in e for e in errors), errors


def test_entry_with_malformed_expires_on_is_rejected(tmp_path: Path) -> None:
    """A non-ISO date value for expires_on should produce a schema error."""
    module = _load_module()
    gaps = tmp_path / "accepted_gaps.yaml"
    gaps.write_text(
        "accepted_gaps:\n"
        "  - lang: rust\n"
        "    category: config_headers\n"
        "    reason: pending\n"
        "    owner: provide-io\n"
        "    expires_on: 'not-a-date'\n",
        encoding="utf-8",
    )
    pairs, entries, errors = module._load_accepted_gaps(gaps)
    assert pairs == set()
    assert entries == []
    assert any("YYYY-MM-DD" in e for e in errors), errors


def test_future_dated_entry_passes(tmp_path: Path) -> None:
    """An entry with a future expires_on should be accepted without warnings."""
    module = _load_module()
    gaps = tmp_path / "accepted_gaps.yaml"
    gaps.write_text(
        "accepted_gaps:\n"
        "  - lang: rust\n"
        "    category: config_headers\n"
        "    reason: pending\n"
        "    owner: provide-io\n"
        "    expires_on: 2099-12-31\n",
        encoding="utf-8",
    )
    pairs, entries, errors = module._load_accepted_gaps(gaps)
    assert errors == []
    assert ("rust", "config_headers") in pairs
    # expiry check on future dates yields exit 0
    assert module._report_expiry(entries, strict=True) == 0


def test_expired_entry_warns_by_default(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An expired entry prints a warning on stderr and returns 0 in non-strict mode."""
    module = _load_module()
    entries: list[dict[str, object]] = [
        {
            "lang": "rust",
            "category": "config_headers",
            "reason": "pending",
            "owner": "provide-io",
            "expires_on": "2000-01-01",
        }
    ]
    rc = module._report_expiry(entries, strict=False)
    assert rc == 0
    captured = capsys.readouterr()
    assert "WARNING" in captured.err
    assert "rust:config_headers" in captured.err


def test_expired_entry_errors_in_strict_mode(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--strict upgrades expired-entry warnings to errors with exit 1."""
    module = _load_module()
    entries: list[dict[str, object]] = [
        {
            "lang": "rust",
            "category": "config_headers",
            "reason": "pending",
            "owner": "provide-io",
            "expires_on": "2000-01-01",
        }
    ]
    rc = module._report_expiry(entries, strict=True)
    assert rc == 1
    captured = capsys.readouterr()
    assert "EXPIRED" in captured.err


def test_repo_accepted_gaps_file_exists_under_new_name() -> None:
    """Renaming must point the checker at spec/fixture_coverage_accepted_gaps.yaml."""
    module = _load_module()
    assert module._ACCEPTED_GAPS_PATH.name == "fixture_coverage_accepted_gaps.yaml"
    assert module._ACCEPTED_GAPS_PATH.exists(), (
        f"Expected file at {module._ACCEPTED_GAPS_PATH} — did the rename succeed?"
    )
    # The previous filename must no longer exist in the repo.
    old_path = _REPO_ROOT / "spec" / "fixture_coverage_allowlist.yaml"
    assert not old_path.exists(), "Previous allowlist filename still present — rename incomplete"


# ---------------------------------------------------------------------------
# Glob-based discovery
# ---------------------------------------------------------------------------


def test_glob_discovery_finds_new_parity_file(tmp_path: Path) -> None:
    """A newly-added parity_*_test.go file should be discovered by the glob."""
    module = _load_module()

    fake_repo = tmp_path / "repo"
    (fake_repo / "go").mkdir(parents=True)
    (fake_repo / "tests" / "parity").mkdir(parents=True)
    (fake_repo / "typescript" / "tests").mkdir(parents=True)
    (fake_repo / "rust" / "tests").mkdir(parents=True)

    discoverable = fake_repo / "go" / "parity_brandnew_test.go"
    discoverable.write_text("// sentinel: parity_brandnew_marker\n", encoding="utf-8")

    # Populate minimal siblings so other languages don't trip the empty-language guard
    (fake_repo / "tests" / "parity" / "test_parity_dummy.py").write_text("# ok\n", encoding="utf-8")
    (fake_repo / "typescript" / "tests" / "parity.test.ts").write_text("// ok\n", encoding="utf-8")
    (fake_repo / "rust" / "tests" / "parity_test.rs").write_text("// ok\n", encoding="utf-8")

    discovered = module._discover_language_files(
        fake_repo, module._LANGUAGE_GLOBS, {"python": [], "typescript": [], "go": [], "rust": []}
    )

    assert discoverable.resolve() in discovered["go"], f"parity_brandnew_test.go not discovered: {discovered['go']}"
    assert all(len(paths) >= 1 for paths in discovered.values()), discovered


def test_discover_rejects_symlinks(tmp_path: Path) -> None:
    """Symlinks should be filtered out of discovered parity test files."""
    module = _load_module()

    fake_repo = tmp_path / "repo"
    (fake_repo / "go").mkdir(parents=True)

    outside = tmp_path / "outside_parity_test.go"
    outside.write_text("// escaping content\n", encoding="utf-8")
    link = fake_repo / "go" / "parity_symlink_test.go"
    link.symlink_to(outside)

    real = fake_repo / "go" / "parity_real_test.go"
    real.write_text("// real\n", encoding="utf-8")

    discovered = module._discover_language_files(fake_repo, {"go": ["go/parity_*_test.go"]}, {"go": []})
    assert real.resolve() in discovered["go"]
    assert link.resolve() not in discovered["go"]
    # And we should NOT have followed the symlink to pull in the outside file
    assert outside.resolve() not in discovered["go"]


def test_empty_language_discovery_fails_loudly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """If no parity files are discovered for a language, main() must return nonzero."""
    module = _load_module()

    fake_repo = tmp_path / "repo"
    (fake_repo / "spec").mkdir(parents=True)
    (fake_repo / "spec" / "behavioral_fixtures.yaml").write_text("sampling:\n  description: x\n", encoding="utf-8")

    monkeypatch.setattr(module, "_REPO_ROOT", fake_repo)
    monkeypatch.setattr(module, "_ACCEPTED_GAPS_PATH", fake_repo / "spec" / "accepted.yaml")

    rc = module.main([])
    assert rc != 0
    captured = capsys.readouterr()
    assert "no parity test files discovered" in captured.err
