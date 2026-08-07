# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Every canonical config default must declare which SDKs it applies to.

`config_defaults` in spec/telemetry-api.yaml is the contract the per-language
config probes are diffed against.  Without an explicit `applicability` list a
comparator cannot tell "this SDK is missing a variable it should support" from
"this variable was never meant for that SDK", so an absent knob reads as parity.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.tooling

_REPO_ROOT = Path(__file__).parent.parent.parent
_SPEC = _REPO_ROOT / "spec" / "telemetry-api.yaml"

KNOWN_LANGUAGES = frozenset({"python", "typescript", "go", "rust", "csharp"})


def _spec() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(_SPEC.read_text(encoding="utf-8"))
    return loaded


def _config_entries() -> list[tuple[str, dict[str, Any]]]:
    """Flatten config_defaults into (category, entry) pairs.

    Note the real shape is ``category -> list[entry]``, not ``name -> entry``.
    """
    pairs: list[tuple[str, dict[str, Any]]] = []
    for category, entries in _spec()["config_defaults"].items():
        assert isinstance(entries, list), f"{category}: config_defaults values must be lists"
        for entry in entries:
            pairs.append((category, entry))
    return pairs


def test_every_config_default_declares_applicability() -> None:
    missing = [f"{category}:{entry['env']}" for category, entry in _config_entries() if not entry.get("applicability")]
    assert not missing, f"config defaults without an applicability list: {missing}"


def test_applicability_names_only_known_languages() -> None:
    unknown: list[str] = []
    for category, entry in _config_entries():
        extra = set(entry.get("applicability") or []) - KNOWN_LANGUAGES
        if extra:
            unknown.append(f"{category}:{entry['env']} -> {sorted(extra)}")
    assert not unknown, f"config defaults naming unknown languages: {unknown}"


def test_applicability_is_a_list_not_a_bare_string() -> None:
    """A bare string would make ``"python" in applicability`` match substrings."""
    bad = [
        f"{category}:{entry['env']}"
        for category, entry in _config_entries()
        if entry.get("applicability") is not None and not isinstance(entry["applicability"], list)
    ]
    assert not bad, f"applicability must be a list: {bad}"


def test_at_least_one_entry_is_not_universal() -> None:
    """Guard against the whole field being rubber-stamped as all five languages.

    If every entry claims all five SDKs, the field carries no information and the
    comparator silently degrades to "compare everything everywhere".
    """
    applicabilities = {tuple(sorted(entry.get("applicability") or [])) for _, entry in _config_entries()}
    assert len(applicabilities) > 1, (
        "every config default declares the same applicability; the field was likely "
        "filled in uniformly rather than by checking which SDKs parse each variable"
    )


def test_health_snapshot_declares_receipt_failures() -> None:
    """Governance receipt delivery must be observable in the health snapshot.

    A sink that silently drops receipts is indistinguishable from one that
    delivers them unless the failure count is part of the canonical surface.
    """
    fields = _spec()["health_snapshot"]["fields"]
    assert "receipt_failures" in fields
    assert fields["receipt_failures"]["type"] == "uint64"


def test_health_snapshot_field_count_is_pinned() -> None:
    """26 serialized fields: the 25 that existed plus receipt_failures.

    Pinning the count makes an accidental addition or removal a test failure
    rather than a silent change to a cross-language contract.
    """
    assert len(_spec()["health_snapshot"]["fields"]) == 26
