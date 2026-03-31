# Mutation Debt Kill Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kill all pre-existing surviving mutants in `fingerprint.ts`, `pretty.ts`, `logger.ts` (TypeScript) and `processors.py`, `middleware.py` (Python) by adding targeted tests that assert exact values — not just structural validity.

**Architecture:** Every surviving mutant exists because the existing tests check *shape* (correct length, non-empty, different-from-other) but not *content* (exact values, exact separators, exact ANSI codes). New tests fix this by computing expected values inline from known inputs, directly exercising the discriminating conditions.

**Tech Stack:** Vitest + `node:crypto` (TypeScript), pytest + `hashlib` + `traceback` (Python), no new dependencies.

---

## Background: Why These Mutants Survive

| File | Root cause |
|------|-----------|
| `fingerprint.ts` | Tests check `length == 12` and `a != b` — never assert exact hash, so separator/slice/case mutations survive |
| `pretty.ts` | Tests check level name appears, not the ANSI escape code; SKIP_KEYS only partially verified |
| `logger.ts` | `?? ''` fallback on line 70 never tested when `event` is absent |
| `processors.py` | Same as fingerprint.ts; harden_input boundary conditions (`>` vs `>=`) untested |
| `middleware.py` | `_extract_baggage_value` is private and untested directly |

---

## File Map

| File | Action |
|------|--------|
| `typescript/tests/fingerprint.test.ts` | Add 7 tests |
| `typescript/tests/pretty.test.ts` | Add 11 tests |
| `typescript/tests/logger.test.ts` | Add 1 test |
| `tests/logger/test_error_fingerprint.py` | Add 6 tests |
| `tests/logger/test_processors_mutations.py` | Add 10 tests |
| `tests/asgi/test_middleware_mutations.py` | Add 4 tests |

---

## Task 1: Kill TypeScript `fingerprint.ts` survivors

**Files:**
- Modify: `typescript/tests/fingerprint.test.ts`

The root problem: every existing test calls `computeErrorFingerprint` and checks `length == 12` or `a != b`. None assert the exact computed value. Stryker can mutate the colon separator, the `slice(-3)`, any `.toLowerCase()`, or the path-extraction logic and tests still pass.

Strategy: add tests that compute the expected hash inline using `createHash` with explicit known inputs, then assert equality.

- [ ] **Step 1: Add exact-hash tests to fingerprint.test.ts**

Add the following `describe` block at the end of `typescript/tests/fingerprint.test.ts`:

