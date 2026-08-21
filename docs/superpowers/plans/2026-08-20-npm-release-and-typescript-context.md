# npm Release and TypeScript Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make npm publication idempotent without making it unfailable, and make TypeScript's Node async-context degradation observable instead of silent.

**Architecture:** The npm job currently carries `continue-on-error: true`, so every failure mode — bad credentials, a broken tarball, a provenance rejection — reads as success. Replace that blunt tool with a targeted one: a `ci/` script that asks the registry whether the exact version already exists, treats only that case as a successful no-op, lets every other failure be fatal, and verifies the version exists afterwards. Separately, `typescript/src/otel.ts` swallows every context-manager failure in a bare `catch {}`; replace it with a three-way discriminator that stays silent on non-Node runtimes and reports actionably on Node.

**Tech Stack:** GitHub Actions with npm Trusted Publishing (OIDC), Node 24, bash for the `ci/` script, TypeScript + vitest + Stryker.

**Spec:** [`docs/superpowers/specs/2026-08-20-external-review-remediation-design.md`](../specs/2026-08-20-external-review-remediation-design.md) (revision 2) — workstream C1.

## Global Constraints

- **Never put inline scripts in workflow YAML.** Anything over 3 lines goes in `ci/`.
- Add a short comment above every workflow step explaining what it does.
- **No new public API surface.** The TypeScript degraded state goes through the existing `setSetupError` mechanism (`typescript/src/health.ts:147-149`); do not add fields to `HealthSnapshot` or `RuntimeStatus`.
- **Fail-open for telemetry.** A missing context manager must never stop signal export. It becomes observable, not fatal.
- **777 LOC max per file**; **SPDX headers required**; **100% branch coverage** and **100% mutation kill** for TypeScript.
- `typescript/package.json` pins `vite ~8.0.16` deliberately — 8.1 breaks the vitest decorator transform. Do not float it.
- Commit messages must not mention AI assistance and must not carry a `Co-Authored-By: Claude` trailer.

## File Structure

- Create: `ci/publish-npm.sh` — registry pre-check, publish, postcondition verify.
- Create: `tests/tooling/test_publish_npm_script.py` — drives the script against a stubbed `npm` on `PATH`.
- Modify: `.github/workflows/release.yml:252-291` — drop `continue-on-error`, call the script.
- Modify: `typescript/src/otel.ts:98-109` — three-way context-manager discriminator.
- Create: `typescript/src/otel-context-manager.ts` — the discriminator, extracted so `otel.ts` stays under the LOC cap and the logic is unit-testable without a full setup.
- Create: `typescript/tests/otel-context-manager.test.ts`.
- Modify: `typescript/README.md` — install instructions name the peer dependency.

---

### Task 1: npm publish script — registry pre-check with tests

**Files:**
- Create: `ci/publish-npm.sh`
- Create: `tests/tooling/test_publish_npm_script.py`

**Interfaces:**
- Consumes: env `PACKAGE_DIR` (the unpacked package directory, default `npm-pack/package`), and `npm` on `PATH`.
- Produces: exit 0 when the version was published or already existed; non-zero on every other failure. Prints `already-published` or `published` so the workflow log records which path ran.

- [ ] **Step 1: Write the failing script tests**

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""ci/publish-npm.sh must suppress only a positively confirmed existing version."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.tooling

_SCRIPT = Path(__file__).resolve().parents[2] / "ci" / "publish-npm.sh"


def _package(tmp_path: Path, *, name: str = "@scope/pkg", version: str = "1.2.3") -> Path:
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    (package_dir / "package.json").write_text(json.dumps({"name": name, "version": version}))
    return package_dir


