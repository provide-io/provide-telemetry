# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Cross-language parity for the ``resource_precedence`` fixture.

Validates the shared "explicit = differs from framework default" gate that every
language's resource builder applies. Go, TypeScript, and Rust have equivalent
checks. End-to-end env-layer precedence is covered by tests/test_resource.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
import yaml

from provide.telemetry._resource import _resolve_resource_attrs
from provide.telemetry.config import TelemetryConfig

# The mutmut mutation gate runs tests from a `mutants/` sandbox that copies only
# src + tests, not spec/, so skip the whole module when the fixture is absent
# (the _resource mutants are killed by tests/test_resource.py regardless).
_FIXTURE_PATH = Path(__file__).resolve().parents[2] / "spec" / "behavioral_fixtures.yaml"
if not _FIXTURE_PATH.exists():
    pytest.skip("behavioral_fixtures.yaml not available (mutmut sandbox)", allow_module_level=True)

_FIXTURES = yaml.safe_load(_FIXTURE_PATH.read_text())
_RESOURCE = _FIXTURES["resource_precedence"]
# Passing every identity key as "env-provided" suppresses the floor layer, so
# _resolve_resource_attrs returns exactly the explicit (non-default) attributes.
_ALL_IDENTITY_KEYS = set(_RESOURCE["keys"].values())


@pytest.mark.parametrize(
    "case",
    _RESOURCE["cases"],
    ids=[c["description"] for c in _RESOURCE["cases"]],
)
def test_parity_resource_precedence_explicit_keys(case: dict[str, object]) -> None:
    config_fields = cast("dict[str, str]", case["config"])
    config = TelemetryConfig(**config_fields)  # type: ignore[arg-type]
    explicit = _resolve_resource_attrs(config, _ALL_IDENTITY_KEYS)
    expected = cast("list[str]", case["expected_explicit_keys"])
    assert set(explicit) == set(expected)
