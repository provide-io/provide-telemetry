use super::*;
use std::collections::HashMap;

#[test]
fn parse_module_levels_inserts_unknown_level_and_warns() {
    let map = parse_module_levels("foo=VERBOSE,bar=DEBUG");
    assert_eq!(
        map.get("foo").map(String::as_str),
        Some("VERBOSE"),
        "unknown level must still be inserted into the map"
    );
    assert_eq!(
        map.get("bar").map(String::as_str),
        Some("DEBUG"),
        "valid entry must not be affected by adjacent unknown entry"
    );
}

#[test]
fn parse_module_levels_valid_levels_no_warning() {
    let map =
        parse_module_levels("a=TRACE,b=DEBUG,c=INFO,d=WARN,e=WARNING,f=ERROR,g=CRITICAL,h=FATAL");
    assert_eq!(map.len(), 8, "all valid levels must parse");
}

#[test]
fn parse_module_levels_empty_input() {
    let map = parse_module_levels("");
    assert!(map.is_empty());
}

#[test]
fn parse_module_levels_skips_empty_module_name() {
    let map = parse_module_levels("=DEBUG,pkg=INFO");
    assert!(!map.contains_key(""), "empty module name must be skipped");
    assert_eq!(map.get("pkg").map(String::as_str), Some("INFO"));
}

#[test]
fn parse_module_levels_skips_empty_level() {
    let map = parse_module_levels("pkg=,other=DEBUG");
    assert!(!map.contains_key("pkg"), "empty level must be skipped");
    assert_eq!(map.get("other").map(String::as_str), Some("DEBUG"));
}

#[test]
fn parse_module_levels_trims_whitespace() {
    let map = parse_module_levels("  pkg = DEBUG , other = INFO ");
    assert_eq!(map.get("pkg").map(String::as_str), Some("DEBUG"));
    assert_eq!(map.get("other").map(String::as_str), Some("INFO"));
}

#[test]
fn parse_non_negative_float_rejects_invalid_and_negative_values() {
    let err =
        parse_non_negative_float(Some("abc"), 1.0, "FIELD").expect_err("nonnumeric must fail");
    assert!(err.message.contains("invalid float for FIELD"));

    let err =
        parse_non_negative_float(Some("-0.1"), 1.0, "FIELD").expect_err("negative float must fail");
    assert!(err.message.contains("FIELD must be >= 0"));
}

#[test]
fn parse_rate_rejects_values_above_one() {
    let err = parse_rate(Some("1.5"), 1.0, "RATE").expect_err("rate above one must fail");
    assert!(err.message.contains("RATE must be in [0, 1]"));
}

#[test]
fn parse_rate_rejects_negative_values() {
    let err = parse_rate(Some("-0.1"), 1.0, "RATE").expect_err("negative rate must fail");
    assert!(err.message.contains("RATE must be >= 0"));
}

#[test]
fn parse_rate_surfaces_invalid_float_errors() {
    let err = parse_rate(Some("nope"), 1.0, "RATE").expect_err("invalid rate must fail");
    assert!(err.message.contains("invalid float for RATE"));
}

#[test]
fn parse_rate_accepts_valid_fraction() {
    let rate = parse_rate(Some("0.25"), 1.0, "RATE").expect("valid rate should parse");
    assert!((rate - 0.25).abs() < f64::EPSILON);
}

#[test]
fn parse_rate_uses_default_for_missing_and_blank_values() {
    assert_eq!(
        parse_rate(None, 0.5, "RATE").expect("missing rate should use default"),
        0.5
    );
    assert_eq!(
        parse_rate(Some("  "), 0.25, "RATE").expect("blank rate should use default"),
        0.25
    );
}

#[test]
fn parse_otlp_headers_skips_pairs_with_invalid_percent_encoding() {
    let headers = parse_otlp_headers(Some("%ZZ=value,good=1,bad=%ZZ,ok=2"))
        .expect("a provided header string should yield a map");
    assert_eq!(headers.get("good").map(String::as_str), Some("1"));
    assert_eq!(headers.get("ok").map(String::as_str), Some("2"));
    assert!(!headers.contains_key("%ZZ"));
    assert!(!headers.contains_key("bad"));
}

#[test]
fn parse_module_levels_ignores_pairs_without_equals() {
    let map = parse_module_levels("noequals,pkg=INFO,other");
    assert_eq!(map.len(), 1);
    assert_eq!(map.get("pkg").map(String::as_str), Some("INFO"));
}

#[test]
fn nonempty_env_value_ignores_missing_and_blank_values() {
    let mut env = HashMap::new();
    env.insert("BLANK".to_string(), "   ".to_string());
    env.insert("VALUE".to_string(), "present".to_string());

    assert_eq!(nonempty_env_value(&env, &["MISSING"]), None);
    assert_eq!(nonempty_env_value(&env, &["BLANK"]), None);
    assert_eq!(nonempty_env_value(&env, &["VALUE"]), Some("present"));
}

#[test]
fn parse_otlp_headers_blank_string_returns_empty_map() {
    let headers = parse_otlp_headers(Some("   ")).expect("blank headers should still return a map");
    assert!(headers.is_empty());
}

#[test]
fn parse_otlp_headers_skips_pairs_without_separator_and_empty_keys() {
    let headers =
        parse_otlp_headers(Some("noequals,=value,good=1,also=2")).expect("headers should parse");
    assert_eq!(headers.get("good").map(String::as_str), Some("1"));
    assert_eq!(headers.get("also").map(String::as_str), Some("2"));
    assert_eq!(headers.len(), 2);
}

#[test]
fn parse_module_levels_skips_blank_pairs_and_trims_entries() {
    let map = parse_module_levels(" , pkg = INFO , , other = WARN ");
    assert_eq!(map.len(), 2);
    assert_eq!(map.get("pkg").map(String::as_str), Some("INFO"));
    assert_eq!(map.get("other").map(String::as_str), Some("WARN"));
}