def _stub_npm(tmp_path: Path, *, view_exit: int, view_stdout: str, publish_exit: int) -> Path:
    """Write a fake `npm` that records its arguments and returns fixed results."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "npm"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$@" >> "{tmp_path}/npm-calls.txt"\n'
        'case "$1" in\n'
        f'  view) printf "%s" "{view_stdout}"; exit {view_exit} ;;\n'
        f"  publish) exit {publish_exit} ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n"
    )
    stub.chmod(0o755)
    return bin_dir


def _run(tmp_path: Path, package_dir: Path, bin_dir: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["PACKAGE_DIR"] = str(package_dir)
    return subprocess.run([str(_SCRIPT)], env=env, capture_output=True, text=True, check=False)


def test_existing_version_is_a_successful_no_op(tmp_path: Path) -> None:
    package_dir = _package(tmp_path)
    bin_dir = _stub_npm(tmp_path, view_exit=0, view_stdout="1.2.3", publish_exit=0)
    result = _run(tmp_path, package_dir, bin_dir)
    assert result.returncode == 0
    assert "already-published" in result.stdout
    assert "publish" not in (tmp_path / "npm-calls.txt").read_text()


def test_absent_version_is_published(tmp_path: Path) -> None:
    package_dir = _package(tmp_path)
    bin_dir = _stub_npm(tmp_path, view_exit=1, view_stdout="", publish_exit=0)
    result = _run(tmp_path, package_dir, bin_dir)
    assert result.returncode == 0
    assert "published" in result.stdout
    assert "publish" in (tmp_path / "npm-calls.txt").read_text()


def test_publish_failure_is_fatal(tmp_path: Path) -> None:
    package_dir = _package(tmp_path)
    bin_dir = _stub_npm(tmp_path, view_exit=1, view_stdout="", publish_exit=1)
    assert _run(tmp_path, package_dir, bin_dir).returncode != 0


def test_ambiguous_registry_answer_is_fatal(tmp_path: Path) -> None:
    """`npm view` returning an unexpected version is not evidence of anything."""
    package_dir = _package(tmp_path)
    bin_dir = _stub_npm(tmp_path, view_exit=0, view_stdout="9.9.9", publish_exit=0)
    assert _run(tmp_path, package_dir, bin_dir).returncode != 0


def test_missing_package_json_is_fatal(tmp_path: Path) -> None:
    bin_dir = _stub_npm(tmp_path, view_exit=1, view_stdout="", publish_exit=0)
    assert _run(tmp_path, tmp_path / "nope", bin_dir).returncode != 0
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run python scripts/run_pytest_gate.py --no-cov -q tests/tooling/test_publish_npm_script.py`
Expected: FAIL — the script does not exist.

- [ ] **Step 3: Write the script**

```bash
#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#
# Publish the packed npm tarball, idempotently — without making the job
# unfailable.
#
# The job used to carry `continue-on-error: true` so a re-triggered release
# would not fail on an already-published version. That suppressed every other
# failure too: bad credentials, a broken tarball, a rejected provenance
# attestation and a registry outage all reported success. This asks the
# registry a specific question instead, and treats only a confirmed
# already-published version as a no-op.

set -euo pipefail

readonly PACKAGE_DIR="${PACKAGE_DIR:-npm-pack/package}"

if [[ ! -f "${PACKAGE_DIR}/package.json" ]]; then
  echo "publish-npm: no package.json under ${PACKAGE_DIR}" >&2
  exit 1
fi

cd "${PACKAGE_DIR}"

name="$(node -p 'require("./package.json").name')"
version="$(node -p 'require("./package.json").version')"
if [[ -z "${name}" || -z "${version}" ]]; then
  echo "publish-npm: package.json is missing a name or version" >&2
  exit 1
fi
echo "publish-npm: ${name}@${version}"

# Ask for the exact version. A hit is proof it exists; a miss (non-zero exit)
# is the normal "not published yet" answer. Anything else — a hit reporting a
# DIFFERENT version — means the query did not mean what we assumed, so we stop
# rather than guess.
set +e
existing="$(npm view "${name}@${version}" version 2>/dev/null)"
view_status=$?
set -e

if [[ ${view_status} -eq 0 ]]; then
  if [[ "${existing}" == "${version}" ]]; then
    echo "publish-npm: already-published ${name}@${version}; nothing to do"
    exit 0
  fi
  echo "publish-npm: registry answered ${existing:-<empty>} for ${name}@${version}; refusing to guess" >&2
  exit 1
fi

# Every failure from here is fatal: auth, network, packaging, provenance.
npm publish --access public --provenance --ignore-scripts

# Postcondition. A publish that exits 0 without the version appearing is a
# failure we would otherwise ship as a release.
confirmed="$(npm view "${name}@${version}" version 2>/dev/null || true)"
if [[ "${confirmed}" != "${version}" ]]; then
  echo "publish-npm: ${name}@${version} not present after publish (saw '${confirmed}')" >&2
  exit 1
fi
echo "publish-npm: published ${name}@${version}"
```

Note the postcondition runs `npm view` again after publishing. In the
`test_absent_version_is_published` stub the second `view` also exits 1, so make
the stub's `view` return the version on its second call — or, simpler, have the
test assert on the `publish` call being recorded and let the script's
postcondition failure path be covered by its own test. Adjust the stub in Step 1
to count invocations if the assertion does not hold as written; do not weaken the
postcondition to make a test pass.

- [ ] **Step 4: Run the tests**

Run: `chmod +x ci/publish-npm.sh && uv run python scripts/run_pytest_gate.py --no-cov -q tests/tooling/test_publish_npm_script.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ci/publish-npm.sh tests/tooling/test_publish_npm_script.py
git commit -m "feat(ci): idempotent npm publish that still fails on real errors"
```

---

### Task 2: Remove `continue-on-error` and wire the script in

**Files:**
- Modify: `.github/workflows/release.yml:252-291`

**Interfaces:**
- Consumes: `ci/publish-npm.sh`, the `npm-pack` artifact downloaded by the existing step.

- [ ] **Step 1: Delete the mask**

Remove these two lines from the `publish-npm` job (`.github/workflows/release.yml:254-255`):

```yaml
    # continue-on-error: safe to retrigger — npm will fail with 403 if version already published
    continue-on-error: true
```

Nothing else in this recommendation matters until this is gone: with it present,
the script's careful exit codes are discarded by the runner.

- [ ] **Step 2: Replace the inline publish step**

Replace the `- name: Publish to npm` step's `run:` block with:

```yaml
      # Unpack the tarball we built earlier — publishing the extracted package
      # is what `npm pack` + `npm publish` round-trips to.
      - name: Unpack the built tarball
        run: tar xzf npm-pack/*.tgz -C npm-pack
      # Publish via OIDC trusted publishing. --provenance records a signed
      # attestation linking the tarball to this exact workflow run. The script
      # treats an already-published version as a no-op and every other failure
      # as fatal, then verifies the version exists afterwards.
      - name: Publish to npm
        run: ./ci/publish-npm.sh
        env:
          PACKAGE_DIR: npm-pack/package
```

- [ ] **Step 3: Lint the workflow**

Run: `uv run python -c "import yaml,pathlib;yaml.safe_load(pathlib.Path('.github/workflows/release.yml').read_text());print('ok')"`
Expected: `ok`.

If the repository has an actionlint step or a workflow-checker test, run that too:
`grep -rn "actionlint" .github/workflows/ scripts/` and run whatever it names.

- [ ] **Step 4: Confirm no other job still masks failures**

Run: `grep -n "continue-on-error" .github/workflows/release.yml`
Expected: no hits, or only hits on jobs where the design explicitly allows it. Any
remaining hit is a finding — record it in the checklist rather than deleting it
unreviewed, since another job may mask a failure for a documented reason.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "fix(ci)!: npm publish failures are fatal again

continue-on-error made every failure mode — bad credentials, a broken tarball,
a rejected provenance attestation — report success. Idempotency now comes from
a registry pre-check that suppresses only a confirmed existing version."
```

---

### Task 3: TypeScript — failing tests for the context-manager discriminator

**Files:**
- Create: `typescript/tests/otel-context-manager.test.ts`

**Interfaces:**
- Produces the contract Task 4 implements:
  `installContextManager(deps: ContextManagerDeps): Promise<ContextManagerOutcome>` where
  `ContextManagerDeps = { importHooks: () => Promise<unknown>; importApi: () => Promise<unknown>; isNode: () => boolean; warn: (message: string) => void; setSetupError: (message: string | null) => void; readSetupError: () => string | null }`
  and `ContextManagerOutcome = 'installed' | 'unsupported-runtime' | 'module-missing' | 'install-failed'`.

Injecting the dependencies is what makes the three branches testable without a
real Node/browser split, and it is what lets the mutation gate reach them.

- [ ] **Step 1: Write the failing tests**

```ts
// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

import { describe, expect, it, vi } from 'vitest';
import {
  CONTEXT_MANAGER_MESSAGE,
  installContextManager,
  type ContextManagerDeps,
} from '../src/otel-context-manager.js';

function deps(overrides: Partial<ContextManagerDeps> = {}): ContextManagerDeps {
  let stored: string | null = null;
  return {
    isNode: () => true,
    importHooks: async () => ({
      AsyncLocalStorageContextManager: class {
        enable() { return this; }
      },
    }),
    importApi: async () => ({ context: { setGlobalContextManager: () => undefined } }),
    warn: vi.fn(),
    setSetupError: (message) => { stored = message; },
    readSetupError: () => stored,
    ...overrides,
  };
}

describe('installContextManager', () => {
  it('installs the context manager on Node and records no error', async () => {
    const d = deps();
    await expect(installContextManager(d)).resolves.toBe('installed');
    expect(d.readSetupError()).toBeNull();
  });

  it('is silent on a non-Node runtime', async () => {
    const warn = vi.fn();
    const d = deps({
      isNode: () => false,
      importHooks: async () => { throw new Error('should not be called'); },
      warn,
    });
    await expect(installContextManager(d)).resolves.toBe('unsupported-runtime');
    expect(d.readSetupError()).toBeNull();
    expect(warn).not.toHaveBeenCalled();
  });

  it('reports an actionable error when the peer dependency is missing on Node', async () => {
    const warn = vi.fn();
    const missing = Object.assign(new Error('Cannot find module'), { code: 'ERR_MODULE_NOT_FOUND' });
    const d = deps({ importHooks: async () => { throw missing; }, warn });
    await expect(installContextManager(d)).resolves.toBe('module-missing');
    expect(d.readSetupError()).toBe(CONTEXT_MANAGER_MESSAGE);
    expect(warn).toHaveBeenCalledTimes(1);
    expect(warn.mock.calls[0][0]).toContain('@opentelemetry/context-async-hooks');
  });

  it('reports an actionable error when enable() throws on Node', async () => {
    const d = deps({
      importHooks: async () => ({
        AsyncLocalStorageContextManager: class {
          enable(): never { throw new Error('enable exploded'); }
        },
      }),
    });
    await expect(installContextManager(d)).resolves.toBe('install-failed');
    expect(d.readSetupError()).toBe(CONTEXT_MANAGER_MESSAGE);
  });

  it('reports an actionable error when setGlobalContextManager throws', async () => {
    const d = deps({
      importApi: async () => ({
        context: { setGlobalContextManager: () => { throw new Error('registry locked'); } },
      }),
    });
    await expect(installContextManager(d)).resolves.toBe('install-failed');
    expect(d.readSetupError()).toBe(CONTEXT_MANAGER_MESSAGE);
  });

  it('warns only once across repeated failures', async () => {
    const warn = vi.fn();
    const d = deps({ importHooks: async () => { throw new Error('nope'); }, warn });
    await installContextManager(d);
    await installContextManager(d);
    expect(warn).toHaveBeenCalledTimes(1);
  });

  it('clears its own prior message when a later attempt succeeds', async () => {
    let stored: string | null = CONTEXT_MANAGER_MESSAGE;
    const d = deps({
      setSetupError: (m) => { stored = m; },
      readSetupError: () => stored,
    });
    await installContextManager(d);
    expect(stored).toBeNull();
  });

  it('leaves an unrelated setup error alone when it succeeds', async () => {
    let stored: string | null = 'applyConfigPolicies failed: bad sample rate';
    const d = deps({
      setSetupError: (m) => { stored = m; },
      readSetupError: () => stored,
    });
    await installContextManager(d);
    expect(stored).toBe('applyConfigPolicies failed: bad sample rate');
  });
});
```

- [ ] **Step 2: Run and confirm failure**

Run: `cd typescript && npx vitest run tests/otel-context-manager.test.ts`
Expected: FAIL — cannot resolve `../src/otel-context-manager.js`.

- [ ] **Step 3: Commit the red tests**

```bash
git add typescript/tests/otel-context-manager.test.ts
git commit -m "test(typescript): context manager failure must be observable"
```

---

### Task 4: TypeScript — implement the discriminator

**Files:**
- Create: `typescript/src/otel-context-manager.ts`
- Modify: `typescript/src/otel.ts:98-109`

**Interfaces:**
- Consumes: `dynImportOtel` (`typescript/src/otel-dynimport.ts:22`), `setSetupError` and `getHealthSnapshot` (`typescript/src/health.ts:113,147`), the `_isNodeLike` predicate used by `typescript/src/config.ts:363`.
- Produces: `installContextManager`, `CONTEXT_MANAGER_MESSAGE`, `_resetContextManagerWarningForTests`.

- [ ] **Step 1: Write the module**

```ts
// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

/**
 * Node async-context installation, made observable.
 *
 * `startActiveSpan` only propagates across `await` boundaries when an
 * AsyncLocalStorage context manager is registered. Installing it used to be a
 * bare try/catch labelled "not Node or peer dep not installed — skip
 * silently", which collapsed three different situations into one: a browser
 * build where no context manager is wanted, a Node process missing the peer
 * dependency, and a Node process where installation genuinely failed. The
 * first is correct and should stay quiet. The other two produce spans with no
 * parent, which looks like a tracing bug rather than a setup problem.
 *
 * Failing here is never fatal — signal export works without context
 * propagation — so this reports rather than throws.
 */

export const CONTEXT_MANAGER_MESSAGE =
  'AsyncLocalStorage context manager unavailable: spans will not propagate across ' +
  'await boundaries. Install @opentelemetry/context-async-hooks (peer dependency) ' +
  'in this Node application.';

export type ContextManagerOutcome =
  | 'installed'
  | 'unsupported-runtime'
  | 'module-missing'
  | 'install-failed';

export interface ContextManagerDeps {
  isNode: () => boolean;
  importHooks: () => Promise<unknown>;
  importApi: () => Promise<unknown>;
  warn: (message: string) => void;
  setSetupError: (message: string | null) => void;
  readSetupError: () => string | null;
}

let _warned = false;

/** Test seam: the one-time warning latch is module state. */
export function _resetContextManagerWarningForTests(): void {
  _warned = false;
}

function _isModuleMissing(error: unknown): boolean {
  const code = (error as { code?: unknown } | null)?.code;
  return code === 'ERR_MODULE_NOT_FOUND' || code === 'MODULE_NOT_FOUND';
}

function _report(deps: ContextManagerDeps): void {
  deps.setSetupError(CONTEXT_MANAGER_MESSAGE);
  if (!_warned) {
    _warned = true;
    deps.warn(`[provide-telemetry] ${CONTEXT_MANAGER_MESSAGE}`);
  }
}

export async function installContextManager(
  deps: ContextManagerDeps,
): Promise<ContextManagerOutcome> {
  // A browser or edge build has no AsyncLocalStorage and is not meant to. That
  // is a supported configuration, not a degradation, so it stays silent.
  if (!deps.isNode()) return 'unsupported-runtime';

  let hooks: unknown;
  try {
    hooks = await deps.importHooks();
  } catch (error: unknown) {
    _report(deps);
    return _isModuleMissing(error) ? 'module-missing' : 'install-failed';
  }

  try {
    const api = (await deps.importApi()) as {
      context: { setGlobalContextManager: (manager: unknown) => void };
    };
    const Ctor = (hooks as { AsyncLocalStorageContextManager: new () => { enable: () => unknown } })
      .AsyncLocalStorageContextManager;
    const manager = new Ctor();
    manager.enable();
    api.context.setGlobalContextManager(manager);
  } catch {
    _report(deps);
    return 'install-failed';
  }

  // Clear only our own message. An unrelated setup error — a rejected config
  // policy, an ALS fallback — belongs to whoever recorded it.
  if (deps.readSetupError() === CONTEXT_MANAGER_MESSAGE) deps.setSetupError(null);
  return 'installed';
}
```

- [ ] **Step 2: Run the tests**

Run: `cd typescript && npx vitest run tests/otel-context-manager.test.ts`
Expected: PASS. The one-time-warning test needs `_resetContextManagerWarningForTests()`
in a `beforeEach` — add it to the test file now if it is not already there.

- [ ] **Step 3: Call it from `otel.ts`**

Replace the block at `typescript/src/otel.ts:98-109` with:

```ts
  // ── Context manager ──────────────────────────────────────────────────────────
  // Install AsyncLocalStorageContextManager so startActiveSpan propagates spans
  // through async boundaries in Node.js. Must happen before TracerProvider setup.
  // Failure is reported through setSetupError rather than swallowed — see
  // otel-context-manager.ts for why the three outcomes are distinguished.
  await installContextManager({
    isNode: () => typeof process !== 'undefined' && process.versions?.node != null,
    importHooks: () => dynImportOtel('@opentelemetry/context-async-hooks'),
    importApi: () => import('@opentelemetry/api'),
    warn: (message) => console.warn(message),
    setSetupError,
    readSetupError: () => getHealthSnapshot().setupError,
  });
```

Add the imports:

```ts
import { installContextManager } from './otel-context-manager.js';
import { getHealthSnapshot, setSetupError } from './health.js';
```

If `otel.ts` already imports from `./health.js`, extend the existing import rather
than adding a second one. If a `_isNodeLike`-style predicate is already exported
from `config.ts`, use it instead of the inline `process.versions` check — one
runtime predicate, not two.

- [ ] **Step 4: Prove the fail-open contract still holds**

Run: `cd typescript && npx vitest run`
Expected: PASS. In particular, existing OTel setup tests must still pass with the
context-async-hooks peer absent — export must not depend on it.

- [ ] **Step 5: Prove the message reaches both status surfaces**

Add to `typescript/tests/otel-context-manager.test.ts`:

```ts
  it('surfaces through both getHealthSnapshot and getRuntimeStatus', async () => {
    const { getHealthSnapshot, setSetupError } = await import('../src/health.js');
    const { getRuntimeStatus } = await import('../src/runtime.js');
    setSetupError(CONTEXT_MANAGER_MESSAGE);
    expect(getHealthSnapshot().setupError).toBe(CONTEXT_MANAGER_MESSAGE);
    expect(getRuntimeStatus().setupError).toBe(CONTEXT_MANAGER_MESSAGE);
    setSetupError(null);
  });
```

Run: `cd typescript && npx vitest run tests/otel-context-manager.test.ts`
Expected: PASS. This is the assertion that proves no new public field was needed.

- [ ] **Step 6: Negative control**

Temporarily replace `_report(deps)` in the `importHooks` catch with a no-op,
run the suite, confirm `reports an actionable error when the peer dependency is
missing on Node` fails, then restore.

- [ ] **Step 7: Check the LOC cap**

Run: `uv run python scripts/check_max_loc.py --max-lines 777`
Expected: PASS — extracting the module is partly why it is a separate file.

- [ ] **Step 8: Commit**

```bash
git add typescript/src/otel-context-manager.ts typescript/src/otel.ts typescript/tests/otel-context-manager.test.ts
git commit -m "fix(typescript): report Node context-manager failures

A bare catch treated a browser build, a missing peer dependency and a failed
installation as the same silent skip. The last two leave spans unparented,
which reads as a tracing bug. Report them through the existing setupError
channel and keep export fail-open."
```

---

### Task 5: Document the peer dependency

**Files:**
- Modify: `typescript/README.md`

- [ ] **Step 1: Name it in the install instructions**

`@opentelemetry/context-async-hooks` is already declared under
`peerDependencies` in `typescript/package.json` — the gap is that a reader
following the README never learns to install it. Add it to the OTel install
command and add a sentence saying what breaks without it:

```markdown
On Node, also install `@opentelemetry/context-async-hooks`. Without it there is
no AsyncLocalStorage context manager, so `startActiveSpan` cannot propagate a
span across an `await` boundary and child spans are emitted without a parent.
Telemetry still exports; the trace tree is what degrades. When the package is
missing on Node, `getHealthSnapshot().setupError` and
`getRuntimeStatus().setupError` both report it.
```

- [ ] **Step 2: Run the docs checker**

Run: `uv run python scripts/check_docs_accuracy.py`
Expected: PASS. `typescript/README.md` is outside `DOC_PATHS` until plan 4 widens
it, so this passing does not yet prove the new prose is checked — plan 4 closes
that loop.

- [ ] **Step 3: Commit**

```bash
git add typescript/README.md
git commit -m "docs(typescript): name the context-async-hooks peer dependency"
```

---

### Task 6: Full verification and checklist update

- [ ] **Step 1: Run the TypeScript gates**

```bash
cd typescript
npm run build
npx vitest run --coverage
npx tsc --noEmit
```
Expected: PASS with 100% branch coverage. An uncovered branch in
`otel-context-manager.ts` means one of the four outcomes has no test.

- [ ] **Step 2: Run both Stryker configs, one at a time**

```bash
cd typescript
npx stryker run --concurrency 2
npx stryker run --concurrency 2 -c stryker.otel.config.mjs
```
Expected: no survivors. A survivor on `_isModuleMissing` means the
`MODULE_NOT_FOUND` alternative has no test — add one rather than deleting the
branch, since CommonJS callers produce that code.

- [ ] **Step 3: Run the Python tooling tests and repo gates**

```bash
uv run python scripts/run_pytest_gate.py -m tooling --no-cov -q
uv run python scripts/check_max_loc.py --max-lines 777
uv run python scripts/check_spdx_headers.py
git status --short
```
Expected: all pass; clean tree.

- [ ] **Step 4: Update the umbrella checklist**

Tick recommendations 6 and 7 in
`docs/superpowers/plans/2026-08-20-external-review-remediation-checklist.md`,
pasting real output. The `continue-on-error` removal is the item most worth
quoting verbatim — paste the `grep -n "continue-on-error" .github/workflows/release.yml`
result showing it gone.
