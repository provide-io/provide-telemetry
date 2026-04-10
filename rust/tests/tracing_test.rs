// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
use serde_json::json;
use tokio::runtime::Builder;

use provide_telemetry::context::get_context;
use provide_telemetry::{
    bind_context, bind_session_context, clear_context, clear_session_context, get_session_id,
    get_trace_context, set_trace_context, unbind_context,
};

#[test]
fn tracing_test_bind_context_guard_restores_previous_snapshot() {
    {
        let _clear = clear_context();
    }

    let outer = bind_context([("request_id".to_string(), json!("req-1"))]);
    assert_eq!(get_context().get("request_id"), Some(&json!("req-1")));

    {
        let _inner = bind_context([("actor_id".to_string(), json!("user-1"))]);
        assert_eq!(get_context().get("request_id"), Some(&json!("req-1")));
        assert_eq!(get_context().get("actor_id"), Some(&json!("user-1")));
    }

    assert_eq!(get_context().get("request_id"), Some(&json!("req-1")));
    assert!(!get_context().contains_key("actor_id"));

    {
        let _unbind = unbind_context(&["request_id"]);
        assert!(!get_context().contains_key("request_id"));
    }

    assert_eq!(get_context().get("request_id"), Some(&json!("req-1")));
    drop(outer);
}

#[test]
fn tracing_test_session_context_round_trip() {
    let _outer = bind_session_context("sess-123");
    assert_eq!(get_session_id().as_deref(), Some("sess-123"));
    assert_eq!(get_context().get("session_id"), Some(&json!("sess-123")));

    {
        let _clear = clear_session_context();
        assert_eq!(get_session_id(), None);
        assert!(!get_context().contains_key("session_id"));
    }

    assert_eq!(get_session_id().as_deref(), Some("sess-123"));
}

#[test]
fn tracing_test_trace_context_survives_await_boundaries() {
    let runtime = Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("runtime");

    runtime.block_on(async {
        let _guard = set_trace_context(Some("a".repeat(32)), Some("b".repeat(16)));
        tokio::task::yield_now().await;

        let ctx = get_trace_context();
        assert_eq!(ctx.get("trace_id"), Some(&Some("a".repeat(32))));
        assert_eq!(ctx.get("span_id"), Some(&Some("b".repeat(16))));
    });

    assert_eq!(get_trace_context().get("trace_id"), Some(&None));
    assert_eq!(get_trace_context().get("span_id"), Some(&None));
}

#[test]
fn tracing_test_context_isolated_across_tokio_tasks() {
    let runtime = Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()
        .expect("runtime");

    let (a, b) = runtime.block_on(async {
        let task_a = tokio::spawn(async {
            let _ctx = bind_context([("request_id".to_string(), json!("req-a"))]);
            let _sess = bind_session_context("sess-a");
            let _trace = set_trace_context(Some("a".repeat(32)), Some("1".repeat(16)));
            tokio::task::yield_now().await;
            (get_context(), get_session_id(), get_trace_context())
        });

        let task_b = tokio::spawn(async {
            let _ctx = bind_context([("request_id".to_string(), json!("req-b"))]);
            let _sess = bind_session_context("sess-b");
            let _trace = set_trace_context(Some("b".repeat(32)), Some("2".repeat(16)));
            tokio::task::yield_now().await;
            (get_context(), get_session_id(), get_trace_context())
        });

        (
            task_a.await.expect("task a should succeed"),
            task_b.await.expect("task b should succeed"),
        )
    });

    assert_eq!(a.0.get("request_id"), Some(&json!("req-a")));
    assert_eq!(b.0.get("request_id"), Some(&json!("req-b")));
    assert_eq!(a.1.as_deref(), Some("sess-a"));
    assert_eq!(b.1.as_deref(), Some("sess-b"));
    assert_eq!(a.2.get("trace_id"), Some(&Some("a".repeat(32))));
    assert_eq!(b.2.get("trace_id"), Some(&Some("b".repeat(32))));
}
