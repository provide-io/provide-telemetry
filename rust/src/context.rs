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

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Hash)]
enum ContextScopeKey {
    Task(tokio::task::Id),
    #[default]
    Thread,
}

#[derive(Default)]
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

#[cfg_attr(test, mutants::skip)] // Equivalent mutants only swap in Mutex::default().
fn empty_task_contexts_mutex() -> Mutex<HashMap<tokio::task::Id, ContextSnapshot>> {
    Mutex::new(HashMap::new())
}

#[cfg_attr(test, mutants::skip)] // cargo-mutants synthesizes tokio::task::Id::default(), which cannot compile.
fn task_contexts() -> &'static Mutex<HashMap<tokio::task::Id, ContextSnapshot>> {
    TASK_CONTEXTS.get_or_init(empty_task_contexts_mutex)
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
            let mut map = task_contexts().lock().expect("task context lock poisoned");
            if snapshot == ContextSnapshot::default() {
                // Remove the entry when restoring to default to prevent unbounded growth
                map.remove(&task_id);
            } else {
                map.insert(task_id, snapshot);
            }
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

#[cfg(test)]
mod tests {
    use super::*;

    use serde_json::json;

    use crate::testing::acquire_test_state_lock;

    #[test]
    fn context_test_bind_context_roundtrip_restores_previous_fields() {
        let _guard = acquire_test_state_lock();
        reset_context_for_tests();

        let outer = bind_context([
            ("request_id".to_string(), json!("req-1")),
            ("tenant_id".to_string(), json!("tenant-1")),
        ]);
        assert_eq!(get_context().get("request_id"), Some(&json!("req-1")));
        assert_eq!(get_context().get("tenant_id"), Some(&json!("tenant-1")));

        {
            let cleared = clear_context();
            assert!(get_context().is_empty());
            drop(cleared);
        }

        assert_eq!(get_context().get("request_id"), Some(&json!("req-1")));
        assert_eq!(get_context().get("tenant_id"), Some(&json!("tenant-1")));
        drop(outer);
        assert!(get_context().is_empty());
    }

    #[test]
    fn context_test_unbind_context_removes_selected_fields_and_restores_them() {
        let _guard = acquire_test_state_lock();
        reset_context_for_tests();

        let outer = bind_context([
            ("request_id".to_string(), json!("req-1")),
            ("tenant_id".to_string(), json!("tenant-1")),
        ]);

        {
            let unbound = unbind_context(&["tenant_id"]);
            assert_eq!(get_context().get("request_id"), Some(&json!("req-1")));
            assert!(!get_context().contains_key("tenant_id"));
            drop(unbound);
        }

        assert_eq!(get_context().get("request_id"), Some(&json!("req-1")));
        assert_eq!(get_context().get("tenant_id"), Some(&json!("tenant-1")));
        drop(outer);
        assert!(get_context().is_empty());
    }

    #[test]
    fn context_test_a_session_context_roundtrip_restores_session_id() {
        let _guard = acquire_test_state_lock();
        reset_context_for_tests();

        let outer = bind_session_context("session-123");
        assert_eq!(get_session_id(), Some("session-123".to_string()));
        assert_eq!(get_context().get("session_id"), Some(&json!("session-123")));

        {
            let cleared = clear_session_context();
            assert_eq!(get_session_id(), None);
            assert!(!get_context().contains_key("session_id"));
            drop(cleared);
        }

        assert_eq!(get_session_id(), Some("session-123".to_string()));
        assert_eq!(get_context().get("session_id"), Some(&json!("session-123")));
        drop(outer);
        assert_eq!(get_session_id(), None);
        assert!(!get_context().contains_key("session_id"));
    }

    #[test]
    fn context_test_current_scope_key_tracks_tasks_without_leaking_to_threads() {
        let _guard = acquire_test_state_lock();
        reset_context_for_tests();

        assert_eq!(current_scope_key(), ContextScopeKey::Thread);

        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("runtime");
        runtime.block_on(async {
            tokio::spawn(async {
                let task_id = tokio::task::id();
                match current_scope_key() {
                    ContextScopeKey::Task(key) => assert_eq!(key, task_id),
                    ContextScopeKey::Thread => panic!("task scope should use the task id"),
                }

                let _bound = bind_context([("task_id".to_string(), json!(task_id.to_string()))]);
                assert_eq!(
                    get_context().get("task_id"),
                    Some(&json!(task_id.to_string()))
                );
            })
            .await
            .expect("task should complete");
        });

        assert!(!get_context().contains_key("task_id"));
    }

    #[test]
    fn context_test_set_trace_context_roundtrip_restores_previous_snapshot() {
        let _guard = acquire_test_state_lock();
        reset_context_for_tests();

        let outer = set_trace_context_internal(
            Some("outer-trace".to_string()),
            Some("outer-span".to_string()),
        );
        let snapshot = trace_snapshot();
        assert_eq!(snapshot.trace_id.as_deref(), Some("outer-trace"));
        assert_eq!(snapshot.span_id.as_deref(), Some("outer-span"));

        {
            let inner = set_trace_context_internal(
                Some("inner-trace".to_string()),
                Some("inner-span".to_string()),
            );
            let snapshot = trace_snapshot();
            assert_eq!(snapshot.trace_id.as_deref(), Some("inner-trace"));
            assert_eq!(snapshot.span_id.as_deref(), Some("inner-span"));
            drop(inner);
        }

        let snapshot = trace_snapshot();
        assert_eq!(snapshot.trace_id.as_deref(), Some("outer-trace"));
        assert_eq!(snapshot.span_id.as_deref(), Some("outer-span"));
        drop(outer);

        let snapshot = trace_snapshot();
        assert_eq!(snapshot.trace_id, None);
        assert_eq!(snapshot.span_id, None);
    }

    #[test]
    fn context_test_reset_trace_context_clears_task_snapshots_too() {
        let _guard = acquire_test_state_lock();
        reset_context_for_tests();

        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("runtime");
        runtime.block_on(async {
            tokio::spawn(async {
                let task_id = tokio::task::id();
                task_contexts()
                    .lock()
                    .expect("task context lock poisoned")
                    .insert(
                        task_id,
                        ContextSnapshot {
                            trace_id: Some("trace".to_string()),
                            span_id: Some("span".to_string()),
                            ..ContextSnapshot::default()
                        },
                    );

                reset_trace_context_for_tests();

                let tasks = task_contexts().lock().expect("task context lock poisoned");
                let snapshot = tasks
                    .get(&task_id)
                    .expect("task snapshot should still exist");
                assert_eq!(snapshot.trace_id, None);
                assert_eq!(snapshot.span_id, None);
            })
            .await
            .expect("task should complete");
        });
    }
}
