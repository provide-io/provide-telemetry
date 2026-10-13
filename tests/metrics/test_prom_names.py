# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""The Python port of otlptranslator against every reference-generated case."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from provide.telemetry.metrics import _prom_names as names


def _repo_root() -> Path:
    """The directory holding VERSION; mutmut runs these tests from a copy under mutants/."""
    return next(p for p in Path(__file__).resolve().parents if (p / "VERSION").exists())


_FIXTURES: dict[str, Any] = yaml.safe_load(
    (_repo_root() / "spec" / "prometheus_fixtures.yaml").read_text(encoding="utf-8")
)
_SPEC: dict[str, Any] = yaml.safe_load((_repo_root() / "spec" / "telemetry-api.yaml").read_text(encoding="utf-8"))
_KINDS: dict[str, str] = _SPEC["prometheus_metrics"]["translation"]["instrument_types"]
_STRATEGIES: list[str] = _SPEC["prometheus_metrics"]["translation"]["strategies"]


def _metric_cases() -> list[tuple[str, str, str, str, str | None]]:
    cases = []
    for section in ("metric_names", "translation_corpus", "translator_only_corpus"):
        for c in _FIXTURES[section]:
            for strategy, want in c["expected"].items():
                cases.append((c["name"], c["unit"], _KINDS[c["instrument"]], strategy, want))
    return cases


@pytest.mark.parametrize(("name", "unit", "kind", "strategy", "want"), _metric_cases())
def test_metric_name_matches_reference(name: str, unit: str, kind: str, strategy: str, want: str | None) -> None:
    if want is None:
        with pytest.raises(ValueError, match="translates to nothing usable"):
            names.metric_name(name, unit, kind, strategy)
    else:
        assert names.metric_name(name, unit, kind, strategy) == want


def _label_cases() -> list[tuple[str, str, str | None]]:
    cases = []
    for c in [*_FIXTURES["label_names"], *_FIXTURES["label_corpus"]]:
        for strategy in _STRATEGIES:
            cases.append((c["attribute"], strategy, c["escaped"] if strategy.startswith("Underscore") else c["utf8"]))
    return cases


@pytest.mark.parametrize(("attribute", "strategy", "want"), _label_cases())
def test_label_name_matches_reference(attribute: str, strategy: str, want: str | None) -> None:
    if want is None:
        with pytest.raises(ValueError, match="cannot be a label name"):
            names.label_name(attribute, strategy)
    else:
        assert names.label_name(attribute, strategy) == want


def test_empty_attribute_is_rejected() -> None:
    with pytest.raises(ValueError, match="cannot be a label name"):
        names.label_name("", "NoTranslation")


def test_escaped_name_of_only_invalid_characters_is_rejected() -> None:
    with pytest.raises(ValueError, match="translates to nothing usable"):
        names.metric_name("...", "", names.KIND_GAUGE, "UnderscoreEscapingWithoutSuffixes")


def test_name_already_valid_without_suffixes_is_unchanged() -> None:
    assert names.metric_name("_", "", names.KIND_GAUGE, "UnderscoreEscapingWithoutSuffixes") == "_"


@pytest.mark.parametrize(
    ("strategy", "escapes", "suffixes"),
    [
        ("UnderscoreEscapingWithSuffixes", True, True),
        ("UnderscoreEscapingWithoutSuffixes", True, False),
        ("NoUTF8EscapingWithSuffixes", False, True),
        ("NoTranslation", False, False),
    ],
)
def test_strategy_flags(strategy: str, escapes: bool, suffixes: bool) -> None:
    assert names.escapes(strategy) is escapes
    assert names.adds_suffixes(strategy) is suffixes
