// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Render collected metrics in the Prometheus text exposition format.
//!
//! A port of the Python renderer (`metrics/_prom_render.py`). Names go through
//! the reference translation in [`super::names`]. A scraper that negotiates
//! `escaping=allow-utf-8` (Prometheus 3 does) gets the UTF-8 names of the
//! NoUTF8/NoTranslation strategies in the quoted text-format syntax; any other
//! scraper gets the UnderscoreEscaping output with the same suffix choice, as
//! `prometheus_metrics.translation.rules` requires.
//!
//! The input is a plain view of one collection ([`ResourceView`]) rather than
//! the SDK's `ResourceMetrics`, whose fields cannot be built outside the SDK;
//! `otel::prometheus_reader` converts one into the other.

use std::collections::BTreeMap;

use super::names::{self, Kind, Strategy};

pub(crate) const CONTENT_TYPE_TEXT: &str =
    "text/plain; version=0.0.4; charset=utf-8; escaping=underscores";
pub(crate) const CONTENT_TYPE_UTF8: &str =
    "text/plain; version=1.0.0; charset=utf-8; escaping=allow-utf-8";

const TARGET_INFO: &str = "target_info";
const TARGET_INFO_HELP: &str = "Target metadata";

/// What one collection is rendered with.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct RenderOptions {
    pub(crate) strategy: String,
    pub(crate) scope_labels: bool,
    pub(crate) target_info: bool,
}

/// Ordered label pairs. Setting an existing name replaces its value in place,
/// as a Python dict update does.
pub(crate) type Labels = Vec<(String, String)>;

fn set_label(labels: &mut Labels, name: String, value: String) {
    match labels.iter_mut().find(|(existing, _)| *existing == name) {
        Some(slot) => slot.1 = value,
        None => labels.push((name, value)),
    }
}

/// One histogram data point, cumulative bucket counts not yet summed.
#[derive(Clone, Debug, PartialEq)]
pub(crate) struct HistogramPoint {
    pub(crate) attributes: Labels,
    pub(crate) bounds: Vec<f64>,
    pub(crate) bucket_counts: Vec<u64>,
    pub(crate) count: u64,
    pub(crate) sum: f64,
}

/// The data of one metric, by aggregation.
#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(not(feature = "otel"), allow(dead_code))] // built from SDK data
pub(crate) enum Points {
    Sum {
        monotonic: bool,
        points: Vec<(Labels, f64)>,
    },
    Gauge(Vec<(Labels, f64)>),
    Histogram(Vec<HistogramPoint>),
}

#[derive(Clone, Debug, PartialEq)]
pub(crate) struct MetricView {
    pub(crate) name: String,
    pub(crate) unit: String,
    pub(crate) description: String,
    pub(crate) points: Points,
}

#[derive(Clone, Debug, PartialEq)]
pub(crate) struct ScopeView {
    pub(crate) name: String,
    pub(crate) version: Option<String>,
    pub(crate) metrics: Vec<MetricView>,
}

/// One collection: the resource's attributes and every scope's metrics.
#[derive(Clone, Debug, Default, PartialEq)]
pub(crate) struct ResourceView {
    pub(crate) attributes: Labels,
    pub(crate) scopes: Vec<ScopeView>,
}

/// The Prometheus `# TYPE` of a family.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum PromType {
    Counter,
    Gauge,
    Histogram,
}

impl PromType {
    fn as_str(self) -> &'static str {
        match self {
            Self::Counter => "counter",
            Self::Gauge => "gauge",
            Self::Histogram => "histogram",
        }
    }
}

/// One sample: a suffix appended to the family name, its labels and value.
#[derive(Clone, Debug, PartialEq)]
pub(crate) struct Sample {
    pub(crate) suffix: &'static str,
    pub(crate) labels: Labels,
    pub(crate) value: f64,
}

/// One metric family: a translated name, a Prometheus type and its samples.
#[derive(Clone, Debug, PartialEq)]
pub(crate) struct Family {
    pub(crate) name: String,
    pub(crate) kind: PromType,
    pub(crate) help: String,
    pub(crate) samples: Vec<Sample>,
}

impl Family {
    pub(crate) fn new(name: &str, kind: PromType, help: &str) -> Self {
        Self {
            name: name.to_string(),
            kind,
            help: help.to_string(),
            samples: Vec::new(),
        }
    }

