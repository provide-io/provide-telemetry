# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""The Python SDK against the cross-language JCS number vectors.

``spec/jcs_number_fixtures.yaml`` carries one vector per branch of the
ECMAScript ``Number::toString`` algorithm that RFC 8785 defers to. It exists
because ``spec/receipt_fixtures.yaml``'s seven whole receipts are realistic
payloads, and realistic payloads never reach the exponent thresholds, the
significand-trimming path, or the zero-padding branch — so two real bugs shipped
past them. Python rendered ``1e21`` as ``"0.1"``, colliding with ``0.1`` and
``1e22`` on a single receipt digest; C# rendered ``1e-6`` as ``"1e-6"`` where
every other SDK emits ``"0.000001"``. Both are fixed, and these vectors are what
turn a regression into a failing test instead of a shipped digest collision.

Every case is asserted twice: the number rendered alone, and the same number
inside ``{"v": ...}``. A serializer can format correctly in isolation and still
lose the value in context.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from provide.telemetry.receipts import canonical_json


def _find_fixtures() -> Path:
    """Locate spec/jcs_number_fixtures.yaml by walking up, not by counting parents.

    mutmut runs the suite against a copy of the tree under ``mutants/``, which
    has no ``spec/`` beside it, so a fixed ``parent.parent.parent`` resolves to a
    path that does not exist and the whole file errors during collection.
    Walking up until the fixture is found works from either location.
    """
    for candidate in Path(__file__).resolve().parents:
        fixtures = candidate / "spec" / "jcs_number_fixtures.yaml"
        if fixtures.is_file():
            return fixtures
    raise RuntimeError("spec/jcs_number_fixtures.yaml not found in any parent directory")


_FIXTURES = _find_fixtures()

# One vector per branch of Number::toString, as committed. Asserted below so a
# parse failure or a truncated file fails loudly instead of turning every
# parametrized case into a vacuous pass over an empty list.
_EXPECTED_CASE_COUNT = 21


def _cases() -> list[dict[str, Any]]:
    loaded: dict[str, Any] = yaml.safe_load(_FIXTURES.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = loaded["cases"]
    return cases


def _value_of(case: dict[str, Any]) -> Any:
    """Recover the float64 a JavaScript producer would have canonicalized.

    ``parse_int=float`` is load bearing. JavaScript has a single number type, so
    the fixture spells ``1e20`` and ``1e21`` without a decimal point exactly as
    ``JSON.stringify`` renders them. Python's ``json`` would hand those back as
    ``int``, which takes the ``isinstance(value, int)`` shortcut in
    ``_canonical`` and never reaches ``_format_number`` — the code path these
    vectors exist to pin.
    """
    parsed: dict[str, Any] = json.loads(case["in_object"], parse_int=float)
    return parsed["v"]


def test_every_committed_number_vector_is_exercised() -> None:
    assert len(_cases()) >= _EXPECTED_CASE_COUNT


@pytest.mark.parametrize("case", _cases(), ids=lambda case: str(case["id"]))
def test_number_renders_to_its_canonical_form(case: dict[str, Any]) -> None:
    assert canonical_json(_value_of(case)) == case["canonical"], case["branch"]


@pytest.mark.parametrize("case", _cases(), ids=lambda case: str(case["id"]))
def test_number_renders_the_same_inside_an_object(case: dict[str, Any]) -> None:
    assert canonical_json({"v": _value_of(case)}) == case["in_object"], case["branch"]
