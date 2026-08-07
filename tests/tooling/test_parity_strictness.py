# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""The five-language parity gates must be strict by default.

A gate that downgrades an absent toolchain to "skip" reports success for a
language it never exercised.  These tests pin two properties: every gate knows
about all five SDKs, and a missing runtime is a failure unless the operator
explicitly opts out.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

pytestmark = pytest.mark.tooling

_REPO_ROOT = Path(__file__).parent.parent.parent
_FIXTURE_IDS = _REPO_ROOT / "spec" / "check_fixture_test_ids.py"
_RUNNER = _REPO_ROOT / "spec" / "run_behavioral_parity.py"

EXPECTED_LANGUAGES = ("python", "typescript", "go", "rust", "csharp")


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_required_languages_include_csharp() -> None:
    module = _load_module(_FIXTURE_IDS, "check_fixture_test_ids_strictness_module")
    assert module.REQUIRED_LANGUAGES == EXPECTED_LANGUAGES


def test_fixture_manifest_maps_every_category_to_csharp() -> None:
    manifest = yaml.safe_load((_REPO_ROOT / "spec" / "fixture_test_ids.yaml").read_text(encoding="utf-8"))
    mappings = manifest["fixture_test_ids"]
    missing = [category for category, by_language in mappings.items() if not by_language.get("csharp")]
    assert not missing, f"fixture categories with no C# evidence: {missing}"


def test_csharp_ids_are_discovered_from_the_parity_corpus() -> None:
    module = _load_module(_FIXTURE_IDS, "check_fixture_test_ids_discovery_module")
    discovered = module._csharp_ids()
    assert discovered, "no C# parity test IDs discovered"
    # Sanity-check a method that exists in csharp/tests/.../ParitySamplingTests.cs
    assert "Sampling_RateZero_AlwaysDrops" in discovered


def test_fixture_gate_passes_for_five_languages() -> None:
    module = _load_module(_FIXTURE_IDS, "check_fixture_test_ids_validate_module")
    assert module.validate() == []


def test_missing_runtime_is_fatal_by_default() -> None:
    """A runner whose toolchain is absent must not be recorded as a skip."""
    module = _load_module(_RUNNER, "run_behavioral_parity_strictness_module")
    parser = module._build_parser()
    args = parser.parse_args([])
    assert args.allow_missing_runtimes is False, (
        "missing runtimes must be fatal unless the operator explicitly opts out"
    )


def test_strict_flag_is_accepted_and_is_the_default() -> None:
    """--strict stays valid so the documented CI invocation keeps working."""
    module = _load_module(_RUNNER, "run_behavioral_parity_strict_flag_module")
    parser = module._build_parser()
    strict = parser.parse_args(["--strict"])
    default = parser.parse_args([])
    assert strict.allow_missing_runtimes == default.allow_missing_runtimes is False


def test_opt_out_flag_allows_missing_runtimes() -> None:
    module = _load_module(_RUNNER, "run_behavioral_parity_optout_module")
    parser = module._build_parser()
    args = parser.parse_args(["--allow-missing-runtimes"])
    assert args.allow_missing_runtimes is True


def test_default_language_selection_is_all_five() -> None:
    module = _load_module(_RUNNER, "run_behavioral_parity_langs_module")
    parser = module._build_parser()
    args = parser.parse_args([])
    selected = tuple(s.strip() for s in args.lang.split(","))
    assert set(selected) == set(EXPECTED_LANGUAGES)
