#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Cross-language fixture coverage gate.

For each top-level category in spec/behavioral_fixtures.yaml, checks whether
each language's parity test file(s) mention that category (case-insensitive).
Exits 0 only when every gap is listed in spec/fixture_coverage_accepted_gaps.yaml.
Unaccepted gaps cause exit code 1 so CI fails instead of silently drifting.

To accept a known gap, add an entry to spec/fixture_coverage_accepted_gaps.yaml
with reason, owner, and a required expires_on date.

Usage:
    python spec/check_fixture_coverage.py            # default mode — warns on expired entries
    python spec/check_fixture_coverage.py --strict   # fails on expired entries
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ACCEPTED_GAPS_PATH = _REPO_ROOT / "spec" / "fixture_coverage_accepted_gaps.yaml"

# ---------------------------------------------------------------------------
# Language → parity test file discovery
#
# Each language has:
#   - one or more glob patterns (relative to repo root) that discover parity
#     test files. The globs are the primary source of truth.
#   - optional "extra" paths (e.g. canonical probe files) that always count
#     toward that language's corpus even if they don't match the glob.
#
# If a language's glob yields zero files AND has no extras, the checker fails
# loudly rather than silently treating the language as empty.
# ---------------------------------------------------------------------------

_LANGUAGE_GLOBS: dict[str, list[str]] = {
    "python": ["tests/parity/test_*.py"],
    "typescript": ["typescript/tests/parity*.test.ts", "typescript/tests/endpoint.test.ts"],
    "go": ["go/parity_*_test.go", "go/parity_test.go"],
    "rust": ["rust/tests/parity_*.rs", "rust/tests/parity_test.rs"],
}

# Extras are canonical probe files that contribute to a language's coverage
# corpus. They are always appended if they exist; missing extras are ignored.
_LANGUAGE_EXTRAS: dict[str, list[str]] = {
    "python": [],
    "typescript": ["spec/probes/emit_log_typescript.ts"],
    "go": ["spec/probes/emit_log_go/main.go"],
    "rust": ["rust/src/otel/endpoint.rs"],
}

_CATEGORY_CONTENT_MARKERS: dict[str, tuple[str, ...]] = {
    "log_output_format": ("log.output.parity",),
}


def _discover_language_files(
    repo_root: Path,
    globs: dict[str, list[str]],
    extras: dict[str, list[str]],
) -> dict[str, list[Path]]:
    """Resolve glob + extras for each language into a list of real in-tree files.

    Symlinks and paths that escape the repo are silently filtered out.
    """
    resolved_root = repo_root.resolve()
    result: dict[str, list[Path]] = {}
    for lang, patterns in globs.items():
        files: list[Path] = []
        seen: set[Path] = set()
        for pattern in patterns:
            for match in sorted(repo_root.glob(pattern)):
                candidate = _sanitize_path(match, resolved_root)
                if candidate is None or candidate in seen:
                    continue
                seen.add(candidate)
                files.append(candidate)
        for extra in extras.get(lang, []):
            extra_path = repo_root / extra
            if not extra_path.exists():
                continue
            candidate = _sanitize_path(extra_path, resolved_root)
            if candidate is None or candidate in seen:
                continue
            seen.add(candidate)
            files.append(candidate)
        result[lang] = files
    return result


def _sanitize_path(path: Path, resolved_root: Path) -> Path | None:
    """Return the resolved path iff it is a real file inside the repo root."""
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        return None
    # Reject symlinks — they could escape the tree even if resolve lands inside.
    if path.is_symlink():
        return None
    if not resolved.is_file():
        return None
    try:
        resolved.relative_to(resolved_root)
    except ValueError:
        return None
    return resolved


def _load_categories(fixtures_path: Path) -> list[str]:
    """Return top-level category keys from behavioral_fixtures.yaml."""
    import yaml

    return list(yaml.safe_load(fixtures_path.read_text(encoding="utf-8")).keys())


def _load_accepted_gaps(path: Path) -> tuple[set[tuple[str, str]], list[dict[str, object]], list[str]]:
    """Parse accepted-gaps file.

    Returns (pairs, entries, errors):
      - pairs: set of (lang, category) that are accepted.
      - entries: raw entry dicts (for expiry checks).
      - errors: schema errors (missing/malformed expires_on, etc.).
    """
    if not path.exists():
        return set(), [], []
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return set(), [], []
    entries_raw = data.get("accepted_gaps", [])
    if not isinstance(entries_raw, list):
        return set(), [], []

    pairs: set[tuple[str, str]] = set()
    entries: list[dict[str, object]] = []
    errors: list[str] = []
    for idx, entry in enumerate(entries_raw):
        if not isinstance(entry, dict):
            errors.append(f"entry #{idx}: not a mapping")
            continue
        lang = entry.get("lang")
        cat = entry.get("category")
        if not (isinstance(lang, str) and isinstance(cat, str)):
            errors.append(f"entry #{idx}: lang/category must be strings")
            continue
        expires_on = entry.get("expires_on")
        if expires_on is None:
            errors.append(f"entry #{idx} ({lang}:{cat}): missing required 'expires_on' (YYYY-MM-DD)")
            continue
        if not _is_valid_expires_on(expires_on):
            errors.append(f"entry #{idx} ({lang}:{cat}): 'expires_on' must be a YYYY-MM-DD date, got {expires_on!r}")
            continue
        if not isinstance(entry.get("reason"), str) or not isinstance(entry.get("owner"), str):
            errors.append(f"entry #{idx} ({lang}:{cat}): 'reason' and 'owner' are required strings")
            continue
        pairs.add((lang, cat))
        entries.append(entry)
    return pairs, entries, errors


