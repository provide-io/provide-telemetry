# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Regression tests for code review batch #9 (tooling environment-shape bugs).

These pin specific failure modes in CI tooling, not in library code:

1. ``scripts/check_max_loc.py`` must scan the repo regardless of the
   caller's cwd — invoking from outside the repo previously silently
   passed because relative roots resolved against cwd, not repo_root.
2. ``spec/_runtime_probe._shared()`` must reuse an already-loaded
   ``parity_probe_support`` module when it was loaded under an alias
   (e.g. via ``importlib.util.spec_from_file_location``) — re-importing
   by canonical name previously created a duplicate module instance,
   silently breaking monkeypatches and shared state in tooling.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.mark.tooling
def test_check_max_loc_scans_repo_when_invoked_from_outside_cwd(tmp_path: Path) -> None:
    """LOC gate must use repo_root for relative roots, not cwd.

    A low ``--max-lines`` threshold guarantees offenders exist anywhere the
    repo is actually scanned. If the script silently uses cwd-relative
    roots, none exist under tmp_path and the gate trivially passes.
    """
    script = REPO_ROOT / "scripts" / "check_max_loc.py"
    proc = subprocess.run(
        [sys.executable, str(script), "--max-lines", "50"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1, (
        "check_max_loc.py must fail (returncode 1) when invoked from outside the repo "
        "with a low threshold — silent pass means roots resolved against cwd.\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    assert "LOC check failed" in proc.stdout, (
        f"Expected failure output mentioning 'LOC check failed', got stdout:\n{proc.stdout}"
    )


@pytest.mark.tooling
def test_runtime_probe_shared_resolves_aliased_parity_module() -> None:
    """``_shared()`` must return symbols from the already-loaded
    ``parity_probe_support`` module even when it was loaded under an alias.

    A re-import by canonical name would create a separate module instance,
    losing any monkeypatches applied to the alias.
    """
    spec_dir = REPO_ROOT / "spec"
    pps_path = spec_dir / "parity_probe_support.py"

    spec = importlib.util.spec_from_file_location("aliased_pps_for_test", str(pps_path))
    assert spec is not None and spec.loader is not None
    aliased = importlib.util.module_from_spec(spec)
    sys.modules["aliased_pps_for_test"] = aliased
    spec.loader.exec_module(aliased)

    sentinel = frozenset({"sentinel_for_regression_9"})
    aliased._OTEL_REQUIRED_CASE_IDS = sentinel  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]

    inserted_spec = False
    try:
        if str(spec_dir) not in sys.path:
            sys.path.insert(0, str(spec_dir))
            inserted_spec = True
        import _runtime_probe  # type: ignore[import-not-found]

        shared = _runtime_probe._shared()
        # Tuple layout: (ProbeRunner, _OTEL_REQUIRED_CASE_IDS, ...) — index 1.
        assert shared[1] is sentinel, (
            "_shared() returned a different _OTEL_REQUIRED_CASE_IDS than the aliased "
            "parity_probe_support — likely re-imported by canonical name and created "
            "a duplicate module instance."
        )
    finally:
        if inserted_spec:
            sys.path.remove(str(spec_dir))
        sys.modules.pop("aliased_pps_for_test", None)
