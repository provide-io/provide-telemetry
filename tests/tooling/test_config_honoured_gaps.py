# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""The honoured-gaps register must stay honest.

`check_config_parity.py` decides applicability differentially: it sets a
variable, rebuilds the config, and calls the variable supported when the config
object changes. That answers "does this SDK parse it", never "does this SDK
honour it" — which is how two variables stayed parsed-but-dead in Go while five
gates ran green.

`spec/config_honoured_gaps.yaml` is where that divergence is declared. These
tests keep the register itself from rotting: an entry naming a language that
does not exist, a variable the spec has dropped, or a pair the spec already
marks not-applicable is worse than no entry at all, because it reads as a
tracked debt that nobody can act on.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.tooling

REPO_ROOT = Path(__file__).resolve().parents[2]
GAPS_PATH = REPO_ROOT / "spec" / "config_honoured_gaps.yaml"
SPEC_PATH = REPO_ROOT / "spec" / "telemetry-api.yaml"
CHECKER_PATH = REPO_ROOT / "spec" / "check_config_parity.py"

REQUIRED_FIELDS = ("lang", "env", "reason", "owner", "expires_on")


def _checker() -> Any:
    spec = importlib.util.spec_from_file_location("_check_config_parity_gaps_module", CHECKER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before exec: the module defines a dataclass, and dataclasses
    # resolves annotations through sys.modules[cls.__module__].
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _gaps() -> list[dict[str, Any]]:
    data = yaml.safe_load(GAPS_PATH.read_text(encoding="utf-8"))
    return list(data.get("honoured_gaps") or [])


def _spec_entries() -> dict[str, list[str]]:
    """env var -> the languages the spec says it applies to."""
    spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    return {
        entry["env"]: list(entry.get("applicability") or [])
        for entries in spec["config_defaults"].values()
        for entry in entries
    }


def test_every_gap_carries_the_required_fields() -> None:
    for index, gap in enumerate(_gaps()):
        missing = [field for field in REQUIRED_FIELDS if not gap.get(field)]
        assert missing == [], f"entry #{index} is missing {missing}: {gap}"


def test_every_gap_names_a_known_language() -> None:
    known = set(_checker().REQUIRED_LANGUAGES)
    for gap in _gaps():
        assert gap["lang"] in known, f"unknown language {gap['lang']!r}: {gap}"


def test_every_gap_names_a_variable_the_spec_declares() -> None:
    declared = _spec_entries()
    for gap in _gaps():
        assert gap["env"] in declared, f"{gap['env']} is not in telemetry-api.yaml config_defaults"


def test_no_gap_contradicts_applicability() -> None:
    """A gap for a variable the spec says does not apply is stale, not tracked.

    Either the SDK was never meant to honour it — in which case the entry should
    go — or the applicability list is wrong. Both are edits; neither is a gap.
    """
    declared = _spec_entries()
    for gap in _gaps():
        applicable = declared[gap["env"]]
        assert gap["lang"] in applicable, (
            f"{gap['lang']} is not in {gap['env']}'s applicability {applicable}; "
            "the entry is stale or the spec is wrong"
        )


def test_every_expiry_is_a_real_date() -> None:
    for gap in _gaps():
        value = gap["expires_on"]
        parsed = value if isinstance(value, dt.date) else dt.date.fromisoformat(str(value))
        assert isinstance(parsed, dt.date)


def test_the_register_is_readable_even_when_empty() -> None:
    """An empty register is the goal state, and must still parse.

    Every gap has been closed, so the file now holds ``honoured_gaps: []``. It
    is kept rather than deleted because the mechanism is what matters: an entry
    here excuses a language from the callsite-attribution pass, and that pass is
    two-sided, so a gap cannot be added to dodge a failure without the
    divergence showing, nor removed before the work is done.

    This asserts the file stays loadable — a malformed register would otherwise
    read as "no gaps" to every consumer, which is exactly the silence the
    register exists to break.
    """
    data = yaml.safe_load(GAPS_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "register must parse to a mapping"
    assert isinstance(data.get("honoured_gaps"), list), "honoured_gaps must be a list, even when empty"