def _is_valid_expires_on(value: object) -> bool:
    """Return True iff value is (or parses cleanly as) a YYYY-MM-DD date."""
    if isinstance(value, _dt.date) and not isinstance(value, _dt.datetime):
        return True
    if isinstance(value, str):
        try:
            _dt.date.fromisoformat(value)
        except ValueError:
            return False
        return True
    return False


def _as_date(value: object) -> _dt.date | None:
    """Coerce an expires_on value to a date, or return None if invalid."""
    if isinstance(value, _dt.date) and not isinstance(value, _dt.datetime):
        return value
    if isinstance(value, str):
        try:
            return _dt.date.fromisoformat(value)
        except ValueError:
            return None
    return None


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


def _category_search_terms(category: str) -> list[str]:
    """Return all content terms that count as coverage for a category."""
    return list(dict.fromkeys([*_category_variants(category), *_CATEGORY_CONTENT_MARKERS.get(category, ())]))


def _category_mentioned(category: str, corpus: str) -> bool:
    """Return True if any variant of category appears in corpus (case-insensitive)."""
    return any(re.search(re.escape(term), corpus, re.IGNORECASE) for term in _category_search_terms(category))


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


def _report_expiry(entries: list[dict[str, object]], *, strict: bool) -> int:
    """Check expiry dates on accepted-gap entries.

    In default (non-strict) mode, prints warnings to stderr and returns 0.
    In --strict mode, returns 1 if any entry is expired.
    """
    today = _dt.date.today()
    expired: list[tuple[str, str, _dt.date]] = []
    for entry in entries:
        lang = str(entry.get("lang", ""))
        cat = str(entry.get("category", ""))
        exp = _as_date(entry.get("expires_on"))
        if exp is None:
            continue
        if today >= exp:
            expired.append((lang, cat, exp))
    if not expired:
        return 0
    label = "EXPIRED" if strict else "WARNING"
    stream = sys.stderr
    print(f"\n{label} — {len(expired)} accepted-gap entry/entries are expired:", file=stream)
    for lang, cat, exp in sorted(expired):
        print(f"  {lang}:{cat} expired on {exp.isoformat()}", file=stream)
    if strict:
        print("Run with --strict removed, or renew/close the gap.", file=stream)
        return 1
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cross-language fixture coverage gate.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail (exit 1) when any accepted-gap entry has passed its expires_on date.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    fixtures_path = _REPO_ROOT / "spec" / "behavioral_fixtures.yaml"
    if not fixtures_path.exists():
        print(f"ERROR: fixtures not found at {fixtures_path}", file=sys.stderr)
        return 2

    language_files = _discover_language_files(_REPO_ROOT, _LANGUAGE_GLOBS, _LANGUAGE_EXTRAS)

    # Fail loudly if a language that expects parity tests yielded zero files.
    empty: list[str] = []
    for lang, files in language_files.items():
        if not files:
            empty.append(lang)
    if empty:
        for lang in empty:
            patterns = ", ".join(_LANGUAGE_GLOBS.get(lang, []))
            print(
                f"ERROR: no parity test files discovered for '{lang}' (globs: {patterns})",
                file=sys.stderr,
            )
        return 2

    coverage = run_report(fixtures_path, language_files)
    _print_report(coverage)

    accepted, entries, schema_errors = _load_accepted_gaps(_ACCEPTED_GAPS_PATH)
    if schema_errors:
        print("\nFAILED — accepted-gaps file has schema errors:", file=sys.stderr)
        for err in schema_errors:
            print(f"  {err}", file=sys.stderr)
        return 1

    # Collect gaps that are NOT accepted
    unaccepted: list[tuple[str, str]] = []
    for lang, cat_map in coverage.items():
        for cat, covered in cat_map.items():
            if not covered and (lang, cat) not in accepted:
                unaccepted.append((lang, cat))

    if unaccepted:
        print()
        print(f"FAILED — {len(unaccepted)} unaccepted gap(s):")
        for lang, cat in sorted(unaccepted):
            print(f"  {lang}: '{cat}' — add to spec/fixture_coverage_accepted_gaps.yaml with reason+owner+expires_on")
        return 1

    # Warn about accepted entries that are no longer needed (coverage closed)
    stale: list[tuple[str, str]] = []
    for lang, cat in accepted:
        lang_cov = coverage.get(lang, {})
        if lang_cov.get(cat):
            stale.append((lang, cat))
    if stale:
        print()
        print(f"NOTE — {len(stale)} accepted-gap entry/entries are now covered and can be removed:")
        for lang, cat in sorted(stale):
            print(f"  {lang}: '{cat}' is now covered — remove from fixture_coverage_accepted_gaps.yaml")

    return _report_expiry(entries, strict=args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
