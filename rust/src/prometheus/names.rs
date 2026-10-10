// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Prometheus metric and label name translation.
//!
//! A port of github.com/prometheus/otlptranslator v1.0.0 (MetricNamer and
//! LabelNamer, without namespaces), the reference named by
//! `prometheus_metrics.translation` in `spec/telemetry-api.yaml`, by way of the
//! Python port in `metrics/_prom_names.py`. The cases in
//! `spec/prometheus_fixtures.yaml` were generated from that library, so this
//! module must reproduce it exactly rather than approximate it.

/// How an OTel instrument's data is shaped, as far as naming is concerned.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Kind {
    MonotonicCounter,
    NonMonotonicCounter,
    Gauge,
    Histogram,
}

/// The two independent choices a translation strategy makes.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct Strategy {
    /// Names are escaped to the legacy character set.
    pub(crate) escapes: bool,
    /// Unit, `_total` and `_ratio` suffixes are appended.
    pub(crate) suffixes: bool,
}

impl Strategy {
    /// The strategy a `PROVIDE_METRICS_PROMETHEUS_TRANSLATION` value names.
    pub(crate) fn named(name: &str) -> Self {
        Self {
            escapes: name.starts_with("UnderscoreEscaping"),
            suffixes: name.ends_with("WithSuffixes"),
        }
    }
}

fn unit_word(unit: &str) -> &str {
    match unit {
        "d" => "days",
        "h" => "hours",
        "min" => "minutes",
        "s" => "seconds",
        "ms" => "milliseconds",
        "us" => "microseconds",
        "ns" => "nanoseconds",
        "By" => "bytes",
        "KiBy" => "kibibytes",
        "MiBy" => "mebibytes",
        "GiBy" => "gibibytes",
        "TiBy" => "tibibytes",
        "KBy" => "kilobytes",
        "MBy" => "megabytes",
        "GBy" => "gigabytes",
        "TBy" => "terabytes",
        "m" => "meters",
        "V" => "volts",
        "A" => "amperes",
        "J" => "joules",
        "W" => "watts",
        "g" => "grams",
        "Cel" => "celsius",
        "Hz" => "hertz",
        "1" => "",
        "%" => "percent",
        other => other,
    }
}

fn per_unit_word(unit: &str) -> &str {
    match unit {
        "s" => "second",
        "m" => "minute",
        "h" => "hour",
        "d" => "day",
        "w" => "week",
        "mo" => "month",
        "y" => "year",
        other => other,
    }
}

fn is_legacy_name_char(c: char) -> bool {
    c.is_ascii_alphanumeric() || c == ':'
}

/// Split `name` on runs of characters `keep` rejects, dropping empty fields
/// (Go's strings.FieldsFunc).
fn tokens(name: &str, keep: fn(char) -> bool) -> Vec<String> {
    name.split(|c: char| !keep(c))
        .filter(|token| !token.is_empty())
        .map(str::to_string)
        .collect()
}

/// Replace each run of characters `keep` rejects with one `_`.
fn collapse_invalid(text: &str, keep: fn(char) -> bool) -> String {
    let mut out = String::with_capacity(text.len());
    let mut in_run = false;
    for c in text.chars() {
        if keep(c) {
            out.push(c);
            in_run = false;
        } else if !in_run {
            out.push('_');
            in_run = true;
        }
    }
    out
}

fn clean_up_unit(unit: &str) -> String {
    let collapsed = collapse_invalid(unit, is_legacy_name_char);
    match collapsed.strip_prefix('_') {
        Some(rest) => rest.to_string(),
        None => collapsed,
    }
}

/// A unit as written, or "" when blank or an `{annotation}`.
fn unit_suffix(unit: &str) -> &str {
    let unit = unit.trim();
    if unit.contains('{') || unit.contains('}') {
        return "";
    }
    unit
}

/// The main and per-unit suffixes for `unit`, e.g. ("bytes", "per_second") for `By/s`.
fn unit_suffixes(unit: &str) -> (String, String) {
    let (main_otel, per_otel) = unit.split_once('/').unwrap_or((unit, ""));
    let main = unit_word(unit_suffix(main_otel)).to_string();
    let per = unit_suffix(per_otel);
    if per.is_empty() {
        return (main, String::new());
    }
    (main, format!("per_{}", per_unit_word(per)))
}

