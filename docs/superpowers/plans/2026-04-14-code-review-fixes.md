# Code-Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve all 7 issues found in the cross-language code review: Rust log-bridge module-level gap, dot-hierarchy prefix-match inconsistency (Rust + Python), silent unknown-level parsing, O(n²) attribute cap, stale comment, misleading Python counter comment, and unhelpful Python error messages.

**Architecture:** Each fix is self-contained within one or two files. Rust fixes live in `rust/src/logger/mod.rs`, `rust/src/logger/processors.rs`, and `rust/src/config/parse.rs`. Python fix is in `src/provide/telemetry/logger/processors.py` and comment/message fixes in `src/provide/telemetry/logger/core.py` + `src/provide/telemetry/runtime.py`. Every fix follows strict TDD: failing test → implementation → green → commit.

**Tech Stack:** Rust (no new crates), Python 3.11 + structlog, Go (already complete — no changes needed), TypeScript (already correct — no changes needed).

---

## Files Modified

| File | Change |
|------|--------|
| `rust/src/logger/mod.rs` | Add unit tests; fix `effective_level_threshold` prefix semantics; fix `impl log::Log for Logger::enabled()` |
| `rust/src/logger/processors.rs` | Fix O(n²) attr cap; fix stale comment; add priority-key preservation test |
| `rust/src/config/parse.rs` | Warn on unknown level strings in `parse_module_levels` |
| `rust/tests/logger_test.rs` | Add integration test for `log` bridge + module override |
| `src/provide/telemetry/logger/processors.py` | Fix `_LevelFilter.__call__` prefix semantics |
| `tests/logger/test_logger_context_processors.py` | Add dot-hierarchy regression tests |
| `src/provide/telemetry/logger/core.py` | Fix misleading comment about sampling counter |
| `src/provide/telemetry/runtime.py` | Improve RuntimeError messages |

---

## Task 1: Rust — Failing unit tests for dot-hierarchy prefix matching

`effective_level_threshold` currently uses `target.starts_with(prefix)` which is a raw string prefix. This lets `"foobar"` match prefix `"foo"`, which is wrong. The correct semantics (matching Go and TypeScript) require exact match OR `target.starts_with(prefix + ".")`.

**Files:**
- Modify: `rust/src/logger/mod.rs` (add `#[cfg(test)] mod tests` block)

- [ ] **Step 1: Add the failing unit tests**

Append this block to the bottom of `rust/src/logger/mod.rs` (before the final `}`):

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn cfg_with_module_level(module: &str, level: &str) -> crate::config::LoggingConfig {
        let mut module_levels = HashMap::new();
        module_levels.insert(module.to_string(), level.to_string());
        crate::config::LoggingConfig {
            level: "INFO".to_string(),
            module_levels,
            ..crate::config::LoggingConfig::default()
        }
    }

    // ── Issue #2: dot-hierarchy prefix matching ───────────────────────────────

    #[test]
    fn effective_level_does_not_match_partial_string() {
        // "foobar" must NOT match prefix "foo" — no dot separator between them
        let cfg = cfg_with_module_level("foo", "DEBUG");
        // INFO = 2, so global threshold applies
        assert_eq!(
            effective_level_threshold("foobar", &cfg),
            2,
            "foobar must not match prefix foo (no dot separator)"
        );
    }

    #[test]
    fn effective_level_matches_dot_separated_child() {
        // "foo.bar" starts with "foo." → should pick up DEBUG override
        let cfg = cfg_with_module_level("foo", "DEBUG");
        assert_eq!(
            effective_level_threshold("foo.bar", &cfg),
            1,
            "foo.bar must match prefix foo via dot separator"
        );
    }

    #[test]
    fn effective_level_matches_exact_module_name() {
        // "foo" == "foo" → exact match → DEBUG override applies
        let cfg = cfg_with_module_level("foo", "DEBUG");
        assert_eq!(effective_level_threshold("foo", &cfg), 1, "exact name must match");
    }

    #[test]
    fn effective_level_empty_prefix_matches_everything() {
        // empty prefix is a catch-all
        let cfg = cfg_with_module_level("", "DEBUG");
        assert_eq!(
            effective_level_threshold("anything.at.all", &cfg),
            1,
            "empty prefix must match any target"
        );
    }

    #[test]
    fn effective_level_longest_prefix_wins() {
        let mut module_levels = HashMap::new();
        module_levels.insert("foo".to_string(), "WARN".to_string());
        module_levels.insert("foo.bar".to_string(), "DEBUG".to_string());
        let cfg = crate::config::LoggingConfig {
            level: "INFO".to_string(),
            module_levels,
            ..crate::config::LoggingConfig::default()
        };
        // "foo.bar.baz" matches both "foo" and "foo.bar"; "foo.bar" is longer → DEBUG wins
        assert_eq!(
            effective_level_threshold("foo.bar.baz", &cfg),
            1,
            "longer prefix must win over shorter"
        );
    }
}
```

- [ ] **Step 2: Verify the tests fail with the current implementation**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry/rust
cargo test effective_level_does_not_match_partial_string 2>&1 | tail -10
```

