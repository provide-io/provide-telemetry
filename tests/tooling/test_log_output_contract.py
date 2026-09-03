# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""The `log_output` contract is checked against the code, not just written.

The section records a decision, not only a capability: four of the five SDKs
deliberately have no log sink, because their runtimes leave the host a native
way to redirect and a second SDK-specific one would be a second way to do what
already works. A decision that lives only in prose gets re-litigated, or quietly
reversed by someone adding a sink to one more SDK because Go has one.

So the claims are asserted against the sources. `applicability` must name the
languages whose runtime is closed after setup, and each `host_control` entry
must match what that SDK's code actually does — a sink appearing in a fifth
language, or an SDK moving off the write path named here, fails this file rather
than drifting away from the spec unnoticed.

The lesson is borrowed from `windows_console`, whose `code_page` clause named Go
for as long as it took a real console test to disprove it. Prose in a spec file
is free to be wrong; an assertion is not.
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

# The languages whose log destination the host cannot reach once setup returns.
# These are the only ones a sink is worth building for.
_CLOSED_RUNTIMES = frozenset({"go", "rust"})

# What each SDK's write path is, as a token that must appear in the file that
# owns it. `host_control` in the spec describes these; if one moves, the
# description is stale and this fails.
_WRITE_PATHS = {
    "go": ("go/logger_sink.go", "_logOutput"),
    "rust": ("rust/src/logger/sink.rs", "eprintln!"),
    "python": ("src/provide/telemetry/logger/core.py", "logging.basicConfig"),
    "csharp": ("csharp/src/Provide.Telemetry/Logger.cs", "Console.Error.WriteLine"),
    "typescript": ("typescript/src/logger.ts", "console"),
}

# The two implementations the contract describes, each reached by the route its
# setup surface allows. Go takes the writer as a setup option; Rust installs it
# independently of setup. Neither puts it in the config: that is the
# cross-language wire shape Rust deserializes and callers receive as a deep
# copy, and a handle survives neither.
_SINKS = {
    "go": (
        ("go/setup.go", "WithLogOutput"),
        ("go/logger_sink.go", "_installLogSink"),
        ("go/logger_sink.go", "_isTerminalWriter"),
    ),
    "rust": (
        ("rust/src/logger/sink.rs", "pub fn set_log_output"),
        ("rust/src/logger/sink.rs", "pub fn clear_log_output"),
        ("rust/src/logger/sink.rs", "fn flush_log_output"),
    ),
}

# Colour follows the sink. Rust cannot ask a writer whether it is a terminal
# without charging every host a trait implementation, so it assumes not — and
# the assumption has to be in the code, not only in the clause that claims it.
_RUST_COLOUR_GUARD = ("rust/src/logger/pretty.rs", "log_output_installed")


def _spec() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(_SPEC.read_text(encoding="utf-8"))
    return loaded


def _log_output() -> dict[str, Any]:
    spec = _spec()
    assert "log_output" in spec, "the spec lost its log_output section"
    section: dict[str, Any] = spec["log_output"]
    return section


def _source(relative_path: str) -> str:
    return (_REPO_ROOT / relative_path).read_text(encoding="utf-8")


@pytest.mark.parametrize("key", ["description", "problem", "contract", "applicability", "host_control", "note"])
def test_the_section_keeps_its_shape(key: str) -> None:
    """A rebase that drops a clause fails here; prose has no gate of its own."""
    value = _log_output().get(key)
    assert value, f"log_output is missing {key!r}"


def test_applicability_names_only_closed_runtimes() -> None:
    """A sink is for a runtime the host cannot redirect, and only for those."""
    applicability = set(_log_output()["applicability"])
    assert applicability <= KNOWN_LANGUAGES, f"unknown languages: {applicability - KNOWN_LANGUAGES}"
    assert applicability <= _CLOSED_RUNTIMES, (
        f"{applicability - _CLOSED_RUNTIMES} can already be redirected by the host; "
        "a sink there would duplicate the platform's own mechanism"
    )


def test_host_control_describes_every_language() -> None:
    """Silence about a language is how one drifts; each must be accounted for."""
    described = set(_log_output()["host_control"])
    assert described == KNOWN_LANGUAGES, f"host_control covers {described}, expected {KNOWN_LANGUAGES}"


@pytest.mark.parametrize(("language", "location"), sorted(_WRITE_PATHS.items()))
def test_each_write_path_is_still_where_the_spec_says(language: str, location: tuple[str, str]) -> None:
    """host_control describes real code; a moved write path makes it stale."""
    relative_path, token = location
    assert token in _source(relative_path), (
        f"{language}: {token!r} is gone from {relative_path}, so log_output.host_control "
        f"no longer describes how {language} writes"
    )


@pytest.mark.parametrize(
    ("language", "relative_path", "token"),
    [(lang, path, token) for lang, entries in sorted(_SINKS.items()) for path, token in entries],
)
def test_each_listed_language_implements_the_sink(language: str, relative_path: str, token: str) -> None:
    """A language in applicability must actually have one."""
    assert token in _source(relative_path), f"{language}: {token!r} is gone from {relative_path}"


def test_every_language_with_a_sink_is_listed() -> None:
    """A sink that appears without a spec change is the drift this prevents."""
    assert set(_SINKS) == set(_log_output()["applicability"]), (
        f"the sinks in the tree are {sorted(_SINKS)} but log_output.applicability "
        f"says {sorted(_log_output()['applicability'])}"
    )


def test_rust_decides_colour_from_the_destination() -> None:
    """The clause says a sink Rust cannot establish as a terminal gets no colour.

    That is a claim about the renderer, so it is asserted against the renderer:
    the pretty path has to consult the sink rather than probe the process.
    """
    relative_path, token = _RUST_COLOUR_GUARD
    assert token in _source(relative_path), (
        f"{relative_path} no longer consults {token!r}, so pretty output can carry ANSI "
        "into a writer that is not known to render it"
    )
