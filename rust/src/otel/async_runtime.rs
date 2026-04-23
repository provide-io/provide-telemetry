// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::fmt::Debug;
use std::sync::OnceLock;
use std::time::Duration;

use opentelemetry_sdk::runtime::{Runtime, RuntimeChannel};

#[derive(Clone, Copy, Debug)]
pub(super) struct ProvideTokioRuntime {
    lane: RuntimeLane,
}

#[derive(Clone, Copy, Debug)]
enum RuntimeLane {
    Logs,
    Traces,
    Metrics,
    #[cfg(test)]
    Test,
}

fn build_runtime(thread_name: &'static str) -> tokio::runtime::Runtime {
    tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .thread_name(thread_name)
        .build()
        .expect("failed to create background Tokio runtime for OpenTelemetry")
}

fn observe_task_handle(
    runtime: &'static tokio::runtime::Runtime,
    handle: tokio::task::JoinHandle<()>,
) {
    drop(runtime.spawn(async move {
        if let Err(err) = handle.await {
            eprintln!("provide_telemetry: OTLP background task panicked: {err}");
        }
    }));
}

impl ProvideTokioRuntime {
    pub(super) fn logs() -> Self {
        Self {
            lane: RuntimeLane::Logs,
        }
    }

    pub(super) fn traces() -> Self {
        Self {
            lane: RuntimeLane::Traces,
        }
    }

    pub(super) fn metrics() -> Self {
        Self {
            lane: RuntimeLane::Metrics,
        }
    }

    #[cfg(test)]
    pub(super) fn test() -> Self {
        Self {
            lane: RuntimeLane::Test,
        }
    }

    fn runtime(&self) -> &'static tokio::runtime::Runtime {
        match self.lane {
            RuntimeLane::Logs => {
                static RUNTIME: OnceLock<tokio::runtime::Runtime> = OnceLock::new();
                RUNTIME.get_or_init(|| build_runtime("provide-telemetry-otel-logs"))
            }
            RuntimeLane::Traces => {
                static RUNTIME: OnceLock<tokio::runtime::Runtime> = OnceLock::new();
                RUNTIME.get_or_init(|| build_runtime("provide-telemetry-otel-traces"))
            }
            RuntimeLane::Metrics => {
                static RUNTIME: OnceLock<tokio::runtime::Runtime> = OnceLock::new();
                RUNTIME.get_or_init(|| build_runtime("provide-telemetry-otel-metrics"))
            }
            #[cfg(test)]
            RuntimeLane::Test => {
                static RUNTIME: OnceLock<tokio::runtime::Runtime> = OnceLock::new();
                RUNTIME.get_or_init(|| build_runtime("provide-telemetry-otel-test"))
            }
        }
    }

    pub(super) fn quiesce(&self) {
        // Shutdown helpers are synchronous and can be called from async
        // tests. Entering a Tokio runtime from another Tokio runtime
        // panics, so treat quiesce as best-effort in that situation.
        if tokio::runtime::Handle::try_current().is_ok() {
            return;
        }
        self.runtime().block_on(async {
            tokio::task::yield_now().await;
            tokio::task::yield_now().await;
        });
    }
}

impl Runtime for ProvideTokioRuntime {
    fn spawn<F>(&self, future: F)
    where
        F: std::future::Future<Output = ()> + Send + 'static,
    {
        let runtime = self.runtime();
        let handle = runtime.spawn(future);
        observe_task_handle(runtime, handle);
    }

    fn delay(&self, duration: Duration) -> impl std::future::Future<Output = ()> + Send + 'static {
        tokio::time::sleep(duration)
    }
}

impl RuntimeChannel for ProvideTokioRuntime {
    type Receiver<T: Debug + Send> = tokio_stream::wrappers::ReceiverStream<T>;
    type Sender<T: Debug + Send> = tokio::sync::mpsc::Sender<T>;

    fn batch_message_channel<T: Debug + Send>(
        &self,
        capacity: usize,
    ) -> (Self::Sender<T>, Self::Receiver<T>) {
        let (sender, receiver) = tokio::sync::mpsc::channel(capacity);
        (
            sender,
            tokio_stream::wrappers::ReceiverStream::new(receiver),
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{sync::mpsc, thread};

    #[test]
    fn async_runtime_test_spawn_executes_background_future() {
        let runtime = ProvideTokioRuntime::test();
        let (sender, receiver) = mpsc::channel();

        runtime.spawn(async move {
            sender.send(41_u32).expect("send from background task");
        });

        assert_eq!(receiver.recv_timeout(Duration::from_secs(2)).ok(), Some(41));
    }

    #[test]
    fn async_runtime_test_delay_completes_on_background_runtime() {
        let runtime = ProvideTokioRuntime::test();
        let task_runtime = runtime;
        let (sender, receiver) = mpsc::channel();

        runtime.spawn(async move {
            task_runtime.delay(Duration::from_millis(10)).await;
            sender.send(true).expect("send after delay");
        });

        assert_eq!(
            receiver.recv_timeout(Duration::from_secs(2)).ok(),
            Some(true)
        );
    }

    #[test]
    fn async_runtime_test_spawn_handles_panicking_future() {
        let runtime = ProvideTokioRuntime::test();

        runtime.spawn(async {
            panic!("expected panic in background task");
        });
        thread::sleep(Duration::from_millis(20));
        runtime.quiesce();
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 1)]
    async fn async_runtime_test_quiesce_is_safe_inside_tokio_runtime() {
        let runtime = ProvideTokioRuntime::test();

        runtime.quiesce();
    }
}
