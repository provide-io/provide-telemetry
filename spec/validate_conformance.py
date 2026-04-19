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
import re
import sys
from collections.abc import Callable
from pathlib import Path

# Allow `spec/` to import siblings whether invoked as a script or imported as a module.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _conformance_extractors import (
    get_go_exports as _ext_get_go_exports,
)
from _conformance_extractors import (
    get_python_exports as _ext_get_python_exports,
)
from _conformance_extractors import (
    get_rust_exports as _ext_get_rust_exports,
)
from _conformance_extractors import (
    get_typescript_exports as _ext_get_typescript_exports,
)

try:
    import yaml  # type: ignore[import-untyped]

    _YAML_AVAILABLE = True
except ImportError:
    yaml = None
    _YAML_AVAILABLE = False

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SPEC_PATH = _REPO_ROOT / "spec" / "telemetry-api.yaml"


# Wrapper functions thread the module-level _REPO_ROOT through to the
# extractors. Tests can monkey-patch this module's _REPO_ROOT and the change
# will flow through these wrappers (the underlying extractors take repo_root
# as an argument now that they live in a sibling module).
def _get_python_exports() -> dict[str, str]:
    return _ext_get_python_exports(_REPO_ROOT)


def _get_go_exports() -> dict[str, str]:
    return _ext_get_go_exports(_REPO_ROOT)


def _get_rust_exports() -> dict[str, str]:
    return _ext_get_rust_exports(_REPO_ROOT)


def _get_typescript_exports() -> dict[str, str]:
    return _ext_get_typescript_exports(_REPO_ROOT)


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


_GO_ACRONYMS: dict[str, str] = {
    "id": "ID",
    "pii": "PII",
    "w3c": "W3C",
    "url": "URL",
    "uri": "URI",
    "api": "API",
    "http": "HTTP",
    "json": "JSON",
    "xml": "XML",
}


def _to_pascal_case(snake: str) -> str:
    """Convert snake_case or lowercase identifier to PascalCase for Go.

    Names that contain no underscores and already have uppercase letters are
    assumed to be PascalCase (e.g. ``TelemetryError``) and returned unchanged.

    Go acronyms (ID, PII, W3C, URL, etc.) are uppercased rather than
    title-cased so that the output matches idiomatic Go naming.
    """
    if "_" not in snake and any(c.isupper() for c in snake):
        return snake
    parts = snake.split("_")
    return "".join(_GO_ACRONYMS.get(p.lower(), p.capitalize()) for p in parts)


def _parse_language_overrides_fallback(text: str) -> dict[str, list[dict[str, object]]]:
    """Parse the language_overrides block from raw YAML text without PyYAML."""
    overrides: dict[str, list[dict[str, object]]] = {}
    in_lo = False
    current_lang: str | None = None
    current_entry: dict[str, object] | None = None

    for line in text.splitlines():
        stripped = line.rstrip()
        if stripped == "language_overrides:":
            in_lo = True
            continue
        if not in_lo:
            continue
        # End of section: new top-level key (no leading spaces)
        if stripped and not stripped.startswith(" "):
            break
        # Language key: exactly 2 spaces + identifier + colon
        m = re.match(r"  (\w+):\s*$", stripped)
        if m:
            current_lang = m.group(1)
            overrides[current_lang] = []
            current_entry = None
            continue
        # List entry starting with spec_name
        m = re.match(r"    - spec_name:\s+(\S+)", stripped)
        if m and current_lang is not None:
            current_entry = {"spec_name": m.group(1), "accepted_kinds": []}
            overrides[current_lang].append(current_entry)
            continue
        # accepted_kinds line
        m = re.match(r"\s+accepted_kinds:\s+\[([^\]]+)\]", stripped)
        if m and current_entry is not None:
            current_entry["accepted_kinds"] = [k.strip() for k in m.group(1).split(",")]

    return overrides