Expected: FAIL — `effective_level_does_not_match_partial_string` asserts `2` but gets `1` because `"foobar".starts_with("foo")` is currently `true`.

- [ ] **Step 3: Commit the failing tests**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry
git add rust/src/logger/mod.rs
git commit -m "test(rust): failing tests for dot-hierarchy prefix matching in effective_level_threshold"
```

---

## Task 2: Rust — Fix `effective_level_threshold` to dot-hierarchy semantics

**Files:**
- Modify: `rust/src/logger/mod.rs:126-136`

- [ ] **Step 1: Replace the prefix-matching line**

In `effective_level_threshold`, change:
```rust
if target.starts_with(prefix.as_str()) && prefix.len() > best_prefix_len {
```
to:
```rust
let matches = prefix.is_empty()
    || target == prefix.as_str()
    || target.starts_with(&format!("{prefix}."));
if matches && prefix.len() > best_prefix_len {
```

The full function after the change:
```rust
fn effective_level_threshold(target: &str, config: &crate::config::LoggingConfig) -> u8 {
    let mut best_prefix_len = 0;
    let mut threshold = level_order(&config.level);
    for (prefix, lvl) in &config.module_levels {
        let matches = prefix.is_empty()
            || target == prefix.as_str()
            || target.starts_with(&format!("{prefix}."));
        if matches && prefix.len() > best_prefix_len {
            best_prefix_len = prefix.len();
            threshold = level_order(lvl);
        }
    }
    threshold
}
```

- [ ] **Step 2: Run the unit tests**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry/rust
cargo test effective_level 2>&1 | tail -15
```

Expected: all 5 `effective_level_*` tests PASS.

- [ ] **Step 3: Run the full Rust test suite**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry/rust
cargo test 2>&1 | tail -20
```

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry
git add rust/src/logger/mod.rs
git commit -m "fix(rust): effective_level_threshold uses dot-hierarchy prefix matching (aligns with Go/TypeScript)"
```

---

## Task 3: Rust — Failing integration test for `log` bridge + module override

Issue #1: `impl log::Log for Logger::enabled()` only checks the global level, not `module_levels`. Records from a module with a looser override are dropped before `log_event()` ever runs.

**Files:**
- Modify: `rust/tests/logger_test.rs`

- [ ] **Step 1: Add the failing integration test**

Add after the existing `logger_test_log_trait_respects_level_filter` test (around line 275):

```rust
#[test]
fn logger_test_log_trait_respects_module_level_override() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    let _ = set_as_global_logger();
    // Global INFO, but module "tests.mod_override" gets DEBUG.
    // Without the fix, enabled() uses global INFO and drops the DEBUG record
    // before log_event() can apply the module override.
    let cfg = provide_telemetry::LoggingConfig {
        level: "INFO".to_string(),
        fmt: "json".to_string(),
        include_timestamp: false,
        module_levels: {
            let mut m = std::collections::HashMap::new();
            m.insert("tests.mod_override".to_string(), "DEBUG".to_string());
            m
        },
        ..provide_telemetry::LoggingConfig::default()
    };
    configure_logging(cfg);
    enable_json_capture_for_tests();

    // Module override allows DEBUG — must reach the event store.
    log::debug!(target: "tests.mod_override", "debug.should.pass");
    // No override — global INFO applies — must be filtered.
    log::debug!(target: "tests.other_module", "debug.must.be.filtered");

    let raw = take_json_capture();
    reset_logging_config_for_tests();
    Logger::drain_events_for_tests();

    let output = String::from_utf8(raw).expect("utf8");
    assert!(
        output.contains("debug.should.pass"),
        "DEBUG must pass for module with DEBUG override; got: {output}"
    );
    assert!(
        !output.contains("debug.must.be.filtered"),
        "DEBUG must be filtered for module without override; got: {output}"
    );
}
```

- [ ] **Step 2: Verify the test fails**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry/rust
cargo test logger_test_log_trait_respects_module_level_override 2>&1 | tail -10
```

Expected: FAIL — `"debug.should.pass"` is not in output because `enabled()` returns false before `log_event()` sees the module override.

- [ ] **Step 3: Commit the failing test**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry
git add rust/tests/logger_test.rs
git commit -m "test(rust): failing integration test for log-bridge module-level override gap"
```

---

## Task 4: Rust — Fix `impl log::Log for Logger::enabled()` to respect `module_levels`

**Files:**
- Modify: `rust/src/logger/mod.rs:405-408`

- [ ] **Step 1: Replace the `enabled()` method**

Replace the current `enabled` implementation:
```rust
fn enabled(&self, metadata: &log::Metadata<'_>) -> bool {
    let config = active_logging_config();
    metadata.level() <= level_str_to_log_filter(&config.level)
}
```

with:
```rust
fn enabled(&self, metadata: &log::Metadata<'_>) -> bool {
    let config = active_logging_config();
    // Map log::Level to our severity order (TRACE=0 … ERROR=4) and compare
    // against the effective threshold for this target, which respects
    // per-module overrides via longest-dot-hierarchy-prefix match.
    let record_order: u8 = match metadata.level() {
        log::Level::Error => 4,
        log::Level::Warn  => 3,
        log::Level::Info  => 2,
        log::Level::Debug => 1,
        log::Level::Trace => 0,
    };
    record_order >= effective_level_threshold(metadata.target(), &config)
}
```

- [ ] **Step 2: Run the integration test**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry/rust
cargo test logger_test_log_trait_respects_module_level_override 2>&1 | tail -10
```

Expected: PASS.

- [ ] **Step 3: Run the full Rust test suite**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry/rust
cargo test 2>&1 | tail -20
```

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry
git add rust/src/logger/mod.rs
git commit -m "fix(rust): log::Log::enabled() now respects per-module level overrides via dot-hierarchy prefix match"
```

---

## Task 5: Rust — Warn on unknown level strings in `parse_module_levels`

Issue #7: `"foo=VERBOSE"` is silently accepted and defaults to INFO at runtime. Users who misconfigure `PROVIDE_LOG_MODULE_LEVELS` with a typo get silent wrong behavior.

**Files:**
- Modify: `rust/src/config/parse.rs`

- [ ] **Step 1: Add a unit test for the unknown-level path**

Add to the existing `#[cfg(test)] mod tests` block at the bottom of `rust/src/config/parse.rs` (or create one if absent):

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_module_levels_inserts_unknown_level_and_warns() {
        // Unknown level strings are still inserted (runtime defaults to INFO),
        // but a warning must be emitted to stderr. We can't capture eprintln!
        // in standard Rust tests, so we verify the map entry is present to
        // ensure the warning path doesn't accidentally drop the entry.
        let map = parse_module_levels("foo=VERBOSE,bar=DEBUG");
        assert_eq!(
            map.get("foo").map(String::as_str),
            Some("VERBOSE"),
            "unknown level must still be inserted into the map"
        );
        assert_eq!(
            map.get("bar").map(String::as_str),
            Some("DEBUG"),
            "valid entry must not be affected by adjacent unknown entry"
        );
    }

    #[test]
    fn parse_module_levels_valid_levels_no_warning() {
        let map =
            parse_module_levels("a=TRACE,b=DEBUG,c=INFO,d=WARN,e=WARNING,f=ERROR,g=CRITICAL,h=FATAL");
        assert_eq!(map.len(), 8, "all valid levels must parse");
    }

    #[test]
    fn parse_module_levels_empty_input() {
        let map = parse_module_levels("");
        assert!(map.is_empty());
    }

    #[test]
    fn parse_module_levels_skips_empty_module_name() {
        let map = parse_module_levels("=DEBUG,pkg=INFO");
        assert!(!map.contains_key(""), "empty module name must be skipped");
        assert_eq!(map.get("pkg").map(String::as_str), Some("INFO"));
    }

    #[test]
    fn parse_module_levels_skips_empty_level() {
        let map = parse_module_levels("pkg=,other=DEBUG");
        assert!(!map.contains_key("pkg"), "empty level must be skipped");
        assert_eq!(map.get("other").map(String::as_str), Some("DEBUG"));
    }

    #[test]
    fn parse_module_levels_trims_whitespace() {
        let map = parse_module_levels("  pkg = DEBUG , other = INFO ");
        assert_eq!(map.get("pkg").map(String::as_str), Some("DEBUG"));
        assert_eq!(map.get("other").map(String::as_str), Some("INFO"));
    }
}
```

- [ ] **Step 2: Run the tests (they should pass already for most, but verify)**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry/rust
cargo test parse_module_levels 2>&1 | tail -15
```

Expected: PASS (these tests don't require the warning, just the map behavior).

- [ ] **Step 3: Add the warning in `parse_module_levels`**

Replace the function body in `rust/src/config/parse.rs:137-153`:

```rust
/// Parse `PROVIDE_LOG_MODULE_LEVELS` — comma-separated `module=LEVEL` pairs.
/// Example: `"provide.server=DEBUG,asyncio=WARNING"`.
/// Unknown level strings emit a stderr warning and default to INFO at runtime.
pub(super) fn parse_module_levels(raw: &str) -> HashMap<String, String> {
    const VALID_LEVELS: &[&str] =
        &["TRACE", "DEBUG", "INFO", "WARN", "WARNING", "ERROR", "CRITICAL", "FATAL"];
    let mut map = HashMap::new();
    for pair in raw.split(',') {
        let pair = pair.trim();
        if pair.is_empty() {
            continue;
        }
        if let Some((module, level)) = pair.split_once('=') {
            let module = module.trim().to_string();
            let level = level.trim().to_uppercase();
            if !module.is_empty() && !level.is_empty() {
                if !VALID_LEVELS.contains(&level.as_str()) {
                    eprintln!(
                        "provide_telemetry: unknown log level {level:?} for module {module:?} \
                         in PROVIDE_LOG_MODULE_LEVELS; will default to INFO at runtime"
                    );
                }
                map.insert(module, level);
            }
        }
    }
    map
}
```

- [ ] **Step 4: Run the full parse test suite**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry/rust
cargo test parse_module_levels 2>&1 | tail -15
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry
git add rust/src/config/parse.rs
git commit -m "fix(rust): parse_module_levels warns on unknown level strings via eprintln"
```

---

## Task 6: Rust — Fix O(n²) attribute cap with HashSet + add priority-key preservation test

Issue #6: `Vec::contains` is O(n) per lookup. Also, there is no test verifying that priority keys survive capping.

**Files:**
- Modify: `rust/src/logger/processors.rs`

- [ ] **Step 1: Add a failing test for priority-key preservation**

Add to the `#[cfg(test)] mod tests` block in `rust/src/logger/processors.rs`:

```rust
#[test]
fn harden_input_preserves_priority_keys_when_over_cap() {
    let mut event = make_event("INFO", "test");
    // Add 10 generic keys that will be over the cap of 5
    for i in 0..10 {
        event.context.insert(format!("extra_{i:02}"), Value::String("x".to_string()));
    }
    // Add a priority key — must survive even though we're over cap
    event.context.insert("trace_id".to_string(), Value::String("tid-abc".to_string()));
    event.context.insert("service".to_string(), Value::String("svc".to_string()));
    // Cap at 4: 2 priority + 2 generic
    harden_input(&mut event, 1024, 4);
    assert_eq!(event.context.len(), 4, "must cap at 4");
    assert!(
        event.context.contains_key("trace_id"),
        "trace_id (priority) must survive capping"
    );
    assert!(
        event.context.contains_key("service"),
        "service (priority) must survive capping"
    );
}
```

- [ ] **Step 2: Run the test to confirm it already passes (the logic is correct, just O(n²))**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry/rust
cargo test harden_input_preserves_priority_keys 2>&1 | tail -10
```

Expected: PASS (confirming the behavior is correct; we're fixing performance, not behavior).

- [ ] **Step 3: Replace the O(n²) implementation with HashSet + BTreeMap::retain**

Replace the attribute-cap block in `harden_input` (`rust/src/logger/processors.rs:109-139`) — the section starting with `// Cap attribute count.`:

```rust
    // Cap attribute count. Priority keys (service identity, trace context,
    // DARS fields) are preserved; excess is trimmed from the remainder
    // in BTreeMap alphabetical order (deterministic).
    if max_attr_count > 0 && event.context.len() > max_attr_count {
        use std::collections::HashSet;
        const PRIORITY_KEYS: &[&str] = &[
            "service", "env", "version", "trace_id", "span_id", "session_id",
            "domain", "action", "resource", "status", "error_fingerprint",
        ];
        let priority_set: HashSet<&str> = PRIORITY_KEYS.iter().copied().collect();

        // Collect priority keys that are actually present.
        let mut keep: HashSet<String> = event
            .context
            .keys()
            .filter(|k| priority_set.contains(k.as_str()))
            .cloned()
            .collect();

        // Fill remaining slots from non-priority keys (alphabetical — BTreeMap order).
        for key in event.context.keys() {
            if keep.len() >= max_attr_count {
                break;
            }
            if !priority_set.contains(key.as_str()) {
                keep.insert(key.clone());
            }
        }

        // Drop everything not in `keep` — O(n) with HashSet lookup.
        event.context.retain(|k, _| keep.contains(k));
    }
```

- [ ] **Step 4: Run all processor tests**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry/rust
cargo test -- --test-output immediate 2>&1 | grep -E "test |FAILED|ok$" | tail -30
```

Expected: all tests PASS.

- [ ] **Step 5: Fix the stale comment in `process_event` (Issue #3)**

In `rust/src/logger/processors.rs:47-51`, change:
```rust
    // 5. Schema enforcement (validate event name when strict mode is on)
    // Annotates with _schema_error instead of dropping — this is the new
    // cross-language standard (Python/TS/Go will be updated to match).
    enforce_schema(event);
```
to:
```rust
    // 5. Schema enforcement (validate event name when strict mode is on)
    // Annotates with _schema_error instead of dropping — cross-language
    // standard: all four languages (Python/TypeScript/Go/Rust) annotate and emit.
    enforce_schema(event);
```

Also in `enforce_schema` docstring (`rust/src/logger/processors.rs:194-199`), change:
```rust
/// When strict schema mode is on, validate the event message as a
/// dot-joined event name. Invalid names get a `_schema_error` context
/// field — the event is always emitted (never dropped), so telemetry
/// is never lost. This is the new cross-language standard; Python/TS/Go
/// will be updated from their current drop-on-failure behaviour to match.
```
to:
```rust
/// When strict schema mode is on, validate the event message as a
/// dot-joined event name. Invalid names get a `_schema_error` context
/// field — the event is always emitted (never dropped), so telemetry
/// is never lost. Cross-language standard: all four languages annotate
/// and emit rather than drop.
```

- [ ] **Step 6: Run the full Rust test suite**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry/rust
cargo test 2>&1 | tail -10
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry
git add rust/src/logger/processors.rs
git commit -m "fix(rust): O(n2) attr cap replaced with HashSet; fix stale cross-language comment"
```

---

## Task 7: Python — Failing tests for dot-hierarchy prefix matching in `_LevelFilter`

Python's `_LevelFilter.__call__` uses `logger_name.startswith(prefix)` — same raw-string-prefix bug as Rust had. This means `"foobar"` matches prefix `"foo"`, which is wrong.

**Files:**
- Modify: `tests/logger/test_logger_context_processors.py`

- [ ] **Step 1: Add the failing tests**

Add to the end of `tests/logger/test_logger_context_processors.py`:

```python
# ── _LevelFilter dot-hierarchy prefix matching (Issue #2) ──────────────────

class TestLevelFilterPrefixSemantics:
    """_LevelFilter must use dot-hierarchy matching, not raw string prefix."""

    def _make_filter(
        self, default: str, overrides: dict[str, str]
    ) -> "_LevelFilter":
        from provide.telemetry.logger.processors import _LevelFilter

        return _LevelFilter(default, overrides)

    def test_partial_string_does_not_match(self) -> None:
        # "foobar" must NOT match prefix "foo" — no dot separator
        f = self._make_filter("INFO", {"foo": "DEBUG"})
        # If it wrongly matched, DEBUG event for "foobar" would pass; it should be dropped.
        import structlog

        with pytest.raises(structlog.DropEvent):
            f(None, "debug", {"event": "x", "level": "debug", "logger_name": "foobar"})

    def test_dot_child_matches(self) -> None:
        # "foo.bar" starts with "foo." → DEBUG override applies → passes through
        f = self._make_filter("INFO", {"foo": "DEBUG"})
        result = f(None, "debug", {"event": "x", "level": "debug", "logger_name": "foo.bar"})
        assert result["event"] == "x"

    def test_exact_name_matches(self) -> None:
        # "foo" == "foo" → exact match → DEBUG override applies → passes through
        f = self._make_filter("INFO", {"foo": "DEBUG"})
        result = f(None, "debug", {"event": "x", "level": "debug", "logger_name": "foo"})
        assert result["event"] == "x"

    def test_empty_prefix_matches_all(self) -> None:
        # Empty prefix is a catch-all → DEBUG for everything
        f = self._make_filter("INFO", {"": "DEBUG"})
        result = f(None, "debug", {"event": "x", "level": "debug", "logger_name": "anything.at.all"})
        assert result["event"] == "x"

    def test_longer_prefix_wins(self) -> None:
        # "foo.bar.baz" matches both "foo" (WARN) and "foo.bar" (DEBUG)
        # Longer prefix "foo.bar" must win → DEBUG → passes
        f = self._make_filter("INFO", {"foo": "WARN", "foo.bar": "DEBUG"})
        result = f(None, "debug", {"event": "x", "level": "debug", "logger_name": "foo.bar.baz"})
        assert result["event"] == "x"

    def test_non_matching_module_uses_global(self) -> None:
        # "other.module" has no match → global INFO → debug is dropped
        f = self._make_filter("INFO", {"foo": "DEBUG"})
        import structlog

        with pytest.raises(structlog.DropEvent):
            f(None, "debug", {"event": "x", "level": "debug", "logger_name": "other.module"})
```

- [ ] **Step 2: Verify the tests fail**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry
uv run python -m pytest tests/logger/test_logger_context_processors.py::TestLevelFilterPrefixSemantics -x -q --no-cov 2>&1 | tail -15
```

Expected: `test_partial_string_does_not_match` FAILS because `"foobar".startswith("foo")` is `True` so the DEBUG event passes instead of being dropped.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/logger/test_logger_context_processors.py
git commit -m "test(python): failing tests for dot-hierarchy prefix matching in _LevelFilter"
```

---

## Task 8: Python — Fix `_LevelFilter.__call__` to dot-hierarchy semantics

**Files:**
- Modify: `src/provide/telemetry/logger/processors.py:242-253`

- [ ] **Step 1: Replace the matching logic in `__call__`**

In `_LevelFilter.__call__`, replace:
```python
        threshold = self._default_numeric
        for prefix in self._sorted_prefixes:
            if logger_name.startswith(prefix):
                threshold = self._module_numerics[prefix]
                break
```
with:
```python
        threshold = self._default_numeric
        for prefix in self._sorted_prefixes:
            if prefix == "" or logger_name == prefix or logger_name.startswith(prefix + "."):
                threshold = self._module_numerics[prefix]
                break
```

- [ ] **Step 2: Run the new tests**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry
uv run python -m pytest tests/logger/test_logger_context_processors.py::TestLevelFilterPrefixSemantics -v --no-cov 2>&1 | tail -20
```

Expected: all 6 tests PASS.

- [ ] **Step 3: Run the full Python test suite (no coverage enforcement yet)**

```bash
uv run python -m pytest tests/logger/ -q --no-cov 2>&1 | tail -10
```

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add src/provide/telemetry/logger/processors.py
git commit -m "fix(python): _LevelFilter uses dot-hierarchy prefix matching (aligns with Go/TypeScript/Rust)"
```

---

## Task 9: Python — Fix misleading comment and improve error messages

Issues #4 and #5.

**Files:**
- Modify: `src/provide/telemetry/logger/core.py:272-275`
- Modify: `src/provide/telemetry/runtime.py:164-167`, `src/provide/telemetry/runtime.py:215-218`

- [ ] **Step 1: Fix the misleading sampling-counter comment in `core.py`**

In `_configure_logging_inner` (around line 272), replace:
```python
            # Schema validation runs BEFORE sampling so records rejected by
            # validate_required_keys / validate_event_name don't inflate the
            # emitted_logs counter (apply_sampling increments it on acceptance).
            enforce_event_schema(config),
```
with:
```python
            # Schema validation runs BEFORE sampling. Schema-invalid records are now
            # annotated with _schema_error and continue through the pipeline — they
            # DO contribute to emitted_logs. The ordering ensures _schema_error is
            # set before apply_sampling evaluates the record.
            enforce_event_schema(config),
```

- [ ] **Step 2: Improve the RuntimeError messages in `runtime.py`**

In `update_runtime_config` (around line 164), replace:
```python
                raise RuntimeError(
                    "provider-changing logging reconfiguration is unsupported after OpenTelemetry log providers "
                    "are installed; restart the process and call setup_telemetry() with the new config"
                )
```
with:
```python
                raise RuntimeError(
                    "provider-changing logging reconfiguration is unsupported after OpenTelemetry log providers "
                    "are installed. Use reconfigure_telemetry() for full provider replacement, or restart the "
                    "process and call setup_telemetry() with the new config."
                )
```

In `reconfigure_telemetry` (around line 215), replace:
```python
                raise RuntimeError(
                    "provider-changing logging reconfiguration is unsupported after OpenTelemetry log providers are "
                    "installed; restart the process and call setup_telemetry() with the new config"
                )
```
with:
```python
                raise RuntimeError(
                    "provider-changing logging reconfiguration (endpoint/headers/timeout change) is unsupported "
                    "after OpenTelemetry log providers are installed. Use reconfigure_telemetry() for full "
                    "provider replacement, or restart the process and call setup_telemetry() with the new config."
                )
```

- [ ] **Step 3: Update the existing RuntimeError message tests to match new text**

Search for test assertions against the old error message text:

```bash
grep -rn "provider-changing logging" /Users/tim/code/gh/provide-io/provide-telemetry/tests/ 2>/dev/null
```

Update any `match=` or `assert ... in str(exc)` patterns to match the new messages. The key distinguishing fragment `"provider-changing logging reconfiguration is unsupported"` should remain in the new messages, so assertions using `match=r"provider-changing"` will still pass. If any test matches the exact tail `"restart the process"` it needs updating to `"restart the process and call setup_telemetry()"`.

- [ ] **Step 4: Run the runtime tests**

```bash
uv run python -m pytest tests/runtime/ -q --no-cov 2>&1 | tail -10
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/provide/telemetry/logger/core.py src/provide/telemetry/runtime.py
git commit -m "fix(python): correct misleading sampling comment; improve provider-change RuntimeError messages"
```

---

## Task 10: Final verification — full test suites + coverage + lint

- [ ] **Step 1: Python full suite with coverage**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry
uv run python scripts/run_pytest_gate.py 2>&1 | tail -20
```

Expected: 100% branch coverage, all tests PASS.

- [ ] **Step 2: Python lint and type-check**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests
```

Expected: no errors.

- [ ] **Step 3: Rust full suite**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry/rust
cargo test 2>&1 | tail -10
```

Expected: all tests PASS.

- [ ] **Step 4: Rust lint**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry/rust
cargo clippy -- -D warnings 2>&1 | tail -10
```

Expected: no warnings.

- [ ] **Step 5: Go full suite**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry/go
go test ./... -race 2>&1 | tail -10
```

Expected: all tests PASS (Go already correct — verify nothing regressed).

- [ ] **Step 6: TypeScript full suite**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry/typescript
npm test 2>&1 | tail -10
```

Expected: all tests PASS (TypeScript unchanged — verify nothing regressed).

- [ ] **Step 7: Verify LOC constraints**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry
uv run python scripts/check_max_loc.py --max-lines 500
```

Expected: no file over 500 lines.

- [ ] **Step 8: Final commit summarising the fix batch**

```bash
git add -u
git commit -m "chore: all code-review fixes verified — 7 issues resolved across Rust and Python"
```

---

## Self-Review Checklist

| Issue | Task | Status |
|-------|------|--------|
| #1 Rust log bridge ignores module_levels in enabled() | Tasks 3+4 | ✅ |
| #2 Rust raw-string prefix (not dot-hierarchy) | Tasks 1+2 | ✅ |
| #2 Python raw-string prefix (not dot-hierarchy) | Tasks 7+8 | ✅ |
| #3 Stale Rust comment (Go "will be updated") | Task 6, Step 5 | ✅ |
| #4 Python misleading sampling-counter comment | Task 9, Step 1 | ✅ |
| #5 Python unhelpful RuntimeError messages | Task 9, Steps 2-3 | ✅ |
| #6 Rust O(n²) attr cap | Task 6, Steps 3-4 | ✅ |
| #7 Rust silent unknown level string | Task 5 | ✅ |
| Go per-module filtering | Already implemented + dot-hierarchy correct | N/A |
| TypeScript prefix semantics | Already correct | N/A |
