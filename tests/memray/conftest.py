# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Fixtures for memray memory profiling tests."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from pathlib import Path

import pytest


def _find_project_root() -> Path:
    """Walk up from this file until we find VERSION, anchoring to the real project root.

    Using VERSION (not pyproject.toml) because mutmut copies pyproject.toml into its
    mutants/ sandbox, making it an unreliable anchor.
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / "VERSION").exists():
            return parent
    raise FileNotFoundError("Could not locate project root (no VERSION file found)")


_PROJECT_ROOT = _find_project_root()

_baseline_updates: dict[str, int] = {}

_BASELINE_PATH = Path(__file__).parent / "baselines.json"


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Absolute path to the project root (works inside mutmut's mutants/ sandbox)."""
    return _PROJECT_ROOT


@pytest.fixture
def memray_output_dir() -> Path:
    """Return path to memray output directory, creating it if needed."""
    output_dir = _PROJECT_ROOT / "memray-output"
    output_dir.mkdir(exist_ok=True)
    return output_dir


@pytest.fixture
def memray_baseline() -> dict[str, int]:
    """Load baseline allocation counts from baselines.json, or return empty dict if not found."""
    if _BASELINE_PATH.exists():
        with _BASELINE_PATH.open(encoding="utf-8") as f:
            return json.load(f)  # type: ignore[no-any-return]
    return {}


@pytest.fixture
def assert_allocation_within_threshold() -> Callable[[int | None, int, str, float], None]:
    """Return a function that asserts allocation is within tolerance of baseline."""

    def _check(baseline: int | None, current: int, name: str, tolerance: float = 0.15) -> None:
        if baseline is None:
            key = f"{name.lower().replace(' ', '_')}_total_allocations"
            _baseline_updates[key] = current
            return
        max_allowed = baseline * (1 + tolerance)
        if current > max_allowed:
            percent_over = ((current - baseline) / baseline) * 100
            msg = (
                f"{name} allocation {current} exceeds baseline {baseline} by {percent_over:.1f}% "
                f"(tolerance: {tolerance * 100:.0f}%)"
            )
            raise AssertionError(msg)

    return _check


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Save baseline updates to baselines.json if MEMRAY_UPDATE_BASELINE is set."""
    _ = session, exitstatus  # required by pytest hook signature
    if not os.getenv("MEMRAY_UPDATE_BASELINE") or not _baseline_updates:
        return
    existing: dict[str, int] = {}
    if _BASELINE_PATH.exists():
        with _BASELINE_PATH.open(encoding="utf-8") as f:
            existing = json.load(f)
    existing.update(_baseline_updates)
    with _BASELINE_PATH.open("w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, sort_keys=True)
        f.write("\n")


_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


@pytest.fixture(scope="session")
def parse_total_allocations() -> Callable[[str], int]:
    r"""Read "Total allocations" out of ``memray stats`` output.

    memray >= 1.15 emits the label in ANSI bold and puts the count on the *next*
    line, so the previous ``r"Total allocations:\s+([\d,]+)"`` could not match:
    ``\s`` does not cross the reset sequence that sits between them. Older
    memray printed both inline, which is why CI parsed this fine while every
    local run failed with "Could not parse allocations" — the whole memray suite
    was unrunnable on a current install, so a regression could only ever be
    caught after merging to main.
    """

    def _parse(stdout: str) -> int:
        plain = _ANSI_ESCAPE.sub("", stdout)
        match = re.search(r"Total allocations:\s*([\d,]+)", plain)
        assert match, f"Could not parse allocations from memray stats:\n{stdout}"
        return int(match.group(1).replace(",", ""))

    return _parse