def _load_spec(path: Path | None = None) -> dict[str, object]:
    """Load the YAML spec. Uses PyYAML if available, else a regex-based fallback."""
    text = (path or _SPEC_PATH).read_text(encoding="utf-8")
    if _YAML_AVAILABLE:
        result: dict[str, object] = yaml.safe_load(text)
        return result

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
    return {"api_entries": names, "language_overrides": _parse_language_overrides_fallback(text)}


def _collect_spec_symbols(spec: dict[str, object]) -> list[dict[str, object]]:
    """Flatten the spec API categories into a list of symbol dicts."""
    api = spec.get("api")
    if api is None:
        raw = spec.get("api_entries", [])
        return raw if isinstance(raw, list) else []
    symbols: list[dict[str, object]] = []
    if isinstance(api, dict):
        for _category, entries in api.items():
            if isinstance(entries, list):
                symbols.extend(e for e in entries if isinstance(e, dict))
    return symbols


# ---------------------------------------------------------------------------
# Per-language kind-aware export parsers live in spec/_conformance_extractors.py
# (split out to keep this script under 500 LOC). They return
# dict[exported_name, kind] where kind ∈ {function, instance, type, decorator}.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Kind overrides are now stored in spec/telemetry-api.yaml under
# language_overrides: rather than hardcoded here.
# Use _build_kind_overrides() to read them at runtime.
# ---------------------------------------------------------------------------


def _build_kind_overrides(
    spec: dict[str, object],
    symbols: list[dict[str, object]],
    transform: Callable[[str], str],
    lang: str,
) -> dict[tuple[str, str], set[str]]:
    """Build a (exported_name, spec_kind) → accepted_kinds map from spec YAML.

    Reads spec["language_overrides"][lang] and resolves spec_kind by looking up
    each spec_name in *symbols*.  The transform converts spec names to the
    language-specific exported name (e.g. snake_case → PascalCase for Go).
    """
    overrides_raw = spec.get("language_overrides")
    if not isinstance(overrides_raw, dict):
        return {}
    lang_entries = overrides_raw.get(lang)
    if not isinstance(lang_entries, list):
        return {}

    # Build a quick lookup: spec_name → spec_kind
    spec_kind_map: dict[str, str] = {}
    for sym in symbols:
        if isinstance(sym, dict):
            name = sym.get("name")
            kind = sym.get("kind")
            if isinstance(name, str) and isinstance(kind, str):
                spec_kind_map[name] = kind

    result: dict[tuple[str, str], set[str]] = {}
    for entry in lang_entries:
        if not isinstance(entry, dict):
            continue
        spec_name = entry.get("spec_name")
        accepted_raw = entry.get("accepted_kinds")
        if not isinstance(spec_name, str) or not isinstance(accepted_raw, list):
            continue
        spec_kind = spec_kind_map.get(spec_name)
        if spec_kind is None:
            continue
        exported_name = transform(spec_name)
        accepted: set[str] = {k for k in accepted_raw if isinstance(k, str)}
        result[(exported_name, spec_kind)] = accepted
    return result


# ---------------------------------------------------------------------------
# Capability gates
# ---------------------------------------------------------------------------

# Languages that always advertise the governance capability.
# Python, TypeScript, and Go ship governance as a first-class module.
# Rust ships governance under the `governance` cargo feature which is included
# in the default feature set (default = ["governance"] in Cargo.toml), so it
# is treated as always-present here unless the checker is extended to support
# feature-stripped builds.
_GOVERNANCE_LANGUAGES: frozenset[str] = frozenset({"python", "typescript", "go", "rust"})


def _language_has_capability(lang: str, capability: str) -> bool:
    """Return True if *lang* is expected to export symbols gated on *capability*."""
    if capability == "governance":
        return lang in _GOVERNANCE_LANGUAGES
    return False


