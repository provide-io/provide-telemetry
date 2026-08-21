# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""The published Rust and Go quick starts must compile.

Sibling of test_readme_snippets.py, which executes the Python snippets. These
need a cargo and a go toolchain, so they carry the tooling marker and run in
their own CI job rather than in the default suite.

rust/README.md shipped a quick start calling setup_telemetry() and
shutdown_telemetry() with no arguments; both take an Option and return a
Result. Nothing caught it because nothing compiled it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.tooling, pytest.mark.slow]

_REPO_ROOT = Path(os.environ.get("PROVIDE_REPO_ROOT", Path(__file__).resolve().parents[2]))
_FENCE_RE = re.compile(r"^```(?P<lang>[a-zA-Z]+)\n(?P<body>.*?)^```", re.MULTILINE | re.DOTALL)


def extract_snippets(markdown: str, language: str) -> list[str]:
    """Return the bodies of every fenced block tagged with `language`."""
    return [
        match.group("body") for match in _FENCE_RE.finditer(markdown) if match.group("lang").lower() == language.lower()
    ]


def test_extract_snippets_picks_the_requested_language() -> None:
    markdown = "```rust\nfn a() {}\n```\n\n```toml\nx = 1\n```\n"
    assert extract_snippets(markdown, "rust") == ["fn a() {}\n"]
    assert extract_snippets(markdown, "toml") == ["x = 1\n"]


def test_extract_snippets_is_case_insensitive_on_the_tag() -> None:
    assert extract_snippets("```Rust\nfn a() {}\n```\n", "rust") == ["fn a() {}\n"]


def test_extract_snippets_returns_empty_for_an_absent_language() -> None:
    assert extract_snippets("```rust\nfn a() {}\n```\n", "go") == []


def _first_main_snippet(readme: Path, language: str, marker: str) -> str:
    snippets = [s for s in extract_snippets(readme.read_text(encoding="utf-8"), language) if marker in s]
    if not snippets:
        pytest.fail(f"{readme}: no runnable {language} quick start found")
    return snippets[0]


@pytest.mark.skipif(shutil.which("cargo") is None, reason="cargo not installed")
def test_rust_quick_start_compiles(tmp_path: Path) -> None:
    snippet = _first_main_snippet(_REPO_ROOT / "rust" / "README.md", "rust", "fn main")
    crate = tmp_path / "snippet"
    (crate / "src").mkdir(parents=True)
    (crate / "Cargo.toml").write_text(
        "[package]\n"
        'name = "snippet"\n'
        'version = "0.0.0"\n'
        'edition = "2021"\n\n'
        "[workspace]\n\n"
        "[dependencies]\n"
        f'provide-telemetry = {{ path = "{(_REPO_ROOT / "rust").as_posix()}" }}\n'
        # The quick start builds a structured-field map, whose values are
        # serde_json::Value — a consumer following the README needs this too.
        'serde_json = "1"\n'
    )
    (crate / "src" / "main.rs").write_text(snippet)
    result = subprocess.run(["cargo", "build", "--quiet"], cwd=crate, capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"rust/README.md quick start does not compile:\n{result.stderr}"


@pytest.mark.skipif(shutil.which("go") is None, reason="go not installed")
def test_go_quick_start_compiles(tmp_path: Path) -> None:
    snippet = _first_main_snippet(_REPO_ROOT / "go" / "README.md", "go", "func main")
    module = tmp_path / "snippet"
    module.mkdir()
    (module / "main.go").write_text(snippet)
    (module / "go.mod").write_text(
        "module snippet\n\ngo 1.26.0\n\n"
        "require github.com/provide-io/provide-telemetry/go v0.0.0\n\n"
        f"replace github.com/provide-io/provide-telemetry/go => {(_REPO_ROOT / 'go').as_posix()}\n"
    )
    tidy = subprocess.run(["go", "mod", "tidy"], cwd=module, capture_output=True, text=True, check=False)
    assert tidy.returncode == 0, f"go mod tidy failed:\n{tidy.stderr}"
    result = subprocess.run(["go", "build", "./..."], cwd=module, capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"go/README.md quick start does not compile:\n{result.stderr}"
