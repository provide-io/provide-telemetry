# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

from pathlib import Path

SPDX_COPYRIGHT = "# SPDX-FileCopyrightText" + ": Copyright (C) 2026 provide.io llc\n"
SPDX_LICENSE = "# SPDX-License-Identifier" + ": Apache-2.0\n"
SPDX_COMMENT = "# SPDX-Comment" + ": Part of provide-telemetry.\n"
SPDX_SEPARATOR = "#\n"
SPDX_BLANK = "\n"

CANONICAL_BLOCK = (
    SPDX_COPYRIGHT,
    SPDX_LICENSE,
    SPDX_COMMENT,
    SPDX_SEPARATOR,
    SPDX_BLANK,
)

GO_COPYRIGHT = "// SPDX-FileCopyrightText" + ": Copyright (C) 2026 provide.io llc\n"
GO_LICENSE = "// SPDX-License-Identifier" + ": Apache-2.0\n"
GO_CANONICAL_BLOCK = (GO_COPYRIGHT, GO_LICENSE)


def has_go_canonical_header(text: str) -> bool:
    lines = text.splitlines(keepends=True)
    if len(lines) < 2:
        return False
    return lines[0] == GO_COPYRIGHT and lines[1] == GO_LICENSE


EXCLUDED_DIRS = {
    ".git",
    ".provide",
    ".venv",
    "workenv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".hypothesis",
    "mutants",
    "dist",
    "build",
    "node_modules",
    "__pycache__",
}


def find_python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*.py"):
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        files.append(path)
    return sorted(files)


def split_shebang(text: str) -> tuple[str, str]:
    if text.startswith("#!"):
        line_end = text.find("\n")
        if line_end == -1:
            return text + "\n", ""
        return text[: line_end + 1], text[line_end + 1 :]
    return "", text


def strip_leading_comment_block(text: str) -> str:
    """Drop an existing SPDX header so the canonical block can replace it.

    The whole leading comment block goes, so a legacy header in some other
    format is replaced rather than left to sit under the canonical one -- with
    one exception. A "# REUSE-" directive is body, not header: swallowing a
    "# REUSE-IgnoreStart" leaves its matching "REUSE-IgnoreEnd" orphaned and
    the file stops being REUSE-compliant, so the script that the SPDX lint
    error tells you to run could break the very compliance it maintains.
    Observed on scripts/check_spdx_headers.py, 2026-08-16.
    """
    lines = text.splitlines(keepends=True)
    idx = 0
    while idx < len(lines):
        stripped = lines[idx].strip()
        if stripped.startswith("# REUSE-"):
            # A REUSE directive is body, not header. Consuming it leaves its
            # partner orphaned and breaks compliance -- see the docstring.
            break
        if stripped.startswith("#") or stripped == "":
            idx += 1
            continue
        break
    while idx < len(lines) and lines[idx].strip() == "":
        idx += 1
    return "".join(lines[idx:])


def normalize_python_text(text: str) -> str:
    shebang, rest = split_shebang(text)
    body = strip_leading_comment_block(rest)
    return shebang + "".join(CANONICAL_BLOCK) + body


def has_canonical_header(text: str) -> bool:
    _, rest = split_shebang(text)
    lines = rest.splitlines(keepends=True)
    if len(lines) < len(CANONICAL_BLOCK):
        return False
    return tuple(lines[: len(CANONICAL_BLOCK)]) == CANONICAL_BLOCK