```ts
import { createHash } from 'node:crypto';

describe('computeErrorFingerprint — exact value assertions (mutation kills)', () => {
  it('uses last 3 frames from a 4-frame stack, not all 4', () => {
    // frames from 4-line stack: ['a:func1', 'b:func2', 'c:func3', 'd:func4']
    // slice(-3) → ['b:func2', 'c:func3', 'd:func4']
    // parts = ['error', 'b:func2', 'c:func3', 'd:func4']
    const stack4 = `Error: boom
    at func1 (a.js:1:1)
    at func2 (b.js:1:1)
    at func3 (c.js:1:1)
    at func4 (d.js:1:1)`;

    // Expected: exact hash of the 3-frame version
    const expected = createHash('sha256')
      .update('error:b:func2:c:func3:d:func4')
      .digest('hex')
      .slice(0, 12);

    expect(computeErrorFingerprint('Error', stack4)).toBe(expected);
  });

  it('uses colon as separator between error name and frame parts', () => {
    // parts = ['typeerror', 'script:myfunc']
    // ':'.join → 'typeerror:script:myfunc'
    // ''.join → 'typeerrorscrip:myfunc' (different hash)
    const stack = 'at myFunc (script.js:1:1)';
    const expected = createHash('sha256')
      .update('typeerror:script:myfunc')
      .digest('hex')
      .slice(0, 12);
    expect(computeErrorFingerprint('TypeError', stack)).toBe(expected);
  });

  it('uses colon as separator inside each frame (basename:func)', () => {
    // frame format is "basename:func" — colon between basename and func
    // mutation might change to "basename.func" or "basename func"
    const stack = 'at handler (src/utils/helper.js:1:1)';
    // basename = 'helper', func = 'handler'
    const expected = createHash('sha256')
      .update('error:helper:handler')
      .digest('hex')
      .slice(0, 12);
    expect(computeErrorFingerprint('Error', stack)).toBe(expected);
  });

  it('case-folds error name to lowercase', () => {
    // mutation: remove .toLowerCase() on errorName → 'TypeError' ≠ 'typeerror'
    expect(computeErrorFingerprint('TypeError')).toBe(computeErrorFingerprint('typeerror'));
    expect(computeErrorFingerprint('TypeError')).toBe(computeErrorFingerprint('TYPEERROR'));
  });

  it('case-folds function names from V8 stack', () => {
    // mutation: remove .toLowerCase() on func
    const lowerStack = 'at myFunc (script.js:1:1)';
    const upperStack = 'at MYFUNC (script.js:1:1)';
    expect(computeErrorFingerprint('Error', lowerStack)).toBe(
      computeErrorFingerprint('Error', upperStack),
    );
  });

  it('case-folds file basenames from V8 stack', () => {
    // mutation: remove .toLowerCase() on basename
    const lowerStack = 'at handler (MyFile.js:1:1)';
    const upperStack = 'at handler (MYFILE.js:1:1)';
    expect(computeErrorFingerprint('Error', lowerStack)).toBe(
      computeErrorFingerprint('Error', upperStack),
    );
  });

  it('anonymous function (no name) produces empty func string, not "undefined"', () => {
    // stack line without function name: match[1] is undefined
    // `String(match[1] || '')` should produce '' not 'undefined'
    const stack = 'at /app/src/index.js:10:5';
    // parts = ['error', 'index:']  (empty func)
    const expected = createHash('sha256')
      .update('error:index:')
      .digest('hex')
      .slice(0, 12);
    const withUndefined = createHash('sha256')
      .update('error:index:undefined')
      .digest('hex')
      .slice(0, 12);
    expect(computeErrorFingerprint('Error', stack)).toBe(expected);
    expect(computeErrorFingerprint('Error', stack)).not.toBe(withUndefined);
  });
});
```

- [ ] **Step 2: Run the fingerprint tests**

```bash
cd typescript && npx vitest run tests/fingerprint.test.ts
```

Expected: all tests pass, including the 7 new ones.

- [ ] **Step 3: Run full TypeScript test suite with coverage**

```bash
cd typescript && npm run test:coverage
```

Expected: all tests pass, 100% coverage maintained.

- [ ] **Step 4: Commit**

```bash
git add typescript/tests/fingerprint.test.ts
git commit -m "test(ts): assert exact fingerprint values to kill mutation survivors"
```

---

## Task 2: Kill TypeScript `pretty.ts` and `logger.ts` survivors

**Files:**
- Modify: `typescript/tests/pretty.test.ts`
- Modify: `typescript/tests/logger.test.ts`

**pretty.ts survivors:** The existing test `renders all level colors correctly` only checks that the level name string appears — not the ANSI escape code. LEVEL_COLORS mutations (`'\x1b[31;1m'` → `'\x1b[31m'` for fatal, etc.) survive. Also, SKIP_KEYS has 7 members but the existing test only checks 3 (`pid`, `hostname`, `v`). The `NO_COLOR` branch can be mutated to always-false since the test doesn't combine it with `isTTY=true`. The `time !== undefined` guard can be mutated to `true` since missing-time is not tested with a structural assertion.

**logger.ts survivor:** Line 70: `o['msg'] = o['event'] ?? ''` — the `?? ''` fallback survives because no test logs without both `msg` and `event` and then checks the msg value is an empty string.

- [ ] **Step 1: Add exact ANSI code tests to pretty.test.ts**

Add the following `describe` block at the end of `typescript/tests/pretty.test.ts`:

