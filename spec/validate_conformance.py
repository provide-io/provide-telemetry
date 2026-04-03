#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Validate language implementations against spec/telemetry-api.yaml.

Usage:
    python spec/validate_conformance.py                # check all available languages
    python spec/validate_conformance.py --lang python   # check one language

Exit code 0 if all checked languages conform, 1 otherwise.
"""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:
    yaml = None  # type: ignore[assignment]

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SPEC_PATH = _REPO_ROOT / "spec" / "telemetry-api.yaml"


def _identity(name: str) -> str:
    """Return the name unchanged (identity transform for Python exports)."""
    return name


def _to_camel_case(snake: str) -> str:
    """Convert snake_case to camelCase, preserving PascalCase names unchanged."""
    if "_" not in snake:
        return snake
    parts = snake.split("_")
    if snake[0].isupper():
        return "".join(p.capitalize() for p in parts)
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _to_pascal_case(snake: str) -> str:
    """Convert snake_case to PascalCase, preserving already-PascalCase names unchanged."""
    if "_" not in snake:
        return snake
    return "".join(p.capitalize() for p in snake.split("_"))


def _load_spec(path: Path | None = None) -> dict[str, object]:
    """Load the YAML spec. Uses PyYAML if available, else a regex-based fallback."""
    text = (path or _SPEC_PATH).read_text(encoding="utf-8")
    if yaml is not None:
        return yaml.safe_load(text)  # type: ignore[no-any-return]

    names: list[dict[str, object]] = []
    for match in re.finditer(
        r"-\s+name:\s+(\S+)\s*\n\s+kind:\s+(\S+)\s*\n\s+required:\s+(true|false)",
        text,
    ):
        names.append(
            {
                "name": match.group(1),
                "kind": match.group(2),
                "required": match.group(3) == "true",
            }
        )
    return {"api_entries": names}


def _collect_spec_symbols(spec: dict[str, object]) -> list[dict[str, object]]:
    """Flatten the spec API categories into a list of symbol dicts."""
    api = spec.get("api")
    if api is None:
        return spec.get("api_entries", [])  # type: ignore[return-value]
    symbols: list[dict[str, object]] = []
    for _category, entries in api.items():  # type: ignore[union-attr]
        if isinstance(entries, list):
            symbols.extend(entries)
    return symbols


def _get_python_exports() -> set[str]:
    """Parse Python __all__ from __init__.py without importing."""
    init_path = _REPO_ROOT / "src" / "provide" / "telemetry" / "__init__.py"
    if not init_path.exists():
        return set()
    tree = ast.parse(init_path.read_text(encoding="utf-8"))
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__" and isinstance(node.value, ast.List):
                    return {
                        elt.value
                        for elt in node.value.elts
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                    }
    return set()


def _get_go_exports() -> set[str]:
    """Parse exported symbol names from go/telemetry.go via regex."""
    facade_path = _REPO_ROOT / "go" / "telemetry.go"
    if not facade_path.exists():
        return set()
    text = facade_path.read_text(encoding="utf-8")
    exports: set[str] = set()
    for pattern in (
        r"^func ([A-Z][A-Za-z0-9]*)",
        r"^var ([A-Z][A-Za-z0-9]*)",
        r"^type ([A-Z][A-Za-z0-9]*)",
    ):
        for match in re.finditer(pattern, text, re.MULTILINE):
            exports.add(match.group(1))
    return exports


def _get_typescript_exports() -> set[str]:
    """Parse TypeScript export names from index.ts via regex."""
    index_path = _REPO_ROOT / "typescript" / "src" / "index.ts"
    if not index_path.exists():
        return set()
    text = index_path.read_text(encoding="utf-8")
    exports: set[str] = set()
    for block in re.finditer(r"export\s+(?:type\s+)?\{([^}]+)\}", text):
        for item in re.split(r"\s*,\s*", block.group(1).strip()):
            if not item:
                continue
            if " as " in item:
                alias = item.split(" as ")[1].strip()
                exports.add(alias)
            else:
                exports.add(item)
    return exports


def _check_language(
    lang: str,
    symbols: list[dict[str, object]],
) -> list[str]:
    """Check one language. Returns list of error messages."""
    if lang == "python":
        exports = _get_python_exports()
        transform = _identity
    elif lang == "typescript":
        exports = _get_typescript_exports()
        transform = _to_camel_case
    elif lang == "go":
        exports = _get_go_exports()
        transform = _to_pascal_case
    else:
        return [f"Language '{lang}' is not yet supported by the conformance checker."]

    errors: list[str] = []
    for sym in symbols:
        if not sym.get("required", False):
            continue
        spec_name = str(sym["name"])
        expected = transform(spec_name)
        if expected not in exports:
            errors.append(f"  MISSING: {lang} does not export '{expected}' (spec: {spec_name})")
    return errors


def main() -> int:
    """Run conformance checks. Returns 0 on success, 1 on failure."""
    parser = argparse.ArgumentParser(description="Validate API conformance against spec.")
    parser.add_argument("--lang", choices=["python", "typescript", "go"], action="append", default=None)
    parser.add_argument("--spec", type=Path, default=None, help="Path to spec YAML (default: spec/telemetry-api.yaml)")
    args = parser.parse_args()

    spec = _load_spec(args.spec)
    symbols = _collect_spec_symbols(spec)

    langs = args.lang or ["python", "typescript"]
    all_errors: list[str] = []

    for lang in langs:
        print(f"Checking {lang}...")
        errors = _check_language(lang, symbols)
        if errors:
            all_errors.extend(errors)
            print(f"  {len(errors)} missing symbols")
        else:
            print("  OK — all required symbols present")

    if all_errors:
        print(f"\nFAILED — {len(all_errors)} conformance errors:")
        for err in all_errors:
            print(err)
        return 1

    print("\nPASSED — all languages conform to spec.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