def _check_language(
    lang: str,
    symbols: list[dict[str, object]],
    spec: dict[str, object],
) -> tuple[list[str], list[str]]:
    """Check one language. Returns (errors, kind_notes).

    errors: missing required symbols or undocumented kind mismatches (exit code 1)
    kind_notes: kind mismatches that are documented deviations in the spec YAML (notes only)

    A symbol is checked when:
      - required: true  (always checked), OR
      - capability: <cap> AND the language advertises that capability
    """
    exports: dict[str, str]
    transform: Callable[[str], str]
    if lang == "python":
        exports = _get_python_exports()
        transform = _identity
    elif lang == "rust":
        exports = _get_rust_exports()
        transform = _identity
    elif lang == "typescript":
        exports = _get_typescript_exports()
        transform = _to_camel_case
    elif lang == "go":
        exports = _get_go_exports()
        transform = _to_pascal_case
    else:
        return [f"Language '{lang}' is not yet supported by the conformance checker."], []

    lang_overrides = _build_kind_overrides(spec, symbols, transform, lang)
    errors: list[str] = []
    kind_notes: list[str] = []

    for sym in symbols:
        required = bool(sym.get("required", False))
        capability = sym.get("capability")
        capability_active = isinstance(capability, str) and _language_has_capability(lang, capability)

        if not required and not capability_active:
            continue

        spec_name = str(sym["name"])
        spec_kind = str(sym.get("kind", "function"))
        expected = transform(spec_name)

        if expected not in exports:
            if required:
                errors.append(f"  MISSING: {lang} does not export '{expected}' (spec: {spec_name})")
            else:
                # capability-gated only: missing governance export is an error
                errors.append(
                    f"  MISSING [governance]: {lang} does not export '{expected}'"
                    f" (spec: {spec_name}, capability: {capability})"
                )
            continue

        actual_kind = exports[expected]
        if actual_kind == spec_kind:
            continue  # exact match — no note needed

        # Check overrides: acceptable if the actual kind is in the allowed set
        override_key = (expected, spec_kind)
        allowed = lang_overrides.get(override_key)
        if allowed is not None and actual_kind in allowed:
            # Documented idiomatic deviation — record as a note, not an error
            kind_notes.append(
                f"  {expected}: spec={spec_kind}, exported as={actual_kind} [idiomatic deviation — intentional]"
            )
        else:
            # Undocumented kind mismatch — error (not in language_overrides allowlist)
            errors.append(
                f"  KIND MISMATCH: {lang} exports '{expected}' as {actual_kind!r},"
                f" spec expects {spec_kind!r} (spec: {spec_name})"
                f" — add to language_overrides in telemetry-api.yaml if intentional"
            )

    return errors, kind_notes


def main() -> int:
    """Run conformance checks. Returns 0 on success, 1 on failure."""
    parser = argparse.ArgumentParser(description="Validate API conformance against spec.")
    parser.add_argument("--lang", choices=["python", "rust", "typescript", "go"], action="append", default=None)
    parser.add_argument("--spec", type=Path, default=None, help="Path to spec YAML (default: spec/telemetry-api.yaml)")
    args = parser.parse_args()

    spec = _load_spec(args.spec)
    symbols = _collect_spec_symbols(spec)

    langs = args.lang or ["python", "rust", "typescript", "go"]
    all_errors: list[str] = []

    for lang in langs:
        print(f"Checking {lang}...")
        errors, kind_notes = _check_language(lang, symbols, spec)
        if errors:
            all_errors.extend(errors)
            print(f"  {len(errors)} missing symbols")
        else:
            print("  OK — all required symbols present")
        if kind_notes:
            print("  KIND NOTES (idiomatic deviations, not errors):")
            for note in kind_notes:
                print(note)

    if all_errors:
        print(f"\nFAILED — {len(all_errors)} conformance errors:")
        for err in all_errors:
            print(err)
        return 1

    print("\nPASSED — all languages conform to spec.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