```ts
describe('formatPretty — exact ANSI codes and key filtering (mutation kills)', () => {
  it('fatal level uses bold red \\x1b[31;1m (not plain red)', () => {
    const line = formatPretty({ level: 60, event: 'test' }, true);
    expect(line).toContain('\x1b[31;1m');
    // Verify it is NOT the plain (non-bold) red used by error
    expect(line).not.toContain('\x1b[31m[');
  });

  it('error level uses plain red \\x1b[31m (not bold)', () => {
    const line = formatPretty({ level: 50, event: 'test' }, true);
    expect(line).toContain('\x1b[31m');
    expect(line).not.toContain('\x1b[31;1m');
  });

  it('warn level uses yellow \\x1b[33m', () => {
    const line = formatPretty({ level: 40, event: 'test' }, true);
    expect(line).toContain('\x1b[33m');
  });

  it('info level uses green \\x1b[32m', () => {
    const line = formatPretty({ level: 30, event: 'test' }, true);
    expect(line).toContain('\x1b[32m');
  });

  it('debug level uses blue \\x1b[34m', () => {
    const line = formatPretty({ level: 20, event: 'test' }, true);
    expect(line).toContain('\x1b[34m');
  });

  it('trace level uses cyan \\x1b[36m', () => {
    const line = formatPretty({ level: 10, event: 'test' }, true);
    expect(line).toContain('\x1b[36m');
  });

  it('skips all 7 internal SKIP_KEYS: level, time, msg, event, v, pid, hostname', () => {
    const line = formatPretty(
      { level: 30, time: 123, msg: 'hi', event: 'test', v: 1, pid: 99, hostname: 'box', user: 'alice' },
      false,
    );
    expect(line).not.toContain('level=');
    expect(line).not.toContain('time=');
    expect(line).not.toContain('msg=');
    expect(line).not.toContain('event=');
    expect(line).not.toContain('v=');
    expect(line).not.toContain('pid=');
    expect(line).not.toContain('hostname=');
    expect(line).toContain('user='); // non-skip key still present
  });

  it('NO_COLOR env takes precedence over isTTY=true', () => {
    vi.stubEnv('NO_COLOR', '');
    const orig = (process.stdout as { isTTY?: boolean }).isTTY;
    try {
      Object.defineProperty(process.stdout, 'isTTY', { value: true, configurable: true });
      expect(supportsColor()).toBe(false);
    } finally {
      Object.defineProperty(process.stdout, 'isTTY', { value: orig, configurable: true });
      vi.unstubAllEnvs();
    }
  });

  it('omits timestamp entirely when time is absent', () => {
    // mutation: `time !== undefined` → `true` would include "undefined" in output
    const line = formatPretty({ level: 30, event: 'test' }, false);
    expect(line).not.toContain('undefined');
    // Line starts directly with level bracket, not a timestamp
    expect(line.trimStart()).toMatch(/^\[/);
  });

  it('key=value separator is = in no-color mode', () => {
    const line = formatPretty({ level: 30, event: 'test', user: 'alice' }, false);
    expect(line).toContain('user=');
    expect(line).toContain('="alice"');
  });

  it('key=value separator is = in color mode (with DIM wrapping)', () => {
    const line = formatPretty({ level: 30, event: 'test', user: 'alice' }, true);
    // DIM + key + RESET + '=' + value
    expect(line).toContain('\x1b[2muser\x1b[0m=');
  });
});
```

- [ ] **Step 2: Add logger.ts `?? ''` fallback test to logger.test.ts**

Add at the end of the `'write hook — window.__pinoLogs capture'` describe block in `typescript/tests/logger.test.ts`:

```ts
  it('msg defaults to empty string when both msg and event are absent', () => {
    // mutation: `o['event'] ?? ''` → `o['event'] ?? null` or similar
    makeCfg();
    const hook = makeWriteHook();
    const obj: Record<string, unknown> = { level: 30 }; // no msg, no event
    hook(obj as object);
    // After hook runs, obj['msg'] should be '' not undefined or null
    expect(obj['msg']).toBe('');
  });
```

- [ ] **Step 3: Run the pretty and logger tests**

```bash
cd typescript && npx vitest run tests/pretty.test.ts tests/logger.test.ts
```

Expected: all tests pass.

- [ ] **Step 4: Run full TypeScript test suite with coverage**

```bash
cd typescript && npm run test:coverage
```

Expected: all tests pass, 100% coverage maintained.

- [ ] **Step 5: Commit**

```bash
git add typescript/tests/pretty.test.ts typescript/tests/logger.test.ts
git commit -m "test(ts): assert exact ANSI codes, SKIP_KEYS completeness, and msg fallback"
```

---

