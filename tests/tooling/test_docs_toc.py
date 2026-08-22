# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""The API reference's hand-written contents list must match its sections.

A table of contents is only worth having if it cannot rot. This asserts that
``docs/guide/api.md`` lists every ``##`` section, in order, with the anchor
GitHub will generate — so adding a section without listing it fails here rather
than leaving a reader to scroll for something the contents claims is absent.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.tooling


def _project_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "VERSION").exists():
            return parent
    raise FileNotFoundError("Could not locate project root (no VERSION file found)")


_DOC = _project_root() / "docs" / "guide" / "api.md"

if not _DOC.exists():  # pragma: no cover - docs/ is absent in the mutmut sandbox
    pytest.skip("docs/ not available in this test runtime", allow_module_level=True)

_TOC_ENTRY = re.compile(r"^- \[(?P<title>[^\]]+)\]\(#(?P<anchor>[^)]+)\)$")


def _github_anchor(title: str) -> str:
    """Slugify a heading the way GitHub does for in-page links."""
    lowered = re.sub(r"[^\w\s-]", "", title.strip().lower())
    return re.sub(r"\s+", "-", lowered)


def _sections_and_toc() -> tuple[list[str], list[tuple[str, str]]]:
    sections: list[str] = []
    toc: list[tuple[str, str]] = []
    in_fence = False
    in_toc = False
    for line in _DOC.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.startswith("## "):
            heading = line[3:].strip()
            in_toc = heading == "Contents"
            if not in_toc:
                sections.append(heading)
            continue
        if in_toc:
            match = _TOC_ENTRY.match(line)
            if match:
                toc.append((match["title"], match["anchor"]))
    return sections, toc


def test_contents_lists_every_section_in_order() -> None:
    sections, toc = _sections_and_toc()
    assert [title for title, _ in toc] == sections


def test_contents_anchors_match_github_slugs() -> None:
    _, toc = _sections_and_toc()
    assert [anchor for _, anchor in toc] == [_github_anchor(title) for title, _ in toc]


def test_contents_is_not_empty() -> None:
    """A parser bug that found nothing would make both assertions above vacuous."""
    sections, toc = _sections_and_toc()
    assert len(toc) >= 15
    assert len(sections) == len(toc)
