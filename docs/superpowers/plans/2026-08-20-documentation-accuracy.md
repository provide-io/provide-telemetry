# Documentation Accuracy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct every shipped documentation claim the external review found false, widen the documentation checker to cover the language READMEs it currently ignores, and make the primary quick starts executable so a snippet that no longer compiles fails CI.

**Architecture:** Three layers. First, fix the specific false claims — each one has a file, a line, and contradicting evidence. Second, widen `scripts/check_docs_accuracy.py` from three paths to include every shipped language README and contributor guidance, then clear whatever that surfaces. Third, add snippet tests that compile the Rust and Go quick starts, because the Rust quick start is currently wrong in a way no reviewer caught and no checker could catch.

**Tech Stack:** Python 3.11+ for the checker and its tests; `cargo build` and `go build` for snippet execution.

**Spec:** [`docs/superpowers/specs/2026-08-20-external-review-remediation-design.md`](../specs/2026-08-20-external-review-remediation-design.md) (revision 2) — workstream C2.

**Run this plan LAST.** It documents behavior that plans 1, 2, 3, and 5 change. Running it early guarantees rework.

## Global Constraints

- **777 LOC max per file**; **SPDX headers required**; **mypy strict**; **100% branch coverage** and **100% mutation kill** for Python.
- Documentation corrections must match observed behavior, not intended behavior. If a doc and the code disagree, read the code and check which one is wrong before editing either.
- Do not "fix" a doc by loosening a checker. Widening `DOC_PATHS` will surface real violations; fix the documents.
- No hardcoded machine paths in scripts — derive from the script location with an env override.
- Commit messages must not mention AI assistance and must not carry a `Co-Authored-By: Claude` trailer.

## File Structure

- Modify: `go/README.md:13`, `go/README.md:268` — Go version floor.
- Modify: `rust/README.md:16`, `rust/README.md:24-36` — install version and lifecycle signatures.
- Modify: `docs/guide/capability-matrix.md:61-65` — C# OTLP evidence claim.
- Modify: `.github/workflows/ci-spec.yml:49`, `ci-contracts.yml:73`, `:80`, `:116`, `ci-surface.yml:64`, `:68` — stale "four languages".
- Modify: `scripts/check_docs_accuracy.py:11,15,160` — `DOC_PATHS`, mutation-threshold message.
- Create: `tests/tooling/test_check_docs_accuracy_scope.py`.
- Create: `tests/tooling/test_readme_snippets.py` — extracts and compiles the quick starts.

---

### Task 1: Widen the documentation checker's scope

**Files:**
- Modify: `scripts/check_docs_accuracy.py:11`
- Create: `tests/tooling/test_check_docs_accuracy_scope.py`

**Interfaces:**
- Consumes: `check_docs_accuracy._iter_markdown_files(root: Path) -> list[Path]`, `DOC_PATHS`.
- Produces: a `DOC_PATHS` that includes every shipped language README and `CONTRIBUTING.md`.

`DOC_PATHS = ("README.md", "docs", "examples/README.md")` today. Every language
README — the documents a package consumer actually reads first — is outside it,
which is exactly why `rust/README.md` can ship a snippet that does not compile.

- [ ] **Step 1: Write the failing scope test**

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Every shipped README must be inside the documentation checker's scope."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_docs_accuracy import _iter_markdown_files

pytestmark = pytest.mark.tooling

_REPO_ROOT = Path(__file__).resolve().parents[2]

_SHIPPED_READMES = (
    "README.md",
    "go/README.md",
    "rust/README.md",
    "typescript/README.md",
    "csharp/README.md",
    "examples/README.md",
    "CONTRIBUTING.md",
)


