# Rust Changelog

Releases of the crates.io package `provide-telemetry`. The root `CHANGELOG.md`
covers all five languages; this file covers only what shipped to crates.io.
Versions 0.5.x and 0.6.0 predate this file — see the root changelog for what
they contained.

---

## [0.8.1] — 2026-08-22

### Breaking

- **`PROVIDE_CONSENT_LEVEL` fails closed on a value it does not recognise.**
  A set, non-empty value other than `FULL`, `FUNCTIONAL`, `MINIMAL` or `NONE`
  (trimmed, case-insensitive) sets consent to `NONE` on every read and writes
  one warning per process to stderr naming the value, e.g.
  `[provide-telemetry] PROVIDE_CONSENT_LEVEL="NOEN" is not one of FULL,
  FUNCTIONAL, MINIMAL, NONE; consent set to NONE (fail-closed)`. The warning
  deliberately bypasses the crate's own logger, which the `NONE` it just
  applied would silence. A process whose environment carries a misspelled
  opt-out therefore stops collecting instead of carrying on at `FULL` -- the
  one failure an opt-out control must not have. Unset and blank (empty or
  whitespace-only) remain no-ops, so `PROVIDE_CONSENT_LEVEL=` in a compose
  file still changes nothing. `reset_consent_for_tests` re-arms the warning.
  The other four SDKs make the same change; the runtime probe
  (`consent_env_invalid_fails_closed`) pins it cross-language.

### Added

- `load_consent_from_env`, exported from the crate root. Reads
  `PROVIDE_CONSENT_LEVEL` (trimmed, case-insensitive; `FULL`, `FUNCTIONAL`,
  `MINIMAL` or `NONE`) and applies it; an unset or blank value leaves the
  current level untouched, and an unrecognised one fails closed (see
  Breaking). `setup_telemetry` calls it on its first, installing pass and
  `get_logger` calls it before setup has run, so an operator opt-out now takes
  effect in Rust as it already did in the other four SDKs. A level set in code
  after setup is never clobbered.
- `DEFAULT_TRUNCATE_TO` (8) and `impl Default for PIIRule`, so
  `PIIRule { path, mode: PIIMode::Truncate, ..Default::default() }` truncates
  to the spec default rather than requiring a limit to be spelled out.

### Fixed

- `PIIMode::Hash` of a non-string value now hashes its RFC 8785 canonical
  JSON, produced by the same canonicaliser the receipts use, instead of its
  `Display` text. The two differ for floats (`2.0` versus `2`) and key order,
  so digests of booleans, null, numbers and objects now match the other SDKs.

## [0.8.0] — 2026-08-19

### Breaking

- **`PROVIDE_LOG_LEVEL=CRITICAL` now excludes `ERROR` records.** `level_order`
  folded `CRITICAL` and `FATAL` onto `ERROR`, so a CRITICAL threshold admitted
  ERROR and the ladder's top two levels were indistinguishable. `FATAL` narrows
  the same way, from an ERROR threshold to a CRITICAL one.

- **`Logger::log(&str, &str)` normalises the level it publishes.**
  `log("warning", m)` now records `WARN` and `log("bogus", m)` records `INFO`.
  It used to pass the caller's string through verbatim, which made this the
  only door in any of the five ports that could put a level no consumer
  recognises onto the wire, and made it disagree with `warn()` about how to
  spell rank 3. `log_fields` and `log_event` normalise too.

### Added

- `LogSeverity`, `parse_level`, `try_parse_level` and `level_order`, exported
  from the crate root. `parse_level` takes the fallback as an argument — Rust
  has no default arguments, so every call site states what an unrecognised
  token becomes.
- `Logger::log_at(LogSeverity, &str)` and `Logger::log_at_fields`. Named
  `log_at` because `log` was already taken by the string form, which keeps its
  signature. `Level` was unavailable: `log::Level` is in scope in the same
  module.

### Fixed

- Consent ranks through the one shared table rather than a second local copy.
- The `log` crate bridge had the ladder written twice — once as bare numbers
  for the threshold test, once as strings for the record. Now one mapping.

## [0.7.2] — 2026-08-16

### Fixed

- **Secret redaction kept only the first match in a value.** A string
  carrying two credentials lost the first and emitted the second intact.
  A filesystem path earlier in the string could also shield a genuine
  credential behind it, because the path exemption was applied to the
  first match and then abandoned the whole value. Every pattern now runs
  across the whole value, each match is judged on its own token, and the
  surviving spans are merged and replaced right to left.

## [0.7.0] — 2026-08-14

### Changed

- **BREAKING: the facade takes optional arguments.**
  `setup_telemetry(Option<TelemetryConfig>)`, `flush_telemetry(Option<f64>)`
  and `shutdown_telemetry(Option<f64>)` — there was previously no way to
  inject a config or bound a drain from Rust at any layer, capabilities the
  other SDKs all had. The caller's deadline threads into the bounded drain
  and overrides the configured one; shutdown drains under it before teardown.
- **BREAKING: receipts are canonical and need a sink.**
  `enable_receipts(bool, Option<&str>, Option<&str>)` becomes
  `enable_receipts(ReceiptOptions) -> Result<(), ConfigurationError>`;
  enabling receipts without a sink is an error rather than signing one per
  redaction and discarding it. `receipts::emit_receipt` is repurposed from
  the redaction hook to sink delivery with failure accounting (the hook is
  now crate-private and takes a `serde_json::Value` — pre-stringifying was
  the bug). `original_hash` is SHA-256 over RFC 8785 canonical JSON rather
  than `Value::to_string()`, so every previously issued receipt hashes
  differently; all seven `spec/receipt_fixtures.yaml` vectors reproduce
  byte-for-byte. `HealthSnapshot` gains `receipt_failures` (25 → 26 fields,
  breaks exhaustive struct literals), and the receipt timestamp is
  fixed-width UTC instead of `SystemTime`'s debug format.

### Fixed

- **Drain outcomes are honest.** The bounded drains no longer panic, a
  zero-second budget times out instead of hanging, and an in-deadline
  exporter rejection reports `failed` rather than `timed_out`.
- **`ProviderImmutableError` is actually produced.** The type was declared
  but no code path returned it; the rejection path now does, via a
  `TelemetryErrorKind` callers can branch on.
- **Baggage keys are RFC 7230 tokens.** A newline inside an inbound baggage
  key could forge a log record through the bare-key render path;
  `parse_baggage` rejects non-token keys and strips control characters from
  values, and hardening covers keys as well as values.
- **`tracestate` is validated against the W3C list-member grammar**; one bad
  member discards the whole header instead of forwarding CRLF to the next
  hop.
- **Control stripping matches the other SDKs** — exactly the C0/C1 classes
  the others strip, applied before truncation rather than after.
- **Credentialed OTLP endpoints are accepted** — the userinfo colon in
  `https://user:pw@collector.example` was read as an empty-port separator
  and the endpoint refused.

### Added

- **`async_blocking_risk` counters move.** `Handle::try_current()` on the
  caller's thread detects a synchronous `flush_telemetry`/
  `shutdown_telemetry` parked on a Tokio worker — measured on the caller's
  thread, not inside the drain primitives, which offload to fresh OS threads
  where the check is always negative.
- **Propagation fuzzing** via proptest over traceparent/tracestate/baggage
  with the shared cross-language invariants (no panic on any bytes, hex
  all-or-nothing ids, token keys, control-free values).
