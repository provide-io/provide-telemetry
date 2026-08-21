# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""The fixture-ID gate must count per-case evidence, not accept a category name."""

from __future__ import annotations

import pytest

from spec.check_fixture_test_ids import _resolve_ids

pytestmark = pytest.mark.tooling


def test_list_shorter_than_case_count_is_an_error() -> None:
    errors = _resolve_ids(
        category="demo",
        language="python",
        identifier=["test_a", "test_b"],
        case_count=3,
        discovered={"test_a", "test_b"},
    )
    assert any("expected 3 test IDs" in error for error in errors)


def test_list_longer_than_case_count_is_an_error() -> None:
    errors = _resolve_ids(
        category="demo",
        language="python",
        identifier=["test_a", "test_b"],
        case_count=1,
        discovered={"test_a", "test_b"},
    )
    assert any("expected 1 test IDs" in error for error in errors)


def test_list_matching_case_count_with_all_ids_resolving_is_clean() -> None:
    errors = _resolve_ids(
        category="demo",
        language="python",
        identifier=["test_a", "test_b"],
        case_count=2,
        discovered={"test_a", "test_b"},
    )
    assert errors == []


def test_unresolved_id_inside_a_list_is_an_error() -> None:
    errors = _resolve_ids(
        category="demo",
        language="python",
        identifier=["test_a", "test_missing"],
        case_count=2,
        discovered={"test_a"},
    )
    assert any("test_missing" in error for error in errors)


def test_empty_entry_inside_a_list_is_an_error() -> None:
    errors = _resolve_ids(
        category="demo",
        language="python",
        identifier=["test_a", ""],
        case_count=2,
        discovered={"test_a"},
    )
    assert any("missing test ID" in error for error in errors)


def test_string_identifier_keeps_the_old_single_id_behaviour() -> None:
    errors = _resolve_ids(
        category="demo",
        language="python",
        identifier="test_a",
        case_count=7,
        discovered={"test_a"},
    )
    assert errors == []


def test_unresolved_string_identifier_is_an_error() -> None:
    errors = _resolve_ids(
        category="demo",
        language="python",
        identifier="test_missing",
        case_count=7,
        discovered={"test_a"},
    )
    assert any("unresolved test ID" in error for error in errors)


@pytest.mark.parametrize("identifier", [None, "", []])
def test_missing_or_empty_identifier_is_an_error(identifier: object) -> None:
    errors = _resolve_ids(
        category="demo",
        language="python",
        identifier=identifier,
        case_count=1,
        discovered=set(),
    )
    assert any("missing test ID" in error for error in errors)
