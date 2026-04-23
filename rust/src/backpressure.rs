// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::sync::{Arc, Mutex, OnceLock};

use tokio::sync::{OwnedSemaphorePermit, Semaphore};

use crate::health::increment_dropped;
use crate::sampling::Signal;

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct QueuePolicy {
    pub logs_maxsize: usize,
    pub traces_maxsize: usize,
    pub metrics_maxsize: usize,
}

enum QueueLimiter {
    Unlimited,
    Bounded(Arc<Semaphore>),
}

impl Default for QueueLimiter {
    fn default() -> Self {
        Self::Unlimited
    }
}

pub enum QueueTicket {
    Unlimited,
    Bounded(OwnedSemaphorePermit),
}

impl Default for QueueTicket {
    fn default() -> Self {
        Self::Unlimited
    }
}

struct QueueState {
    policy: QueuePolicy,
    logs: QueueLimiter,
    traces: QueueLimiter,
    metrics: QueueLimiter,
}

impl Default for QueueState {
    fn default() -> Self {
        Self::from_policy(QueuePolicy::default())
    }
}

impl QueueState {
    fn from_policy(policy: QueuePolicy) -> Self {
        Self {
            logs: limiter(policy.logs_maxsize),
            traces: limiter(policy.traces_maxsize),
            metrics: limiter(policy.metrics_maxsize),
            policy,
        }
    }
}

fn limiter(size: usize) -> QueueLimiter {
    if size == 0 {
        QueueLimiter::Unlimited
    } else {
        QueueLimiter::Bounded(Arc::new(Semaphore::new(size)))
    }
}

static QUEUES: OnceLock<Mutex<QueueState>> = OnceLock::new();

#[cfg_attr(test, mutants::skip)] // Equivalent mutants only swap in Mutex::default().
fn default_queue_state_mutex() -> Mutex<QueueState> {
    Mutex::new(QueueState::default())
}

fn queues() -> &'static Mutex<QueueState> {
    QUEUES.get_or_init(default_queue_state_mutex)
}

pub fn set_queue_policy(policy: QueuePolicy) {
    *queues().lock().expect("queue lock poisoned") = QueueState::from_policy(policy);
}

pub fn get_queue_policy() -> QueuePolicy {
    queues().lock().expect("queue lock poisoned").policy.clone()
}

pub fn try_acquire(signal: Signal) -> Option<QueueTicket> {
    let guard = queues().lock().expect("queue lock poisoned");
    let limiter = match signal {
        Signal::Logs => &guard.logs,
        Signal::Traces => &guard.traces,
        Signal::Metrics => &guard.metrics,
    };

    match limiter {
        QueueLimiter::Unlimited => Some(QueueTicket::Unlimited),
        QueueLimiter::Bounded(semaphore) => semaphore
            .clone()
            .try_acquire_owned()
            .map(QueueTicket::Bounded)
            .ok()
            .or_else(|| {
                increment_dropped(signal, 1);
                None
            }),
    }
}

#[cfg_attr(test, mutants::skip)] // Equivalent mutant: moving `ticket` into this function drops it at scope end.
pub fn release(ticket: QueueTicket) {
    match ticket {
        QueueTicket::Unlimited => {}
        QueueTicket::Bounded(permit) => drop(permit),
    }
}

pub fn _reset_backpressure_for_tests() {
    *queues().lock().expect("queue lock poisoned") = QueueState::default();
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testing::acquire_test_state_lock;

    #[test]
    fn backpressure_test_reset_helper_restores_default_policy() {
        let _guard = acquire_test_state_lock();
        set_queue_policy(QueuePolicy {
            logs_maxsize: 3,
            traces_maxsize: 4,
            metrics_maxsize: 5,
        });
        assert_eq!(
            get_queue_policy(),
            QueuePolicy {
                logs_maxsize: 3,
                traces_maxsize: 4,
                metrics_maxsize: 5,
            }
        );

        _reset_backpressure_for_tests();

        assert_eq!(get_queue_policy(), QueuePolicy::default());
    }

    #[test]
    fn backpressure_test_queues_returns_shared_singleton() {
        let _guard = acquire_test_state_lock();
        let first = queues() as *const Mutex<QueueState>;
        let second = queues() as *const Mutex<QueueState>;

        assert_eq!(first, second);
    }

    #[test]
    fn backpressure_test_acquire_obeys_policy_limits() {
        let _guard = acquire_test_state_lock();
        _reset_backpressure_for_tests();

        set_queue_policy(QueuePolicy {
            logs_maxsize: 1,
            traces_maxsize: 0,
            metrics_maxsize: 0,
        });

        let first = try_acquire(Signal::Logs).expect("bounded acquire should succeed once");
        let second = try_acquire(Signal::Logs);

        assert!(matches!(first, QueueTicket::Bounded(_)));
        assert!(second.is_none());
        assert_eq!(get_queue_policy().logs_maxsize, 1);
        release(first);

        _reset_backpressure_for_tests();
        set_queue_policy(QueuePolicy::default());
        let unlimited = try_acquire(Signal::Logs).expect("unlimited acquire should succeed");
        assert!(matches!(unlimited, QueueTicket::Unlimited));
    }
}