## Task 3: Kill Python `processors.py` survivors

**Files:**
- Modify: `tests/logger/test_error_fingerprint.py`
- Modify: `tests/logger/test_processors_mutations.py`

**`_compute_error_fingerprint` survivors:** Tests check length and determinism, never the exact hash. Mutations to `":".join(parts)`, `[-3:]` slice, any `.lower()` call, or the `f"{basename}:{func}"` format all survive.

**`add_error_fingerprint` survivors:** `len(exc_info) == 3` can mutate to `== 2`; `exc_info[1] is not None` can flip; `isinstance(exc_info, BaseException)` can narrow to `Exception`. Existing tests all use `ValueError`/`RuntimeError` (both `Exception` subclasses).

**`harden_input` survivors:** `>` vs `>=` on length and attr-count checks; `<` vs `<=` on depth recursion. None are tested at exact boundary values.

**`sanitize_sensitive_fields` survivors:** The `max_depth=8` default parameter can be mutated to `7` — never verified.

- [ ] **Step 1: Add exact-hash tests to test_error_fingerprint.py**

Add the following class to `tests/logger/test_error_fingerprint.py`:

```python
import hashlib
import traceback


class TestComputeErrorFingerprintExact:
    def test_exact_hash_no_tb(self) -> None:
        """Kills: missing .lower() on exc_type, [:12] → [:11], or any encoding mutation."""
        expected = hashlib.sha256("valueerror".encode("utf-8")).hexdigest()[:12]
        assert _compute_error_fingerprint("ValueError", None) == expected

    def test_case_folds_exc_type(self) -> None:
        """Kills: .lower() removed from exc_type."""
        lower = _compute_error_fingerprint("valueerror", None)
        upper = _compute_error_fingerprint("VALUEERROR", None)
        mixed = _compute_error_fingerprint("ValueError", None)
        assert lower == upper == mixed

    def test_colon_separator_between_type_and_frame(self) -> None:
        """Kills: ':'.join(parts) → ''.join(parts) or other separator."""
        try:
            raise ValueError("test")
        except ValueError:
            _, _, tb = sys.exc_info()

        # Compute expected hash using same frame-extraction logic but explicit ':' sep
        frames = traceback.extract_tb(tb)[-3:]
        parts = ["valueerror"]
        for frame in frames:
            leaf = frame.filename.replace("\\", "/").rsplit("/", 1)[-1]
            basename = leaf.rsplit(".", 1)[0].lower()
            func = (frame.name or "").lower()
            parts.append(f"{basename}:{func}")
        expected_colon = hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()[:12]
        expected_no_sep = hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()[:12]

        result = _compute_error_fingerprint("ValueError", tb)
        assert result == expected_colon
        assert result != expected_no_sep

    def test_basename_colon_func_frame_format(self) -> None:
        """Kills: f'{basename}:{func}' → f'{basename}.{func}' or f'{basename} {func}'."""
        try:
            raise ValueError("test")
        except ValueError:
            _, _, tb = sys.exc_info()

        frames = traceback.extract_tb(tb)[-3:]
        frame = frames[-1]
        leaf = frame.filename.replace("\\", "/").rsplit("/", 1)[-1]
        basename = leaf.rsplit(".", 1)[0].lower()
        func = (frame.name or "").lower()

        # Both basename and func must be non-empty for this to be meaningful
        assert basename, "test setup: basename should not be empty"
        assert func, "test setup: func name should not be empty"

        expected = hashlib.sha256(
            f"valueerror:{basename}:{func}".encode("utf-8")
        ).hexdigest()[:12]
        expected_dot = hashlib.sha256(
            f"valueerror:{basename}.{func}".encode("utf-8")
        ).hexdigest()[:12]

        assert _compute_error_fingerprint("ValueError", tb) == expected
        assert _compute_error_fingerprint("ValueError", tb) != expected_dot

    def test_uses_last_3_frames_from_longer_stack(self) -> None:
        """Kills: traceback.extract_tb(tb)[-3:] → extract_tb(tb) (all frames)."""

        def inner() -> None:
            raise ValueError("test")

        def middle() -> None:
            inner()

        def outer() -> None:
            middle()

        try:
            outer()
        except ValueError:
            _, _, tb = sys.exc_info()

        all_frames = traceback.extract_tb(tb)
        assert len(all_frames) >= 4, "test requires >=4 frames in stack"

        # With [-3:], only last 3 frames contribute
        last3 = all_frames[-3:]
        parts_3 = ["valueerror"]
        for frame in last3:
            leaf = frame.filename.replace("\\", "/").rsplit("/", 1)[-1]
            basename = leaf.rsplit(".", 1)[0].lower()
            func = (frame.name or "").lower()
            parts_3.append(f"{basename}:{func}")
        expected = hashlib.sha256(":".join(parts_3).encode("utf-8")).hexdigest()[:12]

        # All frames would produce a different hash
        all_parts = ["valueerror"]
        for frame in all_frames:
            leaf = frame.filename.replace("\\", "/").rsplit("/", 1)[-1]
            basename = leaf.rsplit(".", 1)[0].lower()
            func = (frame.name or "").lower()
            all_parts.append(f"{basename}:{func}")
        full_hash = hashlib.sha256(":".join(all_parts).encode("utf-8")).hexdigest()[:12]

        result = _compute_error_fingerprint("ValueError", tb)
        assert result == expected
        assert result != full_hash

    def test_case_folds_func_and_basename_from_tb(self) -> None:
        """Kills: .lower() removed from basename or func."""
        try:
            raise ValueError("test")
        except ValueError:
            _, _, tb = sys.exc_info()

        result = _compute_error_fingerprint("ValueError", tb)
        result_upper = _compute_error_fingerprint("VALUEERROR", tb)
        assert result == result_upper
```