fn add_unit_tokens(mut tokens: Vec<String>, main: String, per: String) -> Vec<String> {
    let mut main = if tokens.contains(&main) {
        String::new()
    } else {
        main
    };
    // The reference also drops a per suffix already among the tokens, but that
    // cannot happen: tokens never contain "_" and a per suffix always does.
    let per = if per == "per_" {
        String::new()
    } else {
        per.strip_suffix('_').unwrap_or(&per).to_string()
    };
    if !per.is_empty() {
        main = main.strip_suffix('_').unwrap_or(&main).to_string();
    }
    tokens.extend([main, per].into_iter().filter(|token| !token.is_empty()));
    tokens
}

fn prefix_leading_digit(name: String) -> String {
    if name.starts_with(|c: char| c.is_ascii_digit()) {
        return format!("_{name}");
    }
    name
}

/// Move `word` to the end of `tokens`, dropping any earlier copies.
fn last_token(tokens: Vec<String>, word: &str) -> Vec<String> {
    let mut kept: Vec<String> = tokens.into_iter().filter(|t| t != word).collect();
    kept.push(word.to_string());
    kept
}

/// Full escaping normalization with suffixes (otlptranslator normalizeName).
fn normalize(name: &str, unit: &str, kind: Kind) -> String {
    let (main, per) = unit_suffixes(unit);
    let mut parts = add_unit_tokens(
        tokens(name, is_legacy_name_char),
        clean_up_unit(&main),
        clean_up_unit(&per),
    );
    if kind == Kind::MonotonicCounter {
        parts = last_token(parts, "total");
    }
    if unit == "1" && kind == Kind::Gauge {
        parts = last_token(parts, "ratio");
    }
    prefix_leading_digit(parts.join("_"))
}

/// Trim `suffix` plus one delimiter character, when something is left before it.
fn trim_suffix(name: String, suffix: &str) -> String {
    match name.strip_suffix(suffix) {
        Some(rest) if rest.chars().count() > 1 => {
            let mut rest = rest.to_string();
            rest.pop();
            rest
        }
        _ => name,
    }
}

/// UTF-8 naming with suffixes (otlptranslator buildMetricName).
///
/// Outer suffixes are trimmed first and re-appended last, so the result reads
/// name, main unit, per unit, then `_total` or `_ratio`.
fn utf8_with_suffixes(name: &str, unit: &str, kind: Kind) -> String {
    let mut name = name.to_string();
    let mut outer = "";
    if unit == "1" && kind == Kind::Gauge {
        name = trim_suffix(name, "ratio");
        outer = "_ratio";
    }
    if kind == Kind::MonotonicCounter {
        name = trim_suffix(name, "total");
        outer = "_total";
    }
    let (main, per) = unit_suffixes(unit);
    let mut per_suffix = String::new();
    if !per.is_empty() {
        name = trim_suffix(name, &per);
        per_suffix = format!("_{per}");
    }
    if !main.is_empty() && !name.ends_with(&main) {
        name = format!("{name}_{main}");
    }
    format!("{name}{per_suffix}{outer}")
}

/// Translate an OTel instrument name into a Prometheus metric name, or `None`
/// when translation leaves no usable name, as the reference rejects it.
pub(crate) fn metric_name(name: &str, unit: &str, kind: Kind, strategy: Strategy) -> Option<String> {
    if !strategy.escapes {
        if strategy.suffixes {
            return Some(utf8_with_suffixes(name, unit, kind));
        }
        return Some(name.to_string());
    }
    let result = if strategy.suffixes {
        normalize(name, unit, kind)
    } else {
        let keep = |c: char| is_legacy_name_char(c) || c == '_';
        prefix_leading_digit(tokens(name, keep).join("_"))
    };
    if result.is_empty() || (result != name && result.trim_matches('_').is_empty()) {
        return None;
    }
    Some(result)
}

/// Translate an attribute key into a Prometheus label name, or `None` for an
/// empty key or one the reference cannot translate.
pub(crate) fn label_name(attribute: &str, strategy: Strategy) -> Option<String> {
    if attribute.trim_matches('_').is_empty() {
        return None;
    }
    if !strategy.escapes {
        return Some(attribute.to_string());
    }
    // A key that starts and ends with "__" keeps both; shorter such keys are all
    // underscores and were rejected above.
    let reserved = attribute.starts_with("__") && attribute.ends_with("__");
    let body = if reserved {
        &attribute[2..attribute.len() - 2]
    } else {
        attribute
    };
    let mut sanitized = collapse_invalid(body, |c| c.is_ascii_alphanumeric());
    if reserved {
        sanitized = format!("__{sanitized}__");
    }
    if sanitized.starts_with(|c: char| c.is_ascii_digit()) {
        sanitized = format!("key_{sanitized}");
    }
    if sanitized.trim_matches('_').is_empty() {
        return None;
    }
    Some(sanitized)
}

#[cfg(test)]
#[path = "names_tests.rs"]
mod tests;