@pytest.mark.parametrize("relative", _SHIPPED_READMES)
def test_shipped_document_is_checked(relative: str) -> None:
    target = _REPO_ROOT / relative
    if not target.is_file():
        pytest.skip(f"{relative} does not exist in this repository")
    checked = {path.resolve() for path in _iter_markdown_files(_REPO_ROOT)}
    assert target.resolve() in checked, f"{relative} is shipped but not checked"
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run python scripts/run_pytest_gate.py --no-cov -q tests/tooling/test_check_docs_accuracy_scope.py`
Expected: FAIL for `go/README.md`, `rust/README.md`, `typescript/README.md`,
`csharp/README.md`, and `CONTRIBUTING.md` (if it exists).

- [ ] **Step 3: Widen `DOC_PATHS`**

```python
# Every document a package consumer or contributor reads. The language READMEs
# were outside this list until 2026-08-20, which is how rust/README.md came to
# ship a quick start that does not compile — see tests/tooling/test_readme_snippets.py.
DOC_PATHS = (
    "README.md",
    "CONTRIBUTING.md",
    "docs",
    "examples/README.md",
    "go/README.md",
    "rust/README.md",
    "typescript/README.md",
    "csharp/README.md",
)
```

`_iter_markdown_files` already skips entries that do not exist, so a missing
`CONTRIBUTING.md` is harmless.

- [ ] **Step 4: Run the scope test**

Run: `uv run python scripts/run_pytest_gate.py --no-cov -q tests/tooling/test_check_docs_accuracy_scope.py`
Expected: PASS.

- [ ] **Step 5: See what the wider scope surfaces**

Run: `uv run python scripts/check_docs_accuracy.py`
Expected: FAIL, listing style and link violations in the newly-included files —
trailing whitespace, heading-level jumps, missing link targets, a first line that
is not an H1.

**Triage every violation before fixing any of them.** For each, decide: is the
document wrong, or is the rule wrong for this document? Fix documents. If a rule
genuinely does not fit a language README, record why in the checklist and raise
it — do not silently exempt the file.

- [ ] **Step 6: Fix them**

Work through the list until `uv run python scripts/check_docs_accuracy.py` exits 0.
Keep these edits mechanical — whitespace, heading levels, broken relative links.
Content corrections belong to Tasks 2–5, not here.

- [ ] **Step 7: Commit**

```bash
git add scripts/check_docs_accuracy.py tests/tooling/test_check_docs_accuracy_scope.py go/README.md rust/README.md typescript/README.md csharp/README.md
git commit -m "test(docs): check every shipped README

The language READMEs — the first documents a package consumer reads — were
outside the checker's scope entirely."
```

---

### Task 2: Correct the Go version floor

**Files:**
- Modify: `go/README.md:13`, `go/README.md:268`

- [ ] **Step 1: Confirm the real floor**

Run: `grep -n "^go " go/go.mod go/otel/go.mod`
Expected: both print `go 1.26.0`.

- [ ] **Step 2: Correct both claims**

`go/README.md:13` says `Requires Go 1.22+.` and `:268` repeats `- Go 1.22+`.
Replace both with the floor the modules actually declare:

```markdown
Requires Go 1.26+.
```

Do not write `1.26.0+` in prose — the module directive carries the patch, the
README states the language version. Check whether any other file repeats the
claim: `grep -rn "Go 1\.2[0-9]" --include='*.md' .`

- [ ] **Step 3: Verify**

Run: `grep -rn "Go 1\.2[0-5]" --include='*.md' . && echo "STALE CLAIMS REMAIN" || echo "clean"`
Expected: `clean`.

- [ ] **Step 4: Commit**

```bash
git add go/README.md
git commit -m "docs(go): state the Go 1.26 floor the modules declare"
```

---

### Task 3: Correct the Rust install version and lifecycle signatures

**Files:**
- Modify: `rust/README.md:13-16`, `rust/README.md:24-36`, `rust/README.md:46-50`

The install line pins `provide-telemetry = "0.3"` while `rust/Cargo.toml:7` and
`VERSION` are both `0.8.0`. Worse, the quick start calls
`setup_telemetry()` and `shutdown_telemetry()` with no arguments, while the real
signatures (`rust/src/setup.rs:37,102`) are:

```rust
pub fn setup_telemetry(config: Option<TelemetryConfig>) -> Result<TelemetryConfig, TelemetryError>
pub fn shutdown_telemetry(timeout_seconds: Option<f64>) -> Result<(), TelemetryError>
```

The published quick start does not compile. Task 5 makes that impossible to
reintroduce.

- [ ] **Step 1: Read the current signatures rather than trusting this plan**

Run: `grep -n "pub fn setup_telemetry\|pub fn shutdown_telemetry\|pub fn get_logger" rust/src/*.rs rust/src/**/*.rs`
Expected: the signatures above. If they have moved since this plan was written,
document what you find, not what is written here.

- [ ] **Step 2: Correct the install line**

```toml
provide-telemetry = "0.8"
```

Use major.minor only — the crate's patch drifts from the repository `VERSION` by
design (`CLAUDE.md`, "Polyglot Structure"), so pinning the patch in docs would go
stale on every release.

- [ ] **Step 3: Correct the quick start**

```rust
use provide_telemetry::{setup_telemetry, shutdown_telemetry, get_logger};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    // None reads the configuration from the environment.
    setup_telemetry(None)?;

    let logger = get_logger("my_app");
    logger.info("app.startup.ok");

    // None uses the default shutdown timeout.
    shutdown_telemetry(None)?;
    Ok(())
}
```

Verify `get_logger`'s real signature before writing it —
`rust/src/runtime_facade.rs:222` takes `Option<&str>`, and the free function may
differ from the facade method. Match what exists.

- [ ] **Step 4: Correct the API table**

The table at `rust/README.md:46-50` lists `setup_telemetry()` and
`shutdown_telemetry()` without their parameters. Write the full signatures.

- [ ] **Step 5: Verify by compiling — do not eyeball it**

Do Task 5 now if you have not already; it extracts this snippet from the README
and compiles it against the local crate, which is the only check that catches a
wrong arity. Then:

Run: `uv run python scripts/run_pytest_gate.py --no-cov -q tests/tooling/test_readme_snippets.py::test_rust_quick_start_compiles`
Expected: PASS.

If you are working the tasks strictly in order and Task 5 does not exist yet, the
interim check is `cd rust && cargo doc --no-deps` followed by reading the
generated signatures for `setup_telemetry`, `shutdown_telemetry`, and
`get_logger` and comparing them character by character against what you wrote.
That is weaker than compiling, which is why Task 5 exists.

- [ ] **Step 6: Commit**

```bash
git add rust/README.md
git commit -m "docs(rust): correct the install version and lifecycle signatures

