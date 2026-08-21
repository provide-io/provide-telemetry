# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Parity for the event_name_contract fixtures.

One test per case in the event_name_contract category of
spec/behavioral_fixtures.yaml, in fixture order.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from provide.telemetry.schema.events import (
    EventSchemaError,
    event,
    event_name,
    validate_event_name,
)

_STRICT_FLAG = "provide.telemetry.runtime._is_strict_event_name"


@pytest.fixture
def strict(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Enable strict schema for one test."""
    monkeypatch.setattr(_STRICT_FLAG, lambda: True)
    yield


@pytest.fixture(autouse=True)
def _relaxed_by_default(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Relaxed is the default; strict tests override it via the `strict` fixture."""
    monkeypatch.setattr(_STRICT_FLAG, lambda: False)
    yield


# ── variadic entry point: event_name() ────────────────────────────────────────


def test_parity_event_name_relaxed_single_segment_ok() -> None:
    assert event_name("startup") == "startup"


def test_parity_event_name_relaxed_two_segments_ok() -> None:
    assert event_name("app", "ready") == "app.ready"


def test_parity_event_name_relaxed_six_segments_ok() -> None:
    assert event_name("a", "b", "c", "d", "e", "f") == "a.b.c.d.e.f"


def test_parity_event_name_relaxed_grammar_not_enforced() -> None:
    assert event_name("User", "Login-OK") == "User.Login-OK"


def test_parity_event_name_relaxed_zero_segments_error() -> None:
    with pytest.raises(EventSchemaError):
        event_name()


def test_parity_event_name_relaxed_empty_segment_error() -> None:
    with pytest.raises(EventSchemaError):
        event_name("user", "", "ok")


def test_parity_event_name_strict_three_segments_ok(strict: None) -> None:
    assert event_name("user", "login", "ok") == "user.login.ok"


def test_parity_event_name_strict_five_segments_ok(strict: None) -> None:
    assert event_name("a", "b", "c", "d", "e") == "a.b.c.d.e"


def test_parity_event_name_strict_two_segments_error(strict: None) -> None:
    with pytest.raises(EventSchemaError):
        event_name("too", "few")


def test_parity_event_name_strict_six_segments_error(strict: None) -> None:
    with pytest.raises(EventSchemaError):
        event_name("a", "b", "c", "d", "e", "f")


def test_parity_event_name_strict_grammar_enforced(strict: None) -> None:
    with pytest.raises(EventSchemaError):
        event_name("user", "Login", "ok")


def test_parity_event_name_strict_zero_segments_error(strict: None) -> None:
    with pytest.raises(EventSchemaError):
        event_name()


# ── dotted-string entry point: validate_event_name() ──────────────────────────


def test_parity_validate_event_name_relaxed_single_segment_ok() -> None:
    validate_event_name("startup", strict_event_name=False)


def test_parity_validate_event_name_relaxed_empty_string_error() -> None:
    with pytest.raises(EventSchemaError):
        validate_event_name("", strict_event_name=False)


def test_parity_validate_event_name_relaxed_interior_empty_segment_error() -> None:
    with pytest.raises(EventSchemaError):
        validate_event_name("a..b", strict_event_name=False)


def test_parity_validate_event_name_relaxed_grammar_not_enforced() -> None:
    validate_event_name("User.Login-OK", strict_event_name=False)


def test_parity_validate_event_name_strict_grammar_enforced() -> None:
    with pytest.raises(EventSchemaError):
        validate_event_name("user.Login.ok", strict_event_name=True)


def test_parity_validate_event_name_strict_two_segments_error() -> None:
    with pytest.raises(EventSchemaError):
        validate_event_name("too.few", strict_event_name=True)


# ── event() is out of scope and must not move ─────────────────────────────────


def test_parity_event_count_rule_unchanged_by_relaxed_mode() -> None:
    with pytest.raises(EventSchemaError):
        event("only", "two")
    with pytest.raises(EventSchemaError):
        event("a", "b", "c", "d", "e")


def test_parity_event_name_contract_covers_every_fixture_case() -> None:
    """Every case in the event_name_contract fixture category has a test here.

    The fixture-ID gate checks that the manifest lists 18 identifiers and that
    each resolves. This checks the other direction: that the number of cases in
    the YAML has not grown past what this module actually exercises.
    """
    from pathlib import Path

    import yaml

    # Anchor to the real repo root via VERSION rather than counting parents:
    # mutmut relocates test files into mutants/, where parents[2] is the mutant
    # tree and spec/ does not exist. Same reason as
    # tests/parity/test_behavioral_fixtures.py::_find_repo_root_from.
    def _repo_root(start: Path) -> Path:
        for parent in start.resolve().parents:
            if (parent / "VERSION").exists():
                return parent
        raise FileNotFoundError(f"Could not locate repo root from {start}")  # pragma: no cover

    repo_root = _repo_root(Path(__file__))
    fixtures = yaml.safe_load((repo_root / "spec" / "behavioral_fixtures.yaml").read_text())
    cases = fixtures["event_name_contract"]

    module = globals()
    covering = {
        name
        for name in module
        if name.startswith(("test_parity_event_name_relaxed", "test_parity_event_name_strict"))
        or name.startswith("test_parity_validate_event_name_")
    }
    assert len(covering) == len(cases), (
        f"{len(cases)} fixture cases but {len(covering)} tests covering them: {sorted(covering)}"
    )