- [ ] **Step 2: Run the fingerprint tests**

```bash
uv run python scripts/run_pytest_gate.py tests/logger/test_error_fingerprint.py --no-cov -q
```

Expected: all tests pass.

- [ ] **Step 3: Add add_error_fingerprint boundary tests to test_processors_mutations.py**

Add to `tests/logger/test_processors_mutations.py` (after the existing `TestEnforceEventSchemaMutants` class):

```python
# ── add_error_fingerprint: tuple shape and type guards ────────────────


class TestAddErrorFingerprintGuards:
    def test_two_tuple_exc_info_does_not_produce_fingerprint(self) -> None:
        """Kills: len(exc_info) == 3 → == 2 or != 3."""
        # A 2-tuple is not a valid exc_info — should not trigger fingerprinting
        event: dict[str, object] = {"event": "error", "exc_info": (ValueError, ValueError("x"))}
        result = add_error_fingerprint(None, "", event)
        assert "error_fingerprint" not in result

    def test_three_tuple_with_none_exception_does_not_produce_fingerprint(self) -> None:
        """Kills: exc_info[1] is not None → is None."""
        event: dict[str, object] = {"event": "error", "exc_info": (type(None), None, None)}
        result = add_error_fingerprint(None, "", event)
        assert "error_fingerprint" not in result

    def test_base_exception_not_subclass_of_exception_is_handled(self) -> None:
        """Kills: isinstance(exc_info, BaseException) → isinstance(exc_info, Exception)."""
        # KeyboardInterrupt is a BaseException but not an Exception
        exc = KeyboardInterrupt("interrupted")
        event: dict[str, object] = {"event": "error", "exc_info": exc}
        result = add_error_fingerprint(None, "", event)
        assert "error_fingerprint" in result
        assert result["error_fingerprint"] == _compute_error_fingerprint("KeyboardInterrupt", exc.__traceback__)

    def test_three_tuple_with_valid_exception_does_produce_fingerprint(self) -> None:
        """Verifies the len==3 and is-not-None fast path."""
        try:
            raise RuntimeError("test")
        except RuntimeError:
            exc_info = sys.exc_info()
        event: dict[str, object] = {"event": "error", "exc_info": exc_info}
        result = add_error_fingerprint(None, "", event)
        assert "error_fingerprint" in result


# ── harden_input: exact boundary values ──────────────────────────────


class TestHardenInputBoundaries:
    def test_string_at_exact_max_length_not_truncated(self) -> None:
        """Kills: len(cleaned) > max_value_length → >=."""
        proc = harden_input(max_value_length=5, max_attr_count=0, max_depth=5)
        result = proc(None, "", {"event": "x", "key": "hello"})  # exactly 5 chars
        assert result["key"] == "hello"  # not truncated

    def test_string_one_over_max_length_truncated(self) -> None:
        """Companion to above — confirms truncation does fire at len+1."""
        proc = harden_input(max_value_length=5, max_attr_count=0, max_depth=5)
        result = proc(None, "", {"event": "x", "key": "hello!"})  # 6 chars
        assert result["key"] == "hello"

    def test_max_attr_count_zero_keeps_all_attributes(self) -> None:
        """Kills: max_attr_count > 0 → >= 0 (would truncate even with count=0)."""
        proc = harden_input(max_value_length=100, max_attr_count=0, max_depth=5)
        event: dict[str, object] = {"event": "x", "a": 1, "b": 2, "c": 3}
        result = proc(None, "", event)
        assert len(result) == 4  # all keys preserved

    def test_attrs_at_exact_max_count_not_dropped(self) -> None:
        """Kills: len(event_dict) > max_attr_count → >=."""
        proc = harden_input(max_value_length=100, max_attr_count=3, max_depth=5)
        event: dict[str, object] = {"event": "x", "a": 1, "b": 2}  # exactly 3 keys
        result = proc(None, "", event)
        assert len(result) == 3  # not truncated

    def test_attrs_one_over_max_count_truncated(self) -> None:
        """Companion — confirms attr dropping fires at count+1."""
        proc = harden_input(max_value_length=100, max_attr_count=3, max_depth=5)
        event: dict[str, object] = {"event": "x", "a": 1, "b": 2, "c": 3}  # 4 keys
        result = proc(None, "", event)
        assert len(result) == 3

    def test_depth_zero_does_not_recurse_into_nested_dict(self) -> None:
        """Kills: depth < max_depth → depth <= max_depth.

        At max_depth=0: depth=0 < 0 is False → dict not recursed, control chars survive.
        At max_depth=0 with mutation <=: depth=0 <= 0 is True → dict IS recursed.
        """
        proc = harden_input(max_value_length=100, max_attr_count=0, max_depth=0)
        event: dict[str, object] = {"event": "x", "nested": {"inner": "\x01dirty"}}
        result = proc(None, "", event)
        # Nested dict should be returned as-is (no recursion at depth=0 with max_depth=0)
        assert result["nested"] == {"inner": "\x01dirty"}

    def test_depth_one_recurses_one_level(self) -> None:
        """Companion — with max_depth=1, depth=0 < 1 is True → recurse and clean."""
        proc = harden_input(max_value_length=100, max_attr_count=0, max_depth=1)
        result = proc(None, "", {"event": "x", "nested": {"inner": "\x01dirty"}})
        assert result["nested"] == {"inner": "dirty"}


# ── sanitize_sensitive_fields: max_depth default ─────────────────────


class TestSanitizeSensitiveFieldsDefault:
    def test_default_max_depth_is_8(self) -> None:
        """Kills: max_depth=8 → max_depth=7 or other value."""
        with patch("provide.telemetry.logger.processors.sanitize_payload") as mock:
            mock.return_value = {}
            processor = sanitize_sensitive_fields(enabled=True)
            processor(None, "", {"event": "x"})
        mock.assert_called_once_with({"event": "x"}, True, max_depth=8)

    def test_custom_max_depth_forwarded(self) -> None:
        """Verifies max_depth param is passed through."""
        with patch("provide.telemetry.logger.processors.sanitize_payload") as mock:
            mock.return_value = {}
            processor = sanitize_sensitive_fields(enabled=True, max_depth=3)
            processor(None, "", {"event": "x"})
        mock.assert_called_once_with({"event": "x"}, True, max_depth=3)
```