The quick start called setup_telemetry() and shutdown_telemetry() with no
arguments; both take an Option and return a Result. The published snippet did
not compile."
```

---

### Task 4: Correct the C# OTLP evidence claim and the stale language count

**Files:**
- Modify: `docs/guide/capability-matrix.md:61-65`
- Modify: `.github/workflows/ci-spec.yml:49`, `ci-contracts.yml:73`, `:80`, `:116`, `ci-surface.yml:64`, `:68`

- [ ] **Step 1: Confirm the C# wire evidence exists and runs**

```bash
ls csharp/tests/Provide.Telemetry.OpenTelemetry.Tests/WireDeliveryTests.cs \
   csharp/tests/Provide.Telemetry.OpenTelemetry.Tests/FakeOtlpCollector.cs
grep -n "SkippableFact\|OPENOBSERVE" csharp/tests/Provide.Telemetry.OpenTelemetry.Tests/WireDeliveryTests.cs
cd csharp && dotnet test --filter FullyQualifiedName~WireDeliveryTests
```
Expected: both files exist, `WireDeliveryTests` contains no `SkippableFact` and no
`OPENOBSERVE` reference, and the tests run and pass without credentials. If any of
that is false, the review's claim was right — stop and record it rather than
"correcting" a true statement.

- [ ] **Step 2: Rewrite the matrix paragraph**

Replace the sentence beginning **"C# is the one language whose OTLP rows have no
blocking CI evidence"** with an accurate account:

```markdown
  C#'s OTLP rows are backed by
  `csharp/tests/Provide.Telemetry.OpenTelemetry.Tests/WireDeliveryTests.cs`,
  which asserts logs, traces and metrics delivery against the in-process
  `FakeOtlpCollector`. It needs no credentials and runs in `ci-csharp.yml`, so
  it is blocking evidence. The credentialed
  `csharp/tests/Provide.Telemetry.Tests/OpenObserveIntegrationTests.cs` remains
  as live-backend verification: it is a `SkippableFact` that self-skips when
  `OPENOBSERVE_*` is unset, and it is additional to the wire test rather than a
  substitute for it.