    pub(crate) fn push(&mut self, labels: Labels, value: f64) {
        self.samples.push(Sample {
            suffix: "",
            labels,
            value,
        });
    }
}

/// Whether an Accept header asks for the text format with UTF-8 names.
pub(crate) fn wants_utf8(accept: Option<&str>) -> bool {
    accept.unwrap_or("").split(',').any(|media_range| {
        let params: Vec<String> = media_range
            .split(';')
            .map(|p| p.trim().to_ascii_lowercase())
            .collect();
        params[0] == "text/plain" && params[1..].iter().any(|p| p == "escaping=allow-utf-8")
    })
}

/// The strategy to translate with for this scrape: a UTF-8 strategy falls back
/// to escaping, with the same suffix choice, unless the scraper negotiated UTF-8.
pub(crate) fn effective_strategy(configured: &str, utf8: bool) -> Strategy {
    let strategy = Strategy::named(configured);
    Strategy {
        escapes: strategy.escapes || !utf8,
        suffixes: strategy.suffixes,
    }
}

/// Translate attribute keys to label names, dropping keys that cannot be labels.
///
/// A key the reference rejects, or translates to a name starting with `__`
/// (reserved by Prometheus), is dropped; the sample is kept.
pub(crate) fn translate_labels(attributes: &Labels, strategy: Strategy) -> Labels {
    let mut labels = Labels::new();
    for (key, value) in attributes {
        if let Some(label) = names::label_name(key, strategy) {
            if !label.starts_with("__") {
                set_label(&mut labels, label, value.clone());
            }
        }
    }
    labels
}

fn scope_labels(scope: &ScopeView) -> Labels {
    let mut labels = vec![("otel_scope_name".to_string(), scope.name.clone())];
    if let Some(version) = scope.version.as_ref().filter(|v| !v.is_empty()) {
        labels.push(("otel_scope_version".to_string(), version.clone()));
    }
    labels
}

/// Convert one collection into families, sorted by translated name.
pub(crate) fn families_from(view: &ResourceView, opts: &RenderOptions, utf8: bool) -> Vec<Family> {
    let strategy = effective_strategy(&opts.strategy, utf8);
    let mut families: BTreeMap<String, Family> = BTreeMap::new();
    for scope in &view.scopes {
        let scope_extra = if opts.scope_labels {
            scope_labels(scope)
        } else {
            Labels::new()
        };
        for metric in &scope.metrics {
            add_metric(&mut families, metric, &scope_extra, strategy);
        }
    }
    let resource_labels = translate_labels(&view.attributes, strategy);
    if opts.target_info && !resource_labels.is_empty() {
        // An instrument that already translated to target_info keeps the name.
        families.entry(TARGET_INFO.to_string()).or_insert_with(|| {
            let mut info = Family::new(TARGET_INFO, PromType::Gauge, TARGET_INFO_HELP);
            info.push(resource_labels, 1.0);
            info
        });
    }
    families.into_values().collect()
}

fn kinds_of(points: &Points) -> (Kind, PromType) {
    match points {
        Points::Sum {
            monotonic: true, ..
        } => (Kind::MonotonicCounter, PromType::Counter),
        Points::Sum { .. } => (Kind::NonMonotonicCounter, PromType::Gauge),
        Points::Gauge(_) => (Kind::Gauge, PromType::Gauge),
        Points::Histogram(_) => (Kind::Histogram, PromType::Histogram),
    }
}

fn with_scope(mut labels: Labels, scope: &Labels) -> Labels {
    for (name, value) in scope {
        set_label(&mut labels, name.clone(), value.clone());
    }
    labels
}

fn add_metric(
    families: &mut BTreeMap<String, Family>,
    metric: &MetricView,
    scope: &Labels,
    strategy: Strategy,
) {
    if super::is_health_metric(&metric.name) {
        return; // the collector's copy is appended instead
    }
    let (kind, prom_type) = kinds_of(&metric.points);
    let Some(name) = names::metric_name(&metric.name, &metric.unit, kind, strategy) else {
        return;
    };
    let family = families
        .entry(name.clone())
        .or_insert_with(|| Family::new(&name, prom_type, &metric.description));
    if family.kind != prom_type {
        return; // a second instrument under the same translated name but another type
    }
    match &metric.points {
        Points::Sum { points, .. } | Points::Gauge(points) => {
            for (attributes, value) in points {
                let labels = with_scope(translate_labels(attributes, strategy), scope);
                family.push(labels, *value);
            }
        }
        Points::Histogram(points) => {
            for point in points {
                let labels = with_scope(translate_labels(&point.attributes, strategy), scope);
                family.samples.extend(histogram_samples(point, labels));
            }
        }
    }
}