Add the necessary imports to `test_processors_mutations.py` — the existing import block needs `add_error_fingerprint`, `harden_input`, `sanitize_sensitive_fields`, `_compute_error_fingerprint`, and `sys`:

```python
import sys

from provide.telemetry.logger.processors import (
    _compute_error_fingerprint,
    add_error_fingerprint,
    add_standard_fields,
    apply_sampling,
    enforce_event_schema,
    harden_input,
    merge_runtime_context,
    sanitize_sensitive_fields,
)
```

- [ ] **Step 4: Run the processor tests**

```bash
uv run python scripts/run_pytest_gate.py tests/logger/test_processors_mutations.py tests/logger/test_error_fingerprint.py --no-cov -q
```

Expected: all tests pass.

- [ ] **Step 5: Run full Python test suite with coverage**

```bash
uv run python scripts/run_pytest_gate.py
```

Expected: all tests pass, 100% coverage maintained.

- [ ] **Step 6: Commit**

```bash
git add tests/logger/test_error_fingerprint.py tests/logger/test_processors_mutations.py
git commit -m "test(py): assert exact fingerprint values and harden_input boundaries"
```

---

## Task 4: Kill Python `middleware.py` survivors

**Files:**
- Modify: `tests/asgi/test_middleware_mutations.py`