```

Keep the surrounding paragraph's closing guidance ("If you add a signal or a
language, the collector job is the row's evidence") — it is still correct.

- [ ] **Step 3: Fix the stale language count in workflow comments**

```bash
grep -rn "four language\|four-language\|all four\|4 languages" .github/workflows/
```
Expected hits: `ci-spec.yml:49`, `ci-contracts.yml:73`, `:80`, `:116`,
`ci-surface.yml:64`, `:68`. Change each to "five languages" / "5 languages".

Leave `docs/plans/2026-08-04-*.md` alone: those are historical plan records and
were accurate when written. Check `README.md:74` and `docs/internal/parity.md:93`
— both use "the other four languages" to mean "the four that are not C#", which
is correct and must not be changed.

- [ ] **Step 4: Verify**

```bash
grep -rn "four language\|all four\|4 languages" .github/workflows/ && echo "STALE REMAINS" || echo clean
uv run python scripts/check_docs_accuracy.py
```
Expected: `clean`, then the docs checker passes.

- [ ] **Step 5: Commit**

```bash
git add docs/guide/capability-matrix.md .github/workflows/ci-spec.yml .github/workflows/ci-contracts.yml .github/workflows/ci-surface.yml
git commit -m "docs: C# OTLP rows do have blocking evidence, and there are five languages

WireDeliveryTests asserts all three signals against an in-process collector
with no credentials and runs in CI, so the matrix's 'no blocking CI evidence'
note was wrong."
```

---

### Task 5: Executable snippet tests for the quick starts

**Files:**
- Create: `tests/tooling/test_readme_snippets.py`

**Interfaces:**
- Produces: `extract_snippets(markdown: str, language: str) -> list[str]` — pulls fenced blocks by language tag; tests then compile them.

A snippet test is the only mechanism that would have caught the Rust quick start.
Cover the two compiled languages where a wrong signature is a hard error.

- [ ] **Step 1: Write the failing test**

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""The published quick starts must compile.

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
        match.group("body")
        for match in _FENCE_RE.finditer(markdown)
        if match.group("lang").lower() == language.lower()
    ]


def test_extract_snippets_picks_the_requested_language() -> None:
    markdown = "```rust\nfn a() {}\n```\n\n```toml\nx = 1\n```\n"
    assert extract_snippets(markdown, "rust") == ["fn a() {}\n"]
    assert extract_snippets(markdown, "toml") == ["x = 1\n"]


def test_extract_snippets_returns_empty_for_an_absent_language() -> None:
    assert extract_snippets("```rust\nfn a() {}\n```\n", "go") == []


def _first_main_snippet(readme: Path, language: str) -> str:
    snippets = [s for s in extract_snippets(readme.read_text(encoding="utf-8"), language) if "fn main" in s or "func main" in s]
    if not snippets:
        pytest.fail(f"{readme}: no runnable {language} quick start found")
    return snippets[0]


@pytest.mark.skipif(shutil.which("cargo") is None, reason="cargo not installed")
def test_rust_quick_start_compiles(tmp_path: Path) -> None:
    snippet = _first_main_snippet(_REPO_ROOT / "rust" / "README.md", "rust")
    crate = tmp_path / "snippet"
    (crate / "src").mkdir(parents=True)
    (crate / "Cargo.toml").write_text(
        "[package]\n"
        'name = "snippet"\n'
        'version = "0.0.0"\n'
        'edition = "2021"\n\n'
        "[dependencies]\n"
        f'provide-telemetry = {{ path = "{(_REPO_ROOT / "rust").as_posix()}" }}\n'
    )
    (crate / "src" / "main.rs").write_text(snippet)
    result = subprocess.run(
        ["cargo", "build", "--quiet"], cwd=crate, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, f"rust/README.md quick start does not compile:\n{result.stderr}"


@pytest.mark.skipif(shutil.which("go") is None, reason="go not installed")
def test_go_quick_start_compiles(tmp_path: Path) -> None:
    snippet = _first_main_snippet(_REPO_ROOT / "go" / "README.md", "go")
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
```

- [ ] **Step 2: Run and watch the Rust test fail against the OLD README**

If Task 3 is already committed, temporarily `git stash` the `rust/README.md`
change, run the test, confirm it fails with the arity error, then restore. This is
the falsifiability evidence: the test must be shown catching the bug it exists for.

Run: `uv run python scripts/run_pytest_gate.py --no-cov -q tests/tooling/test_readme_snippets.py`