fn histogram_samples(point: &HistogramPoint, labels: Labels) -> Vec<Sample> {
    let mut samples = Vec::with_capacity(point.bounds.len() + 3);
    let mut running = 0u64;
    for (bound, count) in point.bounds.iter().zip(&point.bucket_counts) {
        running += count;
        let mut bucket = labels.clone();
        bucket.push(("le".to_string(), format_value(*bound)));
        samples.push(Sample {
            suffix: "_bucket",
            labels: bucket,
            value: running as f64,
        });
    }
    let mut inf = labels.clone();
    inf.push(("le".to_string(), "+Inf".to_string()));
    samples.push(Sample {
        suffix: "_bucket",
        labels: inf,
        value: point.count as f64,
    });
    samples.push(Sample {
        suffix: "_sum",
        labels: labels.clone(),
        value: point.sum,
    });
    samples.push(Sample {
        suffix: "_count",
        labels,
        value: point.count as f64,
    });
    samples
}

/// Format a sample value: the shortest round-trip form, with `NaN`, `+Inf` and
/// `-Inf` spelled as Prometheus expects and an exponent for very large or very
/// small magnitudes.
pub(crate) fn format_value(value: f64) -> String {
    if value.is_nan() {
        return "NaN".to_string();
    }
    if value.is_infinite() {
        return if value.is_sign_negative() {
            "-Inf"
        } else {
            "+Inf"
        }
        .to_string();
    }
    let magnitude = value.abs();
    if magnitude != 0.0 && !(1e-7..1e21).contains(&magnitude) {
        return format!("{value:e}");
    }
    format!("{value}")
}

fn is_legacy_name(name: &str) -> bool {
    let mut chars = name.chars();
    match chars.next() {
        Some(first) if first.is_ascii_alphabetic() || first == '_' || first == ':' => {}
        _ => return false,
    }
    chars.all(|c| c.is_ascii_alphanumeric() || c == '_' || c == ':')
}

fn is_legacy_label(name: &str) -> bool {
    !name.contains(':') && is_legacy_name(name)
}

fn escape_help(text: &str) -> String {
    text.replace('\\', "\\\\").replace('\n', "\\n")
}

/// Escape a label value or a quoted name: backslash, newline and double quote.
fn escape_quoted(text: &str) -> String {
    escape_help(text).replace('"', "\\\"")
}

fn label_pairs(labels: &Labels) -> Vec<String> {
    labels
        .iter()
        .map(|(name, value)| {
            let key = if is_legacy_label(name) {
                name.clone()
            } else {
                format!("\"{}\"", escape_quoted(name))
            };
            format!("{key}=\"{}\"", escape_quoted(value))
        })
        .collect()
}

fn sample_line(name: &str, labels: &Labels, value: f64) -> String {
    let pairs = label_pairs(labels);
    let value = format_value(value);
    if !is_legacy_name(name) {
        let rest: String = pairs.iter().map(|p| format!(",{p}")).collect();
        return format!("{{\"{}\"{rest}}} {value}", escape_quoted(name));
    }
    if pairs.is_empty() {
        return format!("{name} {value}");
    }
    format!("{name}{{{}}} {value}", pairs.join(","))
}

/// Render families as text exposition, HELP and TYPE first in each.
pub(crate) fn render(families: &[Family]) -> String {
    let mut lines: Vec<String> = Vec::new();
    for family in families {
        let header = if is_legacy_name(&family.name) {
            family.name.clone()
        } else {
            format!("\"{}\"", escape_quoted(&family.name))
        };
        if !family.help.is_empty() {
            lines.push(format!("# HELP {header} {}", escape_help(&family.help)));
        }
        lines.push(format!("# TYPE {header} {}", family.kind.as_str()));
        for sample in &family.samples {
            let name = format!("{}{}", family.name, sample.suffix);
            lines.push(sample_line(&name, &sample.labels, sample.value));
        }
    }
    if lines.is_empty() {
        return String::new();
    }
    lines.join("\n") + "\n"
}

#[cfg(test)]
#[path = "render_tests.rs"]
mod tests;
