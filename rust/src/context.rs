// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::cell::RefCell;
use std::collections::{BTreeMap, HashMap};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, OnceLock};

use serde_json::Value;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ContextSnapshot {
    pub fields: BTreeMap<String, Value>,
    pub session_id: Option<String>,
    pub trace_id: Option<String>,
    pub span_id: Option<String>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
enum ContextScopeKey {
    Task(tokio::task::Id),
    Thread,
}

pub struct ContextGuard {
    key: ContextScopeKey,
    previous: ContextSnapshot,
    epoch: u64,
}

thread_local! {
    static THREAD_CONTEXT: RefCell<ContextSnapshot> = RefCell::new(ContextSnapshot::default());
}

static TASK_CONTEXTS: OnceLock<Mutex<HashMap<tokio::task::Id, ContextSnapshot>>> = OnceLock::new();
static CONTEXT_EPOCH: AtomicU64 = AtomicU64::new(0);

fn task_contexts() -> &'static Mutex<HashMap<tokio::task::Id, ContextSnapshot>> {
    TASK_CONTEXTS.get_or_init(|| Mutex::new(HashMap::new()))
}

fn current_scope_key() -> ContextScopeKey {
    tokio::task::try_id()
        .map(ContextScopeKey::Task)
        .unwrap_or(ContextScopeKey::Thread)
}

fn current_snapshot() -> ContextSnapshot {
    match current_scope_key() {
        ContextScopeKey::Task(task_id) => task_contexts()
            .lock()
            .expect("task context lock poisoned")
            .get(&task_id)
            .cloned()
            .unwrap_or_default(),
        ContextScopeKey::Thread => THREAD_CONTEXT.with(|ctx| ctx.borrow().clone()),
    }
}

fn set_snapshot_for_key(key: ContextScopeKey, snapshot: ContextSnapshot) {
    match key {
        ContextScopeKey::Task(task_id) => {
            task_contexts()
                .lock()
                .expect("task context lock poisoned")
                .insert(task_id, snapshot);
        }
        ContextScopeKey::Thread => {
            THREAD_CONTEXT.with(|ctx| {
                *ctx.borrow_mut() = snapshot;
            });
        }
    }
}

fn replace_snapshot(next: ContextSnapshot) -> ContextGuard {
    let key = current_scope_key();
    let previous = current_snapshot();
    let epoch = CONTEXT_EPOCH.load(Ordering::SeqCst);
    set_snapshot_for_key(key, next);
    ContextGuard {
        key,
        previous,
        epoch,
    }
}

pub fn get_context() -> BTreeMap<String, Value> {
    current_snapshot().fields
}

pub fn bind_context<I, K>(fields: I) -> ContextGuard
where
    I: IntoIterator<Item = (K, Value)>,
    K: Into<String>,
{
    let mut next = current_snapshot();
    for (key, value) in fields {
        next.fields.insert(key.into(), value);
    }
    replace_snapshot(next)
}

pub fn unbind_context(keys: &[&str]) -> ContextGuard {
    let mut next = current_snapshot();
    for key in keys {
        next.fields.remove(*key);
    }
    replace_snapshot(next)
}

pub fn clear_context() -> ContextGuard {
    let mut next = current_snapshot();
    next.fields.clear();
    replace_snapshot(next)
}

pub fn bind_session_context(session_id: impl Into<String>) -> ContextGuard {
    let mut next = current_snapshot();
    let session_id = session_id.into();
    next.session_id = Some(session_id.clone());
    next.fields
        .insert("session_id".to_string(), Value::String(session_id));
    replace_snapshot(next)
}

pub fn get_session_id() -> Option<String> {
    current_snapshot().session_id
}

pub fn clear_session_context() -> ContextGuard {
    let mut next = current_snapshot();
    next.session_id = None;
    next.fields.remove("session_id");
    replace_snapshot(next)
}

pub(crate) fn set_trace_context_internal(
    trace_id: Option<String>,
    span_id: Option<String>,
) -> ContextGuard {
    let mut next = current_snapshot();
    next.trace_id = trace_id;
    next.span_id = span_id;
    replace_snapshot(next)
}

pub(crate) fn trace_snapshot() -> ContextSnapshot {
    current_snapshot()
}

pub(crate) fn reset_context_for_tests() {
    CONTEXT_EPOCH.fetch_add(1, Ordering::SeqCst);
    THREAD_CONTEXT.with(|ctx| {
        *ctx.borrow_mut() = ContextSnapshot::default();
    });
    task_contexts()
        .lock()
        .expect("task context lock poisoned")
        .clear();
}

pub(crate) fn reset_trace_context_for_tests() {
    CONTEXT_EPOCH.fetch_add(1, Ordering::SeqCst);
    THREAD_CONTEXT.with(|ctx| {
        let mut snapshot = ctx.borrow_mut();
        snapshot.trace_id = None;
        snapshot.span_id = None;
    });
    let mut tasks = task_contexts().lock().expect("task context lock poisoned");
    for snapshot in tasks.values_mut() {
        snapshot.trace_id = None;
        snapshot.span_id = None;
    }
}

impl Drop for ContextGuard {
    fn drop(&mut self) {
        if CONTEXT_EPOCH.load(Ordering::SeqCst) == self.epoch {
            set_snapshot_for_key(self.key, self.previous.clone());
        }
    }
}
