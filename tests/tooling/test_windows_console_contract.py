# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""The `windows_console` contract is checked against the code, not just written.

Two failures this gate exists for, both of which happened.

The first is a wrong applicability list. `code_page` named Go for as long as it
took a test to allocate a real console and disprove it: Go classifies a console
handle as `kindConsole` and `internal/poll`'s `writeConsole` converts to UTF-16
and calls `WriteConsoleW`, so a code page never sees what Go writes. The claim
survived an issue, a spec block and two changelogs — every place where being
wrong is free. Asserting the list against the sources is what makes it cost
something.

The second is silent loss. Resolving a rebase conflict in favour of HEAD dropped
a whole clause out of `virtual_terminal`'s note, and nothing anywhere noticed;
prose in a spec file has no gate of its own. Structure can be checked even when
wording cannot, so the shape of each block is pinned here.
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

# The token each SDK uses to turn virtual-terminal processing on, and the file
# it lives in. A language listed under virtual_terminal.applicability must
# actually reach for it.
_VT_SOURCES = {
    "go": ("go/logger_console_windows.go", "ENABLE_VIRTUAL_TERMINAL_PROCESSING"),
    "csharp": ("csharp/src/Provide.Telemetry/ConsolePrep.cs", "EnableVirtualTerminalProcessing"),
    "python": ("src/provide/telemetry/logger/_windows_console.py", "_ENABLE_VIRTUAL_TERMINAL_PROCESSING"),
    "rust": ("rust/src/logger/windows_console.rs", "ENABLE_VIRTUAL_TERMINAL_PROCESSING"),
}

# Setting the console output code page. Only the SDK that encodes through one
# has any reason to, and the others must not acquire the habit.
_CODE_PAGE_SOURCES = {
    "csharp": ("csharp/src/Provide.Telemetry/ConsolePrep.cs", "OutputEncoding"),
}

_MUST_NOT_SET_CODE_PAGE = {
    "go": ("go/logger_console_windows.go", "SetConsoleOutputCP"),
    "rust": ("rust/src/logger/windows_console.rs", "SetConsoleOutputCP"),
    "python": ("src/provide/telemetry/logger/_windows_console.py", "SetConsoleOutputCP"),
}


def _spec() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(_SPEC.read_text(encoding="utf-8"))
    return loaded


def _block(name: str) -> dict[str, Any]:
    console = _spec()["windows_console"]
    assert name in console, f"windows_console lost its {name!r} block"
    section: dict[str, Any] = console[name]
    return section


def _source(relative: str) -> str:
    path = _REPO_ROOT / relative
    assert path.is_file(), f"{relative} is named by this gate but does not exist"
    return path.read_text(encoding="utf-8")


def test_every_block_keeps_its_shape() -> None:
    """A clause cannot go missing without this failing.

    Prose is not checkable, but its absence is: each block states the problem,
    the contract, who it applies to, and why the others are excluded.
    """
    console = _spec()["windows_console"]
    assert isinstance(console.get("description"), str)

    for name in ("code_page", "stream_encoding", "virtual_terminal"):
        block = _block(name)
        for key in ("problem", "contract", "applicability", "note"):
            value = block.get(key)
            assert value, f"windows_console.{name} is missing {key!r}"
            if key != "applicability":
                assert isinstance(value, str) and value.strip(), f"windows_console.{name}.{key} is empty"


def test_applicability_names_only_real_languages() -> None:
    for name in ("code_page", "stream_encoding", "virtual_terminal"):
        languages = set(_block(name)["applicability"])
        unknown = languages - KNOWN_LANGUAGES
        assert not unknown, f"windows_console.{name} names unknown languages: {sorted(unknown)}"
        assert languages, f"windows_console.{name} applies to nobody"


def test_every_language_owing_virtual_terminal_enables_it() -> None:
    """Declared and done, or not declared. The register of one is the code."""
    for language in sorted(_block("virtual_terminal")["applicability"]):
        relative, token = _VT_SOURCES[language]
        assert token in _source(relative), (
            f"{language} is listed under virtual_terminal but {relative} never reaches for {token}"
        )


def test_only_the_code_page_language_sets_a_code_page() -> None:
    """The correction that a console test had to make, kept made.

    Go was on this list until a test allocated a real console and showed CP437
    rendering its output correctly. Re-adding the call to any of the others
    would change the host's console for nothing.
    """
    for language in sorted(_block("code_page")["applicability"]):
        relative, token = _CODE_PAGE_SOURCES[language]
        assert token in _source(relative), f"{language} is listed under code_page but {relative} never sets one"

    for language, (relative, token) in sorted(_MUST_NOT_SET_CODE_PAGE.items()):
        assert language not in _block("code_page")["applicability"]
        assert token not in _source(relative), (
            f"{relative} sets the console code page, which {language} has no reason to: "
            "its runtime converts to UTF-16 and calls WriteConsoleW"
        )


def test_the_source_map_covers_every_language_that_could_be_listed() -> None:
    """A language added to the spec without an entry here would pass unchecked.

    The lookup would raise KeyError rather than skip, but only if someone runs
    it; this states the requirement up front instead.
    """
    assert set(_VT_SOURCES) | {"typescript"} == KNOWN_LANGUAGES
    assert set(_CODE_PAGE_SOURCES) | set(_MUST_NOT_SET_CODE_PAGE) | {"typescript"} == KNOWN_LANGUAGES
