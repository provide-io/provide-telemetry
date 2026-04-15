#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO_ROOT / "spec" / "telemetry-api.yaml"

# Files that contain marker comments for generated tables.
TARGET_FILES: dict[str, Path] = {
    "configuration": REPO_ROOT / "docs" / "CONFIGURATION.md",
    "typescript": REPO_ROOT / "typescript" / "README.md",
}

# Sections included in the typescript_summary combined table.
TS_SUMMARY_SECTIONS = ("core", "logging", "tracing", "otlp")

BEGIN_MARKER = "<!-- BEGIN GENERATED CONFIG: {} -->"
END_MARKER = "<!-- END GENERATED CONFIG: {} -->"
MARKER_RE = re.compile(
    r"(<!-- BEGIN GENERATED CONFIG: (\S+) -->)\n"
    r"(.*?)"
    r"(<!-- END GENERATED CONFIG: \2 -->)",
    re.DOTALL,
)


def load_config_defaults(path: Path) -> dict[str, list[dict[str, str]]]:
    """Load config_defaults from the spec YAML."""
    with path.open() as fh:
        spec: dict[str, Any] = yaml.safe_load(fh)
    defaults: dict[str, list[dict[str, str]]] | None = spec.get("config_defaults")
    if defaults is None:
        print("ERROR: config_defaults not found in spec", file=sys.stderr)
        sys.exit(1)
    return defaults


def render_table(vars_list: list[dict[str, str]]) -> str:
    """Render a list of var dicts as a markdown table."""
    lines = [
        "| Variable | Type | Default | Description |",
        "|----------|------|---------|-------------|",
    ]
    for var in vars_list:
        env = var["env"]
        typ = var["type"]
        default = var["default"]
        desc = var["description"]
        # Format default: wrap non-empty/non-None in backticks
        default_fmt = (default if default == "None" else '`""`') if default in ("", "None") else f"`{default}`"
        lines.append(f"| `{env}` | {typ} | {default_fmt} | {desc} |")
    return "\n".join(lines) + "\n"


def render_ts_table(
    defaults: dict[str, list[dict[str, str]]],
) -> str:
    """Render a combined table for the TypeScript README.

    Uses the same vars that appear in the current TS README: core identity,
    log level/format, trace enabled, and all OTLP vars.
    """
    ts_vars: list[dict[str, str]] = []
    for section in TS_SUMMARY_SECTIONS:
        if section in defaults:
            ts_vars.extend(defaults[section])
    lines = [
        "| Env var | Default | Description |",
        "|---------|---------|-------------|",
    ]
    for var in ts_vars:
        env = var["env"]
        default = var["default"]
        desc = var["description"]
        default_cell = ("\u2014" if default == "None" else '`""`') if default in ("", "None") else f"`{default}`"
        lines.append(f"| `{env}` | {default_cell} | {desc} |")
    return "\n".join(lines) + "\n"


def replace_markers(content: str, section: str, table: str) -> str:
    """Replace content between BEGIN/END markers for *section*."""
    begin = BEGIN_MARKER.format(section)
    end = END_MARKER.format(section)
    pattern = re.compile(
        re.escape(begin) + r"\n" + r"(.*?)" + re.escape(end),
        re.DOTALL,
    )
    replacement = f"{begin}\n{table}{end}"
    new_content, count = pattern.subn(replacement, content)
    if count == 0:
        print(f"  WARNING: markers for '{section}' not found", file=sys.stderr)
    return new_content


def process_configuration_md(
    defaults: dict[str, list[dict[str, str]]],
    path: Path,
    *,
    check: bool,
) -> bool:
    """Update docs/CONFIGURATION.md. Returns True if content changed."""
    content = path.read_text()
    updated = content
    for section, vars_list in defaults.items():
        table = render_table(vars_list)
        updated = replace_markers(updated, section, table)
    changed = updated != content
    if changed and not check:
        path.write_text(updated)
    return changed


def process_typescript_readme(
    defaults: dict[str, list[dict[str, str]]],
    path: Path,
    *,
    check: bool,
) -> bool:
    """Update typescript/README.md. Returns True if content changed."""
    content = path.read_text()
    table = render_ts_table(defaults)
    updated = replace_markers(content, "typescript_summary", table)
    changed = updated != content
    if changed and not check:
        path.write_text(updated)
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate config doc tables from spec/telemetry-api.yaml",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if any file would change (CI mode)",
    )
    args = parser.parse_args()

    defaults = load_config_defaults(SPEC_PATH)
    any_changed = False

    # docs/CONFIGURATION.md
    cfg_path = TARGET_FILES["configuration"]
    if cfg_path.exists():
        print(f"Processing {cfg_path.relative_to(REPO_ROOT)}")
        changed = process_configuration_md(defaults, cfg_path, check=args.check)
        if changed:
            any_changed = True
            label = "would change" if args.check else "updated"
            print(f"  {label}")
        else:
            print("  up to date")
    else:
        print(f"WARNING: {cfg_path} not found, skipping", file=sys.stderr)

    # typescript/README.md
    ts_path = TARGET_FILES["typescript"]
    if ts_path.exists():
        print(f"Processing {ts_path.relative_to(REPO_ROOT)}")
        changed = process_typescript_readme(defaults, ts_path, check=args.check)
        if changed:
            any_changed = True
            label = "would change" if args.check else "updated"
            print(f"  {label}")
        else:
            print("  up to date")
    else:
        print(f"WARNING: {ts_path} not found, skipping", file=sys.stderr)

    if args.check and any_changed:
        print(
            "\nConfig docs are out of date. Run: uv run python scripts/generate_config_docs.py",
            file=sys.stderr,
        )
        sys.exit(1)

    if not args.check and any_changed:
        print("\nDone — files updated.")
    elif not any_changed:
        print("\nAll files up to date.")


if __name__ == "__main__":
    main()
