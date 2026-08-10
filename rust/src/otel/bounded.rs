// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Bounded drain/teardown primitives shared by the flush and shutdown paths.
//!
//! Split out of `mod.rs` to keep that file inside the 500-line ceiling
//! `scripts/check_max_loc.py` enforces.

use std::io;
use std::sync::{mpsc, Arc, Mutex};
use std::time::Duration;

use super::DrainOutcome;

/// Ceiling applied to a drain deadline. Past this a "bounded" drain is not
/// bounding anything, and it keeps the value well inside what
/// `Duration::from_secs_f64` can represent.
pub(crate) const MAX_DRAIN_SECONDS: f64 = 86_400.0;

/// Cap on outstanding abandoned drain workers, mirroring Python's
/// `_MAX_ABANDONED_WORKERS`. flush is documented for repeated use (a request
/// boundary, a checkpoint), so against an unreachable collector every call
/// would otherwise strand another thread inside the exporter's retry loop
/// until process exit — ending in a failed spawn raised from unrelated code.
const MAX_ABANDONED_WORKERS: u32 = 8;

static ABANDONED_WORKERS: Mutex<u32> = Mutex::new(0);

/// Per-drain arbitration between the waiting caller and its worker.
///
/// `finished` is set by the worker on its way out; `counted` by the caller
/// when it abandons the worker at the deadline. Both flips happen under the
/// same lock, so a worker that finished just after the deadline still
/// decrements the budget slot the caller charged for it, and a worker that
/// finished just before is never charged at all.
struct DrainAccounting {
    finished: bool,
    counted: bool,
}

fn abandoned_worker_count() -> u32 {
    *crate::_lock::lock(&ABANDONED_WORKERS)
}

/// True when `count` stranded workers exhaust the budget for starting another.
fn drain_budget_saturated(count: u32) -> bool {
    count >= MAX_ABANDONED_WORKERS
}

pub(crate) fn _reset_abandoned_workers_for_tests() {
    *crate::_lock::lock(&ABANDONED_WORKERS) = 0;
}

#[cfg(test)]
pub(crate) fn abandoned_worker_count_for_tests() -> u32 {
    abandoned_worker_count()
}

/// Worker-side exit bookkeeping: release the budget slot if the caller
/// charged one for this worker.
fn note_worker_finished(acct: &Mutex<DrainAccounting>) {
    let mut state = crate::_lock::lock(acct);
    state.finished = true;
    if state.counted {
        let mut count = crate::_lock::lock(&ABANDONED_WORKERS);
        *count = count.saturating_sub(1);
    }
}

/// Caller-side deadline bookkeeping: charge a budget slot unless the worker
/// already finished.
fn note_worker_abandoned(acct: &Mutex<DrainAccounting>) {
    let mut state = crate::_lock::lock(acct);
    if !state.finished {
        state.counted = true;
        *crate::_lock::lock(&ABANDONED_WORKERS) += 1;
    }
}

/// Turn a drain deadline in seconds into a `Duration`, or `None` when the
/// value asks for no bound at all.
///
/// `Duration::from_secs_f64` panics on NaN, on ±inf, and on anything past
/// `u64::MAX` seconds. These deadlines arrive from a public API argument
/// (`flush_telemetry`/`shutdown_telemetry`) and from config, and the callers
/// are shutdown paths — a panic there aborts the process mid-termination and
/// loses every queued record, which is the opposite of what a caller passing
/// a deadline is asking for.
///
/// NaN and `+inf` mean "drain without a deadline". A finite value `<= 0` — a
/// caller's whole budget already spent — is a zero budget: the drain is
/// started and abandoned immediately, exactly what Python's `wait(0)` and
/// TypeScript's `setTimeout(..., 0)` do, so a non-blocking best-effort flush
/// behaves the same in all four languages. A finite positive value is clamped
/// so the conversion cannot overflow.
pub(crate) fn drain_deadline(timeout_secs: f64) -> Option<Duration> {
    if timeout_secs.is_nan() || timeout_secs == f64::INFINITY {
        return None;
    }
    if timeout_secs <= 0.0 {
        return Some(Duration::ZERO);
    }
    Some(Duration::from_secs_f64(timeout_secs.min(MAX_DRAIN_SECONDS)))
}

