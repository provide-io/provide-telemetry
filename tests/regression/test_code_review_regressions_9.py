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
import subprocess  # nosec
import sys
import types
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
    """``_shared()`` must return symbols from an already-loaded aliased
    ``parity_probe_support`` module when no canonical copy is loaded.

    Resolution order in ``_shared()`` is: canonical-by-name → aliased-by-path
    → fresh canonical import. This test exercises the middle branch by
    temporarily removing the canonical entry from ``sys.modules`` so the
    aliased copy (loaded via ``importlib.util``) is the only candidate left.
    Without the path-scan fallback, ``_shared()`` would fresh-import a
    second canonical instance and lose the alias's monkeypatches entirely.
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

    # Hide ALL existing parity_probe_support copies (canonical + any
    # aliases that other tests loaded via importlib.util) so the alias
    # under test is the only candidate matching the file path scan.
    # Restored in finally so we don't leak across tests.
    target_filename = "parity_probe_support.py"
    hidden: dict[str, types.ModuleType] = {}
    for mod_name in list(sys.modules.keys()):
        mod = sys.modules.get(mod_name)
        if mod is None or mod is aliased:
            continue
        mod_file = getattr(mod, "__file__", None)
        if mod_file and mod_file.endswith(target_filename):
            popped = sys.modules.pop(mod_name)
            if popped is not None:
                hidden[mod_name] = popped

    inserted_spec = False
    try:
        if str(spec_dir) not in sys.path:
            sys.path.insert(0, str(spec_dir))
            inserted_spec = True
        import _runtime_probe  # type: ignore[import-not-found]

        shared = _runtime_probe._shared()
        assert shared.OTEL_REQUIRED_CASE_IDS is sentinel, (
            "_shared() returned a different OTEL_REQUIRED_CASE_IDS than the aliased "
            "parity_probe_support — likely re-imported by canonical name and created "
            "a duplicate module instance."
        )
    finally:
        if inserted_spec:
            sys.path.remove(str(spec_dir))
        sys.modules.pop("aliased_pps_for_test", None)
        sys.modules.update(hidden)


@pytest.mark.tooling
def test_runtime_probe_shared_prefers_canonical_when_both_loaded() -> None:
    """When both canonical and aliased copies are loaded, ``_shared()`` must
    deterministically return the canonical one — matches Python's default
    import semantics and avoids ambiguity in mixed environments (e.g. a
    pytest run where one test loaded the alias and another loaded canonical).
    """
    spec_dir = REPO_ROOT / "spec"
    pps_path = spec_dir / "parity_probe_support.py"

    # Ensure canonical is loaded.
    inserted_spec = False
    if str(spec_dir) not in sys.path:
        sys.path.insert(0, str(spec_dir))
        inserted_spec = True
    try:
        import parity_probe_support as canonical  # type: ignore[import-not-found]

        # Load a second copy under an alias and monkeypatch it with a sentinel.
        spec = importlib.util.spec_from_file_location("aliased_pps_for_test_2", str(pps_path))
        assert spec is not None and spec.loader is not None
        aliased = importlib.util.module_from_spec(spec)
        sys.modules["aliased_pps_for_test_2"] = aliased
        spec.loader.exec_module(aliased)
        aliased._OTEL_REQUIRED_CASE_IDS = frozenset({"alias_sentinel"})  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]

        try:
            import _runtime_probe

            shared = _runtime_probe._shared()
            assert shared.OTEL_REQUIRED_CASE_IDS is canonical._OTEL_REQUIRED_CASE_IDS, (
                "_shared() must prefer the canonical module when both copies are loaded "
                "(deterministic resolution); got the aliased sentinel instead."
            )
        finally:
            sys.modules.pop("aliased_pps_for_test_2", None)
    finally:
        if inserted_spec:
            sys.path.remove(str(spec_dir))