- [ ] **Step 3: Run against the corrected README**

Expected: PASS for both languages. A Go failure means `go/README.md`'s quick start
has its own drift — fix the README, and record it in the checklist as a finding
the review missed.

- [ ] **Step 4: Wire it into CI**

Add a step to `.github/workflows/ci-python.yml`'s `quality` job — or a new
`docs-snippets` job if the quality job lacks a Go and Rust toolchain:

```yaml
      # Compiles the published Rust and Go quick starts. A README snippet with a
      # wrong signature is a break a consumer hits on their first five minutes.
      - name: Compile README quick starts
        run: uv run python scripts/run_pytest_gate.py --no-cov -q tests/tooling/test_readme_snippets.py
```

The tests are marked `slow`; confirm the pytest marker configuration does not
deselect them in the job you add this to.

- [ ] **Step 5: Commit**

```bash
git add tests/tooling/test_readme_snippets.py .github/workflows/ci-python.yml
git commit -m "test(docs): compile the Rust and Go quick starts"
```

---

### Task 6: Reconcile the mutation-threshold language

**Files:**
- Modify: `scripts/check_docs_accuracy.py:15,160`

The checker's message reads `run_mutation_gate command must include
--min-mutation-score 95`, which states 95 as *the* bar. The real bar is zero
survivors, timeouts, suspicious, and no-tests results; `--min-mutation-score` is
an additional floor on top (`CLAUDE.md`, "Quality Constraints";
`docs/internal/quality-gates.md:158`).

- [ ] **Step 1: Derive the message from the constant**

```python
# The enforced bar is zero survivors, timeouts, suspicious and no-tests results
# (scripts/run_mutation_gate.py::_is_clean). --min-mutation-score is a second,
# looser floor layered on top, which is why this is 95 and not 100: raising it
# would not tighten the gate, and stating it as "the" threshold misreads what
# the gate enforces.
MIN_MUTATION_SCORE = 95.0
```

And at the violation site:

```python
        if match is None or float(match.group("score")) < MIN_MUTATION_SCORE:
            violations.append(
                f"{path}:{line_no}: run_mutation_gate command must include "
                f"--min-mutation-score {MIN_MUTATION_SCORE:g} (an additional floor; "
                f"the gate itself requires zero survivors)"
            )
```

- [ ] **Step 2: Check the prose docs agree**

Read `docs/internal/quality-gates.md:155-165` and `docs/operations/runbook.md:70-80`.
Both already describe the floor correctly — confirm, and correct any document that
presents 95 as the pass mark.

- [ ] **Step 3: Run the checker**

Run: `uv run python scripts/check_docs_accuracy.py`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add scripts/check_docs_accuracy.py
git commit -m "docs: the mutation floor is additional, not the bar"
```

---

### Task 7: Full verification and checklist update

- [ ] **Step 1: Run every documentation gate**

```bash
uv run python scripts/check_docs_accuracy.py
uv run python scripts/run_pytest_gate.py --no-cov -q tests/tooling/
uv run python scripts/check_version_sync.py
uv run codespell
```
Expected: all pass.

- [ ] **Step 2: Run the repository gates**

```bash
uv run python scripts/run_pytest_gate.py
uv run ruff format --check . && uv run ruff check . && uv run mypy src tests
uv run python scripts/check_max_loc.py --max-lines 777
uv run python scripts/check_spdx_headers.py
git status --short
```
Expected: all pass; clean tree.

- [ ] **Step 3: Run the Python mutation gate**

Run: `uv run python scripts/run_mutation_gate.py --max-children 2 --min-mutation-score 95`
Expected: zero survivors. A survivor in `extract_snippets` means the language-tag
filter has an untested case — add it.

- [ ] **Step 4: Re-read the changed docs against the code one last time**

For each claim you corrected, open the file it describes and confirm the
correction is still true after plans 1, 2, 3, and 5 landed. This plan runs last
precisely so this check is meaningful — do not skip it.

- [ ] **Step 5: Update the umbrella checklist**

Tick recommendation 5 in
`docs/superpowers/plans/2026-08-20-external-review-remediation-checklist.md` and
paste the checker output. If Task 5 surfaced a Go quick-start defect the review
did not list, add it to the checklist as a new line item with its evidence.