/// The configured bounded-shutdown deadline, for callers that passed none.
fn configured_drain_seconds() -> f64 {
    crate::runtime::get_runtime_config()
        .map(|cfg| cfg.exporter.logs_shutdown_timeout_seconds)
        .unwrap_or(5.0)
}

/// A worker spawn attempt: the thread name and the job to run on it.
/// Injected so the spawn-failure fallback is reachable from a test.
pub(crate) type SpawnResult = io::Result<std::thread::JoinHandle<()>>;

fn spawn_worker(name: String, job: Box<dyn FnOnce() + Send + 'static>) -> SpawnResult {
    std::thread::Builder::new().name(name).spawn(job)
}

/// Take and run a drain job a failed spawn left untaken.
fn run_leftover_job<T>(job: &Mutex<Option<impl FnOnce() -> T>>) -> Option<T> {
    crate::_lock::lock(job).take().map(|job| job())
}

/// Join a scoped drain worker, or run the drain inline when the spawn itself
/// failed (OS thread limit). Inline the drain loses concurrency and the
/// deadline overlap, not the records — at the thread limit the alternative is
/// dropping the queue on the floor mid-shutdown.
pub(crate) fn join_or_inline<T>(
    spawned: io::Result<std::thread::ScopedJoinHandle<'_, T>>,
    inline: impl FnOnce() -> T,
) -> T {
    match spawned {
        Ok(handle) => handle.join().expect("drain worker must not panic"),
        Err(_) => inline(),
    }
}

/// Run `teardown` under the caller's deadline, on a detached worker when one
/// applies.
///
/// Bounded for the same reason [`bounded_flush`] is: `SdkTracerProvider::shutdown`
/// and its logger/meter counterparts take no timeout parameter and join their
/// batch worker with the SDK's own 30s default. Without this the deadline a
/// SIGTERM handler passed buys nothing — the pre-drain returns on time and the
/// teardown right behind it blocks until the collector answers or the pod is
/// SIGKILLed.
///
/// On expiry the worker is abandoned. The provider slot has already been taken
/// by the caller, so the abandoned thread is draining a provider nothing can
/// reach any more. Abandoned teardown workers count toward the stranded-worker
/// budget, but teardown never declines for want of it: it is the last chance
/// to get queued records out.
pub(crate) fn bounded_teardown<F>(signal: &str, timeout_seconds: Option<f64>, teardown: F)
where
    F: FnOnce() + Send + 'static,
{
    bounded_teardown_with(signal, timeout_seconds, teardown, spawn_worker);
}

