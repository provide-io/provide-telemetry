// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Reporting reserved root fields whose caller value a stamped value replaced
//! (`reserved_root_fields.replacement_reporting` in spec/telemetry-api.yaml).
//!
//! Replacing a field silently loses the caller's data — a `version` meaning a
//! schema version, say — so each replacement adds to
//! `HealthSnapshot::reserved_field_replacements`, and the first replacement of
//! each field in the process logs one warning naming the field, never its
//! value. A record is built only once admission has passed, so a refused
//! record is neither counted nor warned about; the warning is logged while the
//! record is built, so it reaches the output just before the record.

use std::cell::Cell;
use std::collections::{BTreeMap, BTreeSet};
use std::sync::{LazyLock, Mutex};

use serde_json::Value;

use crate::health::increment_reserved_field_replacements;

/// Canonical order: the order replacements are warned about in.
pub(super) const RESERVED_FIELDS: [&str; 5] = ["service", "env", "version", "trace_id", "span_id"];
pub(super) const WARNING_EVENT: &str = "logger.reserved_field.replaced";
const WARNING_TARGET: &str = "provide.telemetry.logger";

static WARNED: LazyLock<Mutex<BTreeSet<&'static str>>> = LazyLock::new(Mutex::default);

thread_local! {
    // Set while this thread logs a warning. The warning is an ordinary record
    // and runs the same stamping, so a reserved field in bound context would
    // otherwise count again, against a record the caller never wrote.
    static WARNING: Cell<bool> = const { Cell::new(false) };
}

/// Whether stamping `stamped` under `key` replaces a different caller value.
pub(super) fn replaces(context: &BTreeMap<String, Value>, key: &str, stamped: &str) -> bool {
    context
        .get(key)
        .is_some_and(|caller| caller.as_str() != Some(stamped))
}

/// Count `replaced` and warn about each field replaced for the first time.
pub(super) fn report(replaced: &[&'static str]) {
    if replaced.is_empty() || WARNING.with(Cell::get) {
        return;
    }
    increment_reserved_field_replacements(replaced.len() as u64);
    let first: Vec<&'static str> = {
        let mut warned = crate::_lock::lock(&WARNED);
        RESERVED_FIELDS
            .into_iter()
            .filter(|field| replaced.contains(field) && warned.insert(*field))
            .collect()
    };
    if first.is_empty() {
        return;
    }
    WARNING.with(|flag| flag.set(true));
    for field in first {
        let fields = BTreeMap::from([("field".to_string(), Value::String(field.to_string()))]);
        super::log_event_with_fields("WARN", WARNING_TARGET, WARNING_EVENT, &fields);
    }
    WARNING.with(|flag| flag.set(false));
}

/// Forget which fields have been warned about (test helper).
pub(crate) fn reset_reserved_warnings() {
    crate::_lock::lock(&WARNED).clear();
}
