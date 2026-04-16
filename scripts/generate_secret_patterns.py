#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Generate secret detection pattern source files from spec/secret_patterns.yaml.

Usage:
  uv run python scripts/generate_secret_patterns.py          # update files in-place
  uv run python scripts/generate_secret_patterns.py --check  # CI mode: exit 1 if stale
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO_ROOT / "spec" / "secret_patterns.yaml"

# ── Target files ─────────────────────────────────────────────────────────────

TARGETS: dict[str, Path] = {
    "python": REPO_ROOT / "src" / "provide" / "telemetry" / "_secret_patterns_generated.py",
    "typescript": REPO_ROOT / "typescript" / "src" / "secret-patterns-generated.ts",
    "go": REPO_ROOT / "go" / "internal" / "piicore" / "secret_patterns_generated.go",
    "rust": REPO_ROOT / "rust" / "src" / "secret_patterns_generated.rs",
}


def load_spec() -> dict:
    return yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))


# ── Generators ───────────────────────────────────────────────────────────────
# REUSE-IgnoreStart — string literals below contain SPDX headers for generated files


def generate_python(spec: dict) -> str:
    lines = [
        "# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc",
        "# SPDX-License-Identifier: Apache-2.0",
        "# SPDX-Comment: Part of provide-telemetry.",
        "#",
        "",
        '"""Auto-generated from spec/secret_patterns.yaml — do not edit."""',
        "",
        "from __future__ import annotations",
        "",
        f"MIN_SECRET_LENGTH: int = {spec['min_secret_length']}",
        "",
        "PATTERNS: tuple[tuple[str, str], ...] = (",
    ]
    for p in spec["patterns"]:
        lines.append(f'    ("{p["name"]}", r"{p["regex"]}"),  # {p["description"]}')
    lines.append(")")
    lines.append("")
    return "\n".join(lines)


def generate_typescript(spec: dict) -> str:
    lines = [
        "// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.",
        "// SPDX-License-Identifier: Apache-2.0",
        "",
        "// Auto-generated from spec/secret_patterns.yaml — do not edit.",
        "",
        f"export const MIN_SECRET_LENGTH = {spec['min_secret_length']};",
        "",
        "export const PATTERNS: ReadonlyArray<{ name: string; regex: RegExp }> = [",
    ]
    for p in spec["patterns"]:
        lines.append(f"  {{ name: '{p['name']}', regex: /{p['regex']}/ }}, // {p['description']}")
    lines.append("];")
    lines.append("")
    return "\n".join(lines)


def generate_go(spec: dict) -> str:
    lines = [
        "// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc",
        "// SPDX-License-Identifier: Apache-2.0",
        "",
        "// Code generated from spec/secret_patterns.yaml — DO NOT EDIT.",
        "",
        "package piicore",
        "",
        'import "regexp"',
        "",
        "// MinSecretLength is the minimum string length for secret detection.",
        f"const MinSecretLength = {spec['min_secret_length']} // pragma: allowlist secret",
        "",
        "// generatedSecretPatterns are compiled from spec/secret_patterns.yaml. // pragma: allowlist secret",
        "var generatedSecretPatterns = []*regexp.Regexp{ // pragma: allowlist secret",
    ]
    for p in spec["patterns"]:
        lines.append(f"\tregexp.MustCompile(`{p['regex']}`), // {p['description']}")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def generate_rust(spec: dict) -> str:
    lines = [
        "// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc",
        "// SPDX-License-Identifier: Apache-2.0",
        "// SPDX-Comment: Part of provide-telemetry.",
        "//",
        "// Auto-generated from spec/secret_patterns.yaml — do not edit.",
        "",
        "/// Minimum string length for secret detection.",
        f"pub(crate) const MIN_SECRET_LENGTH: usize = {spec['min_secret_length']};",
        "",
        "/// (name, regex_pattern) pairs for built-in secret detection.",
        "pub(crate) const PATTERNS: &[(&str, &str)] = &[",
    ]
    for p in spec["patterns"]:
        lines.append(f'    ("{p["name"]}", r#"{p["regex"]}"#), // {p["description"]}')
    lines.append("];")
    lines.append("")
    return "\n".join(lines)


# REUSE-IgnoreEnd

GENERATORS = {
    "python": generate_python,
    "typescript": generate_typescript,
    "go": generate_go,
    "rust": generate_rust,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate secret pattern source files")
    parser.add_argument("--check", action="store_true", help="Exit non-zero if any file would change")
    args = parser.parse_args()

    spec = load_spec()
    any_changed = False

    for lang, target in TARGETS.items():
        generated = GENERATORS[lang](spec)
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        if generated != current:
            any_changed = True
            if args.check:
                print(f"  {lang}: {target.relative_to(REPO_ROOT)} would change")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(generated, encoding="utf-8")
                print(f"  {lang}: {target.relative_to(REPO_ROOT)} updated")
        else:
            print(f"  {lang}: up to date")

    if args.check and any_changed:
        print(
            "\nGenerated secret patterns are stale. Run: uv run python scripts/generate_secret_patterns.py",
            file=sys.stderr,
        )
        sys.exit(1)

    if not args.check and any_changed:
        print("\nDone — files updated.")
    elif not any_changed:
        print("\nAll files up to date.")


if __name__ == "__main__":
    main()
