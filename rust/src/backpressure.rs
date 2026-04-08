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

pub enum QueueTicket {
    Unlimited,
    Bounded(OwnedSemaphorePermit),
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

fn queues() -> &'static Mutex<QueueState> {
    QUEUES.get_or_init(|| Mutex::new(QueueState::default()))
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

pub fn release(ticket: QueueTicket) {
    match ticket {
        QueueTicket::Unlimited => {}
        QueueTicket::Bounded(permit) => drop(permit),
    }
}

pub fn _reset_backpressure_for_tests() {
    *queues().lock().expect("queue lock poisoned") = QueueState::default();
}
