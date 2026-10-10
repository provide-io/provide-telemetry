# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""The prometheus_metrics contract and its fixtures must agree with each other.

No SDK implements the contract yet, so nothing else reads these files. These
checks keep the spec section, spec/prometheus_fixtures.yaml and the conformance
capability gates consistent until the per-language parity suites take over.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.tooling

_REPO_ROOT = Path(__file__).parent.parent.parent
_SPEC = _REPO_ROOT / "spec" / "telemetry-api.yaml"
_FIXTURES = _REPO_ROOT / "spec" / "prometheus_fixtures.yaml"
_SIGNALS = ("logs", "traces", "metrics")
_EXPORTERS = frozenset({"otlp", "prometheus", "none"})
_LEGACY_METRIC_NAME = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")


def _load(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return _load(_SPEC)


@pytest.fixture(scope="module")
def contract(spec: dict[str, Any]) -> dict[str, Any]:
    section: dict[str, Any] = spec["prometheus_metrics"]
    return section


@pytest.fixture(scope="module")
def fixtures() -> dict[str, Any]:
    return _load(_FIXTURES)


def _conformance_module() -> ModuleType:
    module_spec = importlib.util.spec_from_file_location(
        "validate_conformance", _REPO_ROOT / "spec" / "validate_conformance.py"
    )
    assert module_spec is not None and module_spec.loader is not None
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def test_health_mapping_covers_every_snapshot_field_once(spec: dict[str, Any], contract: dict[str, Any]) -> None:
    health = contract["health_metrics"]
    mapped = [f"{entry['field']}_{signal}" for entry in health["per_signal"] for signal in _SIGNALS]
    mapped += [entry["field"] for entry in health["global"]]
    assert sorted(mapped) == sorted(spec["health_snapshot"]["fields"])


def test_health_metric_names_are_valid_under_every_strategy(contract: dict[str, Any]) -> None:
    """Health names are emitted unchanged, so they must already be legacy-valid and suffixed."""
    health = contract["health_metrics"]
    for entry in [*health["per_signal"], *health["global"]]:
        name = entry["metric"]
        assert _LEGACY_METRIC_NAME.match(name), name
        assert name.startswith("provide_telemetry_"), name
        assert name.endswith("_total") == (entry["type"] == "counter"), name


def test_full_snapshot_fixture_matches_the_mapping(contract: dict[str, Any], fixtures: dict[str, Any]) -> None:
    health = contract["health_metrics"]
    case = next(c for c in fixtures["health_metrics"] if c["id"] == "full_snapshot")
    snapshot = case["snapshot"]
    derived: list[tuple[str, tuple[tuple[str, str], ...], float]] = []
    for signal in _SIGNALS:
        for entry in health["per_signal"]:
            raw = snapshot[f"{entry['field']}_{signal}"]
            value = health["circuit_state_values"][raw] if entry["field"] == "circuit_state" else raw
            derived.append((entry["metric"], (("signal", signal),), float(value)))
    derived.append(("provide_telemetry_setup_error", (), 1.0 if snapshot["setup_error"] else 0.0))
    derived.append(("provide_telemetry_receipt_failures_total", (), float(snapshot["receipt_failures"])))
    expected = [(s["metric"], tuple(sorted(s["labels"].items())), float(s["value"])) for s in case["expected_samples"]]
    assert sorted(expected) == sorted(derived)


def test_metric_name_cases_cover_every_strategy(contract: dict[str, Any], fixtures: dict[str, Any]) -> None:
    translation = contract["translation"]
    strategies = set(translation["strategies"])
    assert translation["default"] in strategies
    ids = [case["id"] for case in fixtures["metric_names"]]
    assert len(ids) == len(set(ids)), "duplicate metric_names ids"
    for case in fixtures["metric_names"]:
        assert set(case["expected"]) == strategies, case["id"]
        assert case["instrument"] in translation["instrument_types"], case["id"]
        for strategy, name in case["expected"].items():
            if strategy.startswith("UnderscoreEscaping"):
                assert _LEGACY_METRIC_NAME.match(name), f"{case['id']}/{strategy}: {name}"


def test_every_instrument_type_has_a_name_case(contract: dict[str, Any], fixtures: dict[str, Any]) -> None:
    used = {case["instrument"] for case in fixtures["metric_names"]}
    assert used == set(contract["translation"]["instrument_types"])


def test_translation_strategy_cases_use_known_strategies(contract: dict[str, Any], fixtures: dict[str, Any]) -> None:
    strategies = set(contract["translation"]["strategies"])
    for case in fixtures["translation_strategy"]:
        if case.get("error"):
            assert case["value"] not in strategies, case["id"]
        else:
            assert case["strategy"] in strategies, case["id"]


def test_exporter_selection_cases_are_well_formed(fixtures: dict[str, Any]) -> None:
    for case in fixtures["exporter_selection"]:
        if case.get("error"):
            assert "exporters" not in case and "listener" not in case, case["id"]
        else:
            assert set(case["exporters"]) <= _EXPORTERS, case["id"]
            assert isinstance(case["listener"], bool), case["id"]


def test_listener_path_cases_resolve_to_valid_paths(fixtures: dict[str, Any]) -> None:
    for case in fixtures["listener_path"]:
        if case.get("error"):
            assert "path" not in case, case["id"]
            continue
        path = case["path"]
        assert path.startswith("/") and "?" not in path and "#" not in path, case["id"]


def test_listener_port_cases_are_in_range(fixtures: dict[str, Any]) -> None:
    for case in fixtures["listener_port"]:
        if not case.get("error"):
            assert 0 <= case["port"] <= 65535, case["id"]


def test_planned_config_has_not_also_landed_in_config_defaults(spec: dict[str, Any], contract: dict[str, Any]) -> None:
    """A key moves from planned_config to config_defaults; it must not be in both."""
    landed = {entry["env"] for entries in spec["config_defaults"].values() for entry in entries}
    planned = {entry["env"] for entry in contract["planned_config"]}
    assert not planned & landed


def test_prometheus_config_defaults_match_the_contract(spec: dict[str, Any], contract: dict[str, Any]) -> None:
    """Defaults live in planned_config or config_defaults depending on stage; check wherever they are."""
    entries = [*contract["planned_config"], *(e for es in spec["config_defaults"].values() for e in es)]
    defaults = {entry["env"]: entry["default"] for entry in entries}
    assert defaults["PROVIDE_METRICS_PROMETHEUS_TRANSLATION"] == contract["translation"]["default"]
    assert defaults["OTEL_EXPORTER_PROMETHEUS_HOST"] == "127.0.0.1"
    assert defaults["PROVIDE_METRICS_PROMETHEUS_LISTEN"] == "false"


def test_every_capability_in_the_api_is_known_to_conformance(spec: dict[str, Any]) -> None:
    capabilities = {
        entry["capability"]
        for entries in spec["api"].values()
        for entry in entries
        if isinstance(entry, dict) and "capability" in entry
    }
    known = set(_conformance_module()._CAPABILITY_LANGUAGES)
    assert capabilities <= known, sorted(capabilities - known)


def test_staged_capabilities_are_optional_symbols(spec: dict[str, Any]) -> None:
    """Staged symbols stay required: false so an unshipped language is not an error."""
    staged = [
        entry
        for entries in spec["api"].values()
        for entry in entries
        if isinstance(entry, dict) and entry.get("capability") in {"observable_metrics", "prometheus"}
    ]
    assert {e["name"] for e in staged} == {
        "observable_counter",
        "observable_gauge",
        "observable_up_down_counter",
        "metrics_handler",
        "render_prometheus",
    }
    assert all(entry["required"] is False for entry in staged)


def test_unsupported_push_modes_name_known_modes_and_languages(fixtures: dict[str, Any]) -> None:
    unsupported = fixtures["push_ingestion"]["unsupported_modes"]
    assert set(unsupported) <= {"basic_auth", "tls_basic_auth"}
    for mode, languages in unsupported.items():
        assert set(languages) <= {"python", "typescript", "go", "rust", "csharp"}, mode
        assert all(isinstance(reason, str) and reason for reason in languages.values()), mode


def test_web_config_cases_use_only_supported_keys_unless_they_expect_failure(
    contract: dict[str, Any], fixtures: dict[str, Any]
) -> None:
    supported = contract["listener_security"]["supported_keys"]
    tls_keys = set(supported["tls_server_config"])
    for case in fixtures["listener_web_config"]:
        config = case.get("web_config") or {}
        unknown = set(config) - set(supported)
        bad_tls = set(config.get("tls_server_config") or {}) - tls_keys
        if unknown or bad_tls:
            assert case["error"] is True and case["listener"] is False, case["id"]
        if case.get("error"):
            assert case["listener"] is False, f"{case['id']}: a config error must never leave the listener running"
