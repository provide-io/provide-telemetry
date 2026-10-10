// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! The Prometheus pull reader: a cumulative `ManualReader` the meter provider
//! owns, plus a shared handle the Tier 2 handler collects through.
//!
//! The renderer works on a plain [`ResourceView`]; this module converts the
//! SDK's `ResourceMetrics` into one. Exponential histograms are not exported
//! over this path, as in the other SDKs.

use std::sync::{Arc, Weak};
use std::time::Duration;

use opentelemetry::KeyValue;
use opentelemetry_sdk::error::OTelSdkResult;
use opentelemetry_sdk::metrics::data::{AggregatedMetrics, Metric, MetricData, ResourceMetrics};
use opentelemetry_sdk::metrics::reader::MetricReader;
use opentelemetry_sdk::metrics::{InstrumentKind, ManualReader, Pipeline, Temporality};

use crate::prometheus::render::{
    HistogramPoint, Labels, MetricView, Points, ResourceView, ScopeView,
};

/// A cumulative pull reader. Clones share one underlying reader, so the clone
/// handed to the provider and the one kept for collection see the same data.
#[derive(Clone, Debug)]
pub(crate) struct PullReader {
    inner: Arc<ManualReader>,
}

impl PullReader {
    pub(crate) fn new() -> Self {
        Self {
            inner: Arc::new(
                ManualReader::builder()
                    .with_temporality(Temporality::Cumulative)
                    .build(),
            ),
        }
    }

    /// Run one collection: observable callbacks, then every instrument's
    /// current cumulative value. Empty once the provider has shut down.
    pub(crate) fn view(&self) -> ResourceView {
        let mut metrics = ResourceMetrics::default();
        if self.inner.collect(&mut metrics).is_err() {
            return ResourceView::default();
        }
        view_of(&metrics)
    }
}

impl MetricReader for PullReader {
    fn register_pipeline(&self, pipeline: Weak<Pipeline>) {
        self.inner.register_pipeline(pipeline);
    }

    fn collect(&self, rm: &mut ResourceMetrics) -> OTelSdkResult {
        self.inner.collect(rm)
    }

    // ManualReader's force_flush is a constant Ok(()), so replacing the
    // delegation with Ok(()) is an equivalent mutant.
    #[cfg_attr(test, mutants::skip)]
    fn force_flush(&self) -> OTelSdkResult {
        self.inner.force_flush()
    }

    fn shutdown_with_timeout(&self, timeout: Duration) -> OTelSdkResult {
        self.inner.shutdown_with_timeout(timeout)
    }

    // Prometheus requires cumulative temporality whatever the instrument.
    // Temporality::default() is Cumulative, so the only mutant is equivalent.
    #[cfg_attr(test, mutants::skip)]
    fn temporality(&self, _kind: InstrumentKind) -> Temporality {
        Temporality::Cumulative
    }
}

fn labels<'a>(attributes: impl Iterator<Item = &'a KeyValue>) -> Labels {
    attributes
        .map(|kv| (kv.key.to_string(), kv.value.to_string()))
        .collect()
}

pub(crate) fn view_of(metrics: &ResourceMetrics) -> ResourceView {
    ResourceView {
        attributes: metrics
            .resource()
            .iter()
            .map(|(key, value)| (key.to_string(), value.to_string()))
            .collect(),
        scopes: metrics
            .scope_metrics()
            .map(|scope_metrics| ScopeView {
                name: scope_metrics.scope().name().to_string(),
                version: scope_metrics.scope().version().map(str::to_string),
                metrics: scope_metrics.metrics().filter_map(metric_view).collect(),
            })
            .collect(),
    }
}

fn metric_view(metric: &Metric) -> Option<MetricView> {
    let points = match metric.data() {
        AggregatedMetrics::F64(data) => points_of(data, |v| v),
        AggregatedMetrics::U64(data) => points_of(data, |v| v as f64),
        AggregatedMetrics::I64(data) => points_of(data, |v| v as f64),
    }?;
    Some(MetricView {
        name: metric.name().to_string(),
        unit: metric.unit().to_string(),
        description: metric.description().to_string(),
        points,
    })
}

fn points_of<T: Copy>(data: &MetricData<T>, to_f64: fn(T) -> f64) -> Option<Points> {
    match data {
        MetricData::Gauge(gauge) => Some(Points::Gauge(
            gauge
                .data_points()
                .map(|p| (labels(p.attributes()), to_f64(p.value())))
                .collect(),
        )),
        MetricData::Sum(sum) => Some(Points::Sum {
            monotonic: sum.is_monotonic(),
            points: sum
                .data_points()
                .map(|p| (labels(p.attributes()), to_f64(p.value())))
                .collect(),
        }),
        MetricData::Histogram(histogram) => Some(Points::Histogram(
            histogram
                .data_points()
                .map(|p| HistogramPoint {
                    attributes: labels(p.attributes()),
                    bounds: p.bounds().collect(),
                    bucket_counts: p.bucket_counts().collect(),
                    count: p.count(),
                    sum: to_f64(p.sum()),
                })
                .collect(),
        )),
        MetricData::ExponentialHistogram(_) => None,
    }
}

#[cfg(test)]
#[path = "prometheus_reader_tests.rs"]
mod tests;
