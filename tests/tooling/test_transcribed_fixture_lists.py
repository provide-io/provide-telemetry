# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Guard the endpoint fixture lists that are transcribed rather than parsed.

Python, Go and TypeScript read ``spec/behavioral_fixtures.yaml`` at test time,
so a new case reaches them for free. Rust and C# hard-code the same cases as
literals, because neither test project takes a YAML dependency for this. That
is a reasonable trade, but it is only safe if something checks the copy.

Nothing did. When ``endpoint_validation`` gained the two credentialed-endpoint
cases, the three YAML-reading languages picked them up automatically and the
two transcribing ones would have stayed silently green against the old list —
the same "gate passes while measuring something else" shape that hid a C#
coverage report, a mypy run without the otel extra, and a cargo-mutants run
that tested zero mutants.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.tooling


def _project_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "VERSION").exists():
            return parent
    raise FileNotFoundError("Could not locate project root (no VERSION file found)")


_ROOT = _project_root()
_FIXTURES = yaml.safe_load((_ROOT / "spec" / "behavioral_fixtures.yaml").read_text(encoding="utf-8"))
_ENDPOINTS = _FIXTURES["endpoint_validation"]


def _expected(kind: str) -> list[str]:
    return [case["endpoint"] for case in _ENDPOINTS[kind]]


def _strip_line_comments(source: str) -> str:
    """Drop whole-line ``//`` comments so commentary is not mistaken for a case.

    Only whole-line comments, because every endpoint in the list contains ``//``
    itself — splitting on the first occurrence turns ``"http://host"`` into
    ``"http:"`` and the comparison then fails against a fixture that is fine.
    """
    return "\n".join(line for line in source.splitlines() if not line.strip().startswith("//"))


def _rust_array(function: str) -> list[str]:
    """Return the string literals in the array bound inside a Rust test fn."""
    source = (_ROOT / "rust" / "src" / "otel" / "endpoint.rs").read_text(encoding="utf-8")
    body = re.search(rf"fn {function}\(\) \{{(.*?)\n    \}}", source, re.DOTALL)
    assert body is not None, f"could not find Rust fn {function}"
    literals = re.search(r"= \[(.*?)\];", body.group(1), re.DOTALL)
    assert literals is not None, f"could not find the array literal in {function}"
    return re.findall(r'"([^"]*)"', _strip_line_comments(literals.group(1)))


def _csharp_inline_data(method: str) -> list[str]:
    """Return the InlineData arguments attached to a C# test method."""
    path = _ROOT / "csharp" / "tests" / "Provide.Telemetry.Tests" / "ParityOtherTests.cs"
    lines = path.read_text(encoding="utf-8").splitlines()
    index = next(i for i, line in enumerate(lines) if f"public void {method}(" in line)
    cases: list[str] = []
    for line in reversed(lines[:index]):
        stripped = line.strip()
        if stripped.startswith("[InlineData("):
            match = re.search(r'\[InlineData\("([^"]*)"\)\]', stripped)
            assert match is not None, f"unparsed InlineData in {method}: {stripped}"
            cases.append(match.group(1))
            continue
        if stripped.startswith("[Theory]"):
            continue
        break
    return list(reversed(cases))


@pytest.mark.parametrize("kind", ["valid", "invalid"])
def test_rust_transcribes_every_endpoint_fixture_case(kind: str) -> None:
    assert _rust_array(f"parity_{kind}_endpoints") == _expected(kind)


def test_csharp_transcribes_every_valid_endpoint_fixture_case() -> None:
    """Only the valid list is compared, and the asymmetry is deliberate.

    ``EndpointValidation_Valid`` asserts that config parsing carries each valid
    endpoint through unchanged, so it must track the fixture exactly. The
    matching invalid list does not: C# parsing soft-validates on purpose (as
    Python's ``from_env`` does), rejecting only schemes an OTLP client could
    never speak. The shape and port cases are enforced one layer down, by
    ``Endpoints.BuildSignalUri``, and are pinned there by
    ``MalformedEndpointsAreRefusedAtExporterConstruction``.
    """
    assert _csharp_inline_data("EndpointValidation_Valid") == _expected("valid")


def test_the_transcribed_languages_are_the_only_ones_not_reading_the_yaml() -> None:
    """Fail if a language stops reading the fixture without gaining a check above.

    Without this, moving Go or TypeScript to a hard-coded list would drop it out
    of every guard here and out of the YAML-driven ones, leaving nothing.
    """
    readers = {
        "go": _ROOT / "go" / "parity_endpoint_test.go",
        "typescript": _ROOT / "typescript" / "tests" / "endpoint.test.ts",
        "python": _ROOT / "tests" / "parity" / "test_parity_endpoint_validation.py",
    }
    for language, path in readers.items():
        assert "behavioral_fixtures.yaml" in path.read_text(encoding="utf-8"), (
            f"{language} no longer reads the fixture; it now needs a transcription check"
        )
