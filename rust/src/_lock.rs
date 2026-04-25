// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Poison-tolerant lock helpers.
//!
//! `std::sync::Mutex` and `std::sync::RwLock` become *poisoned* when a
//! thread panics while holding the lock. The stdlib default — calling
//! `.unwrap()` or `.expect("lock poisoned")` — propagates that panic
//! into every subsequent locker, which cascades the failure across the
//! process. For a telemetry library this is catastrophic: a panic inside
//! one log emission path would silently disable the entire logger, tracer,
//! meter, circuit breaker, and health snapshot.
//!
//! These helpers recover the inner guard via [`PoisonError::into_inner`],
//! letting us keep moving with whatever state was present at the time of
//! the panic. Callers don't need to reason about poison semantics — they
//! just call [`lock`], [`rwlock_read`], or [`rwlock_write`] and get a
//! normal guard back.

use std::sync::{Mutex, MutexGuard, RwLock, RwLockReadGuard, RwLockWriteGuard};

/// Acquire a [`Mutex`] guard, recovering from poison.
///
/// If the mutex is poisoned (a previous holder panicked), the poisoned
/// inner guard is returned instead of panicking. This prevents a single
/// panic from cascading into every subsequent lock attempt.
#[inline]
pub(crate) fn lock<T>(m: &Mutex<T>) -> MutexGuard<'_, T> {
    m.lock().unwrap_or_else(|e| e.into_inner())
}

/// Acquire an [`RwLock`] read guard, recovering from poison.
#[inline]
#[allow(dead_code)] // Not currently used in src/; retained as part of the helper API.
pub(crate) fn rwlock_read<T>(m: &RwLock<T>) -> RwLockReadGuard<'_, T> {
    m.read().unwrap_or_else(|e| e.into_inner())
}

/// Acquire an [`RwLock`] write guard, recovering from poison.
#[inline]
#[allow(dead_code)] // Not currently used in src/; retained as part of the helper API.
pub(crate) fn rwlock_write<T>(m: &RwLock<T>) -> RwLockWriteGuard<'_, T> {
    m.write().unwrap_or_else(|e| e.into_inner())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;
    use std::thread;

    #[test]
    fn lock_recovers_from_mutex_poison() {
        let m = Arc::new(Mutex::new(7u32));
        let m2 = Arc::clone(&m);
        let _ = thread::spawn(move || {
            let _guard = m2.lock().expect("first lock must succeed");
            panic!("poison the mutex");
        })
        .join();
        // Stdlib `.lock().unwrap()` would panic here.
        let guard = lock(&m);
        assert_eq!(*guard, 7);
    }

    #[test]
    fn rwlock_helpers_recover_from_poison() {
        let m = Arc::new(RwLock::new(11u32));
        let m2 = Arc::clone(&m);
        let _ = thread::spawn(move || {
            let _guard = m2.write().expect("first write must succeed");
            panic!("poison the rwlock");
        })
        .join();
        assert_eq!(*rwlock_read(&m), 11);
        {
            let mut g = rwlock_write(&m);
            *g = 42;
        }
        assert_eq!(*rwlock_read(&m), 42);
    }
}
