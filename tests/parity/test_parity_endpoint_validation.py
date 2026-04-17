# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Parity test: endpoint_validation fixtures from behavioral_fixtures.yaml."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from provide.telemetry._endpoint import validate_otlp_endpoint

_FIXTURES_PATH = Path(__file__).resolve().parent.parent.parent / "spec" / "behavioral_fixtures.yaml"
_FIXTURES = yaml.safe_load(_FIXTURES_PATH.read_text())
_EP = _FIXTURES["endpoint_validation"]


@pytest.mark.parametrize("case", _EP["valid"], ids=lambda c: c["description"])
def test_parity_endpoint_validation_valid(case: dict[str, str]) -> None:
    assert validate_otlp_endpoint(case["endpoint"]) == case["endpoint"]


@pytest.mark.parametrize("case", _EP["invalid"], ids=lambda c: c["description"])
def test_parity_endpoint_validation_invalid(case: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        validate_otlp_endpoint(case["endpoint"])
