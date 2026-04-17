#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Cross-language fixture coverage reporter.

For each top-level category in spec/behavioral_fixtures.yaml, checks whether
each language's parity test file(s) mention that category (case-insensitive).
Exits 0 and prints a coverage table — it is a report, not a hard gate.

Usage:
    python spec/check_fixture_coverage.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Language → parity test file paths (relative to repo root)
# ---------------------------------------------------------------------------

_LANGUAGE_FILES: dict[str, list[Path]] = {
    "python": [
        _REPO_ROOT / "tests" / "parity" / "test_behavioral_fixtures.py",
        _REPO_ROOT / "tests" / "parity" / "test_behavioral_fixtures_ext.py",
        _REPO_ROOT / "tests" / "parity" / "test_parity_endpoint_validation.py",
    ],
    "typescript": [
        _REPO_ROOT / "typescript" / "tests" / "parity.test.ts",
        _REPO_ROOT / "typescript" / "tests" / "endpoint.test.ts",
    ],
    "go": [
        _REPO_ROOT / "go" / "parity_test.go",
        _REPO_ROOT / "go" / "parity_backpressure_test.go",
        _REPO_ROOT / "go" / "parity_cardinality_test.go",
        _REPO_ROOT / "go" / "parity_config_test.go",
        _REPO_ROOT / "go" / "parity_health_test.go",
        _REPO_ROOT / "go" / "parity_pii_test.go",
        _REPO_ROOT / "go" / "parity_propagation_test.go",
        _REPO_ROOT / "go" / "parity_sampling_test.go",
        _REPO_ROOT / "go" / "parity_schema_test.go",
        _REPO_ROOT / "go" / "parity_slo_test.go",
        _REPO_ROOT / "go" / "parity_endpoint_test.go",
    ],
    "rust": [
        _REPO_ROOT / "rust" / "tests" / "parity_test.rs",
        _REPO_ROOT / "rust" / "src" / "otel" / "endpoint.rs",
    ],
}


def _load_categories(fixtures_path: Path) -> list[str]:
    """Return top-level category keys from behavioral_fixtures.yaml."""
    import yaml

    return list(yaml.safe_load(fixtures_path.read_text(encoding="utf-8")).keys())


def _read_language_corpus(paths: list[Path]) -> str:
    """Concatenate all existing files for a language into one string."""
    parts: list[str] = []
    for path in paths:
        if path.exists():
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def _category_variants(category: str) -> list[str]:
    """Return case variants of a category name for fuzzy searching.

    E.g. "pii_hash" → ["pii_hash", "piiHash", "PiiHash", "pii-hash"]
    """
    variants = [category]
    # snake_case → camelCase
    words = category.split("_")
    camel = words[0] + "".join(w.capitalize() for w in words[1:])
    pascal = "".join(w.capitalize() for w in words)
    kebab = category.replace("_", "-")
    spaced = category.replace("_", " ")
    variants.extend([camel, pascal, kebab, spaced])
    return list(dict.fromkeys(variants))  # deduplicate while preserving order


def _category_mentioned(category: str, corpus: str) -> bool:
    """Return True if any variant of category appears in corpus (case-insensitive)."""
    return any(re.search(re.escape(variant), corpus, re.IGNORECASE) for variant in _category_variants(category))


def run_report(fixtures_path: Path, language_files: dict[str, list[Path]]) -> dict[str, dict[str, bool]]:
    """Build coverage matrix: {language: {category: covered}}."""
    categories = _load_categories(fixtures_path)
    coverage: dict[str, dict[str, bool]] = {}
    for lang, paths in language_files.items():
        corpus = _read_language_corpus(paths)
        coverage[lang] = {cat: _category_mentioned(cat, corpus) for cat in categories}
    return coverage


def _print_report(coverage: dict[str, dict[str, bool]]) -> None:
    if not coverage:
        print("No languages to check.")
        return

    categories = list(next(iter(coverage.values())).keys())
    languages = list(coverage.keys())

    col_w = max(len(lang) for lang in languages) + 2
    cat_w = max(len(cat) for cat in categories) + 2

    header = f"{'category':<{cat_w}}" + "".join(f"{lang:^{col_w}}" for lang in languages)
    print(header)
    print("-" * len(header))

    gaps: list[tuple[str, str]] = []
    for cat in categories:
        row = f"{cat:<{cat_w}}"
        for lang in languages:
            covered = coverage[lang][cat]
            mark = "OK" if covered else "--"
            row += f"{mark:^{col_w}}"
            if not covered:
                gaps.append((lang, cat))
        print(row)

    print()
    if gaps:
        print(f"Coverage gaps ({len(gaps)}):")
        for lang, cat in gaps:
            print(f"  {lang}: missing '{cat}'")
    else:
        print("All categories mentioned in all language test files.")


def main() -> int:
    fixtures_path = _REPO_ROOT / "spec" / "behavioral_fixtures.yaml"
    if not fixtures_path.exists():
        print(f"ERROR: fixtures not found at {fixtures_path}", file=sys.stderr)
        return 2

    coverage = run_report(fixtures_path, _LANGUAGE_FILES)
    _print_report(coverage)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
