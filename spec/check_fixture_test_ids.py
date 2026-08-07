#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Require executable test/probe evidence for every fixture and language."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_LANGUAGES = ("python", "typescript", "go", "rust", "csharp")


def _python_ids() -> set[str]:
    result: set[str] = set()
    for path in (ROOT / "tests" / "parity").glob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        result.update(
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
        )
    return result


def _typescript_ids() -> set[str]:
    result: set[str] = set()
    paths = [
        *(ROOT / "typescript" / "tests").glob("parity*.test.ts"),
        ROOT / "typescript" / "tests" / "endpoint.test.ts",
    ]
    pattern = re.compile(r"""\b(?:describe|it|test)\s*\(\s*['"]([^'"]+)['"]""")
    for path in paths:
        result.update(pattern.findall(path.read_text(encoding="utf-8")))
    return result


def _go_ids() -> set[str]:
    pattern = re.compile(r"^func\s+(Test\w+)\s*\(", re.MULTILINE)
    paths = [*(ROOT / "go").glob("parity*_test.go"), ROOT / "go" / "otel" / "config_resource_test.go"]
    result: set[str] = set()
    for path in paths:
        result.update(pattern.findall(path.read_text(encoding="utf-8")))
    return result


def _rust_ids() -> set[str]:
    pattern = re.compile(r"^\s*fn\s+([a-zA-Z_]\w*)\s*\(", re.MULTILINE)
    paths = [
        *(ROOT / "rust" / "tests").glob("parity*.rs"),
        ROOT / "rust" / "src" / "otel" / "endpoint.rs",
        ROOT / "rust" / "src" / "otel" / "resource.rs",
    ]
    result: set[str] = set()
    for path in paths:
        result.update(pattern.findall(path.read_text(encoding="utf-8")))
    return result


def _csharp_ids() -> set[str]:
    # xUnit facts are `[Fact]`/`[Theory]`-attributed methods; the attribute may
    # carry arguments (`[Theory]` + `[InlineData(...)]` lines) and the signature
    # may be async, so match the declaration rather than the attribute line.
    pattern = re.compile(
        r"^\s*public\s+(?:async\s+)?(?:void|Task|ValueTask)\s+(\w+)\s*\(",
        re.MULTILINE,
    )
    result: set[str] = set()
    for path in (ROOT / "csharp" / "tests").rglob("Parity*.cs"):
        result.update(pattern.findall(path.read_text(encoding="utf-8")))
    return result


def _is_probe(identifier: str) -> bool:
    if not identifier.startswith("probe:"):
        return False
    path = (ROOT / identifier.removeprefix("probe:")).resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError:
        return False
    return path.is_file() and "log.output.parity" in path.read_text(encoding="utf-8")


def validate() -> list[str]:
    fixtures = yaml.safe_load((ROOT / "spec" / "behavioral_fixtures.yaml").read_text(encoding="utf-8"))
    manifest = yaml.safe_load((ROOT / "spec" / "fixture_test_ids.yaml").read_text(encoding="utf-8"))
    mappings = manifest.get("fixture_test_ids", {})
    discovered = {
        "python": _python_ids(),
        "typescript": _typescript_ids(),
        "go": _go_ids(),
        "rust": _rust_ids(),
        "csharp": _csharp_ids(),
    }
    errors: list[str] = []
    fixture_categories = set(fixtures)
    manifest_categories = set(mappings)
    for category in sorted(fixture_categories - manifest_categories):
        errors.append(f"{category}: missing fixture_test_ids entry")
    for category in sorted(manifest_categories - fixture_categories):
        errors.append(f"{category}: stale fixture_test_ids entry")
    for category in sorted(fixture_categories & manifest_categories):
        by_language = mappings[category]
        if not isinstance(by_language, dict):
            errors.append(f"{category}: mapping must be an object")
            continue
        for language in REQUIRED_LANGUAGES:
            identifier = by_language.get(language)
            if not isinstance(identifier, str) or not identifier:
                errors.append(f"{category}:{language}: missing test ID")
            elif identifier not in discovered[language] and not _is_probe(identifier):
                errors.append(f"{category}:{language}: unresolved test ID {identifier!r}")
        extra = set(by_language) - set(REQUIRED_LANGUAGES)
        if extra:
            errors.append(f"{category}: unknown languages {sorted(extra)}")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        print("Fixture test-ID gate failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    categories = len(yaml.safe_load((ROOT / "spec" / "behavioral_fixtures.yaml").read_text(encoding="utf-8")))
    print(f"Fixture test-ID gate passed: {categories} categories x {len(REQUIRED_LANGUAGES)} languages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