pub(crate) fn bounded_teardown_with<F, S>(
    signal: &str,
    timeout_seconds: Option<f64>,
    teardown: F,
    spawn: S,
) where
    F: FnOnce() + Send + 'static,
    S: FnOnce(String, Box<dyn FnOnce() + Send + 'static>) -> SpawnResult,
{
    let timeout_secs = timeout_seconds.unwrap_or_else(configured_drain_seconds);

    // No usable bound (NaN or infinity) — do the synchronous teardown. See
    // `drain_deadline` for why neither can be handed to `Duration::from_secs_f64`.
    let Some(timeout) = drain_deadline(timeout_secs) else {
        teardown();
        return;
    };
    let (tx, rx) = mpsc::channel();
    let acct = Arc::new(Mutex::new(DrainAccounting {
        finished: false,
        counted: false,
    }));
    let job = Arc::new(Mutex::new(Some(teardown)));
    let worker_acct = Arc::clone(&acct);
    let worker_job = Arc::clone(&job);
    let spawned = spawn(
        format!("provide-{signal}-shutdown"),
        Box::new(move || {
            if let Some(teardown) = crate::_lock::lock(&worker_job).take() {
                teardown();
                let _ = tx.send(());
            }
            note_worker_finished(&worker_acct);
        }),
    );
    if spawned.is_err() {
        // The failed spawn never took the job, so it is still here to run.
        // Inline is unbounded, but correct: teardown is the last chance to
        // drain, and at the thread limit the bounded alternative does not exist.
        eprintln!(
            "provide_telemetry: {signal} shutdown worker could not be spawned; tearing down inline without a deadline",
        );
        run_leftover_job(&job).expect("teardown job is present: the failed spawn never ran it");
        return;
    }

    if rx.recv_timeout(timeout).is_err() {
        note_worker_abandoned(&acct);
        eprintln!(
            "provide_telemetry: {signal} shutdown exceeded {:.3}s deadline; abandoning background flush",
            timeout.as_secs_f64(),
        );
    }
}

/// Run `flush` under the bounded-shutdown deadline, on a detached worker when
/// one applies. `flush` reports whether the export succeeded.
///
/// The outcome keeps the deadline expiry and the in-deadline rejection apart:
/// [`DrainOutcome::TimedOut`] when the worker was abandoned at the deadline,
/// [`DrainOutcome::Failed`] when the drain finished in time but the exporter
/// rejected it. Both mean records may still be sitting in the exporter's
/// queue, but a caller alerting on the distinction — Python's
/// `"timed_out"`/`"failed"`, Go's `context.DeadlineExceeded` check — must not
/// see the two collapsed.
///
/// Past [`MAX_ABANDONED_WORKERS`] stranded workers the flush declines to start
/// another — flush runs per request boundary, so against an unreachable
/// collector it would otherwise strand a thread per call until the process
/// hits its thread limit. A declined drain reports [`DrainOutcome::TimedOut`],
/// matching Python, where the decline surfaces through the same `False` its
/// `_drain_signal` maps to `"timed_out"`: the records are hostage to the
/// earlier deadline expiries that saturated the budget.
pub(crate) fn bounded_flush<F>(signal: &str, timeout_seconds: Option<f64>, flush: F) -> DrainOutcome
where
    F: FnOnce() -> bool + Send + 'static,
{
    bounded_flush_with(signal, timeout_seconds, flush, spawn_worker)
}

/// Map the report of a drain that ran to completion — no deadline expired.
fn completed_drain_outcome(exported: bool) -> DrainOutcome {
    if exported {
        DrainOutcome::Drained
    } else {
        DrainOutcome::Failed
    }
}

pub(crate) fn bounded_flush_with<F, S>(
    signal: &str,
    timeout_seconds: Option<f64>,
    flush: F,
    spawn: S,
) -> DrainOutcome
where
    F: FnOnce() -> bool + Send + 'static,
    S: FnOnce(String, Box<dyn FnOnce() + Send + 'static>) -> SpawnResult,
{
    // A caller-supplied deadline wins over the configured one, so a caller with
    // a budget (a SIGTERM handler, a request boundary) can bound this call.
    let timeout_secs = timeout_seconds.unwrap_or_else(configured_drain_seconds);

    // No usable bound (NaN or infinity) — do the synchronous drain. It ran to
    // completion, so the only outcomes are drained and failed: a deadline that
    // does not exist cannot expire.
    let Some(timeout) = drain_deadline(timeout_secs) else {
        return completed_drain_outcome(flush());
    };
    if drain_budget_saturated(abandoned_worker_count()) {
        eprintln!(
            "provide_telemetry: {signal} flush skipped: {MAX_ABANDONED_WORKERS} earlier drain workers are still pending against an unresponsive exporter",
        );
        return DrainOutcome::TimedOut;
    }
    let (tx, rx) = mpsc::channel();
    let acct = Arc::new(Mutex::new(DrainAccounting {
        finished: false,
        counted: false,
    }));
    let job = Arc::new(Mutex::new(Some(flush)));
    let worker_acct = Arc::clone(&acct);
    let worker_job = Arc::clone(&job);
    let spawned = spawn(
        format!("provide-{signal}-flush"),
        Box::new(move || {
            if let Some(flush) = crate::_lock::lock(&worker_job).take() {
                let _ = tx.send(flush());
            }
            note_worker_finished(&worker_acct);
        }),
    );
    if spawned.is_err() {
        // The failed spawn never took the job, so it is still here to run.
        // Inline is unbounded, but the records drain; the bounded alternative
        // does not exist at the thread limit.
        eprintln!(
            "provide_telemetry: {signal} flush worker could not be spawned; draining inline without a deadline",
        );
        return completed_drain_outcome(
            run_leftover_job(&job).expect("flush job is present: the failed spawn never ran it"),
        );
    }

    match rx.recv_timeout(timeout) {
        Ok(true) => DrainOutcome::Drained,
        // The drain finished in time but the exporter rejected it: reporting
        // Drained here would tell a caller its records are out when they are
        // not, and TimedOut would claim a deadline expired when nothing did.
        Ok(false) => {
            eprintln!("provide_telemetry: {signal} flush failed");
            DrainOutcome::Failed
        }
        Err(_) => {
            note_worker_abandoned(&acct);
            eprintln!(
                "provide_telemetry: {signal} flush exceeded {:.3}s deadline; abandoning background flush",
                timeout.as_secs_f64(),
            );
            DrainOutcome::TimedOut
        }
    }
}

#[cfg(test)]
mod accounting_tests {
    use super::*;
    use crate::testing::acquire_test_state_lock;

    /// The saturation boundary: below the cap another worker may be stranded,
    /// at and past it the flush must decline. An off-by-one here either
    /// wastes the last budget slot or lets the stranding grow unbounded.
    #[test]
    fn the_budget_saturates_exactly_at_the_cap() {
        assert!(!drain_budget_saturated(MAX_ABANDONED_WORKERS - 1));
        assert!(drain_budget_saturated(MAX_ABANDONED_WORKERS));
        assert!(drain_budget_saturated(MAX_ABANDONED_WORKERS + 1));
    }

    /// The caller/worker arbitration, both orders. Abandon-then-finish must
    /// charge and then release a slot; finish-then-abandon must never charge —
    /// a drain that completed at 49.9ms of a 50ms budget exported its records.
    #[test]
    fn a_slot_is_charged_only_when_the_worker_had_not_finished() {
        let _guard = acquire_test_state_lock();
        _reset_abandoned_workers_for_tests();

        let acct = Mutex::new(DrainAccounting {
            finished: false,
            counted: false,
        });
        note_worker_abandoned(&acct);
        assert_eq!(abandoned_worker_count(), 1, "abandon charges a slot");
        note_worker_finished(&acct);
        assert_eq!(abandoned_worker_count(), 0, "late finish releases it");

        let acct = Mutex::new(DrainAccounting {
            finished: false,
            counted: false,
        });
        note_worker_finished(&acct);
        note_worker_abandoned(&acct);
        assert_eq!(
            abandoned_worker_count(),
            0,
            "a worker that finished first is never charged"
        );

        _reset_abandoned_workers_for_tests();
    }

    /// The counter never underflows: a stale worker exiting after a test reset
    /// must saturate at zero, not wrap to u32::MAX and jam the budget shut.
    #[test]
    fn releasing_a_slot_saturates_at_zero() {
        let _guard = acquire_test_state_lock();
        _reset_abandoned_workers_for_tests();

        let acct = Mutex::new(DrainAccounting {
            finished: false,
            counted: true,
        });
        note_worker_finished(&acct);
        assert_eq!(abandoned_worker_count(), 0);
    }

    #[test]
    fn a_leftover_job_runs_once_and_only_once() {
        let job = Mutex::new(Some(|| 7));
        assert_eq!(run_leftover_job(&job), Some(7));
        assert_eq!(run_leftover_job(&job), None);
    }
}