`_extract_baggage_value` is a private function tested only indirectly via the full middleware. The two surviving mutants are:
1. `k.strip() == key` → `k == key` (key with leading/trailing space in baggage would match without strip)
2. `val if val else None` → `val if val else ''` (empty value would return empty string instead of None)

Additional mutations that may survive: `partition(";")[0]` → wrong partition char, `raw.split(",")` → wrong split char.

- [ ] **Step 1: Add _extract_baggage_value tests to test_middleware_mutations.py**

Add the following import and class at the end of `tests/asgi/test_middleware_mutations.py`:

```python
from provide.telemetry.asgi.middleware import _extract_baggage_value


# ── _extract_baggage_value: key stripping and value handling ──────────


class TestExtractBaggageValue:
    def test_strips_whitespace_from_baggage_key(self) -> None:
        """Kills: k.strip() == key → k == key.

        W3C baggage allows whitespace around keys. A mutant removing .strip()
        would fail to match 'session_id' because k would be ' session_id '.
        """
        scope: dict[str, object] = {"headers": [(b"baggage", b" session_id = abc123 ")]}
        result = _extract_baggage_value(scope, "session_id")
        assert result == "abc123"

    def test_empty_baggage_value_returns_none_not_empty_string(self) -> None:
        """Kills: val if val else None → val if val else '' (or just `return val`)."""
        scope: dict[str, object] = {"headers": [(b"baggage", b"session_id=")]}
        result = _extract_baggage_value(scope, "session_id")
        assert result is None

    def test_strips_w3c_properties_after_semicolon(self) -> None:
        """Kills: partition(';')[0] → partition(',')[0] or [1].

        W3C baggage: 'key=value;prop=propval' — semicolon-delimited metadata
        should be stripped so only 'key=value' remains.
        """
        scope: dict[str, object] = {"headers": [(b"baggage", b"session_id=abc123;ttl=30")]}
        result = _extract_baggage_value(scope, "session_id")
        assert result == "abc123"

    def test_finds_key_in_multi_pair_baggage_header(self) -> None:
        """Kills: raw.split(',') → raw.split(';') — wrong split char for pairs.

        Multiple baggage pairs are comma-separated. A mutant splitting on ';'
        would treat the whole header as one pair and fail to find the key.
        """
        scope: dict[str, object] = {
            "headers": [(b"baggage", b"other=x,session_id=target_val,more=y")]
        }
        result = _extract_baggage_value(scope, "session_id")
        assert result == "target_val"
```

- [ ] **Step 2: Run the middleware tests**

```bash
uv run python scripts/run_pytest_gate.py tests/asgi/test_middleware_mutations.py --no-cov -q
```

Expected: all tests pass.

- [ ] **Step 3: Run full Python test suite with coverage**

```bash
uv run python scripts/run_pytest_gate.py
```

Expected: all tests pass, 100% coverage maintained.

- [ ] **Step 4: Commit**

```bash
git add tests/asgi/test_middleware_mutations.py
git commit -m "test(py): cover _extract_baggage_value to kill middleware mutation survivors"
```

---

## Verification

After all 4 tasks, push to trigger CI. The Stryker (TypeScript) and mutmut (Python) mutation workflows run in CI — do not run them locally as they crash the context window.

```bash
git push
```

Monitor the `mutation-testing` CI workflow. All survivors should now be killed. If any survive, check the Stryker/mutmut report for the exact mutant line and add a targeted assertion.
