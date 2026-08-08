use super::*;

/// A variable no parser reads must report itself inapplicable rather than
/// inheriting the previous variable's answer.
#[test]
fn probe_test_unknown_variable_is_reported_inapplicable() {
    let probed = config_defaults_probe(&["PROVIDE_NOT_A_REAL_VARIABLE".to_string()]);
    let entry = &probed["PROVIDE_NOT_A_REAL_VARIABLE"];

    assert!(!entry.applicable);
    assert_eq!(entry.type_name, "");
    assert_eq!(entry.default, "");
}

#[test]
fn probe_test_reports_observed_type_and_default_for_a_parsed_variable() {
    let probed = config_defaults_probe(&[
        "PROVIDE_LOG_LEVEL".to_string(),
        "PROVIDE_TRACE_ENABLED".to_string(),
        "PROVIDE_SAMPLING_LOGS_RATE".to_string(),
        "PROVIDE_BACKPRESSURE_LOGS_MAXSIZE".to_string(),
    ]);

    assert_eq!(probed["PROVIDE_LOG_LEVEL"].type_name, "str");
    assert_eq!(probed["PROVIDE_LOG_LEVEL"].default, "INFO");
    assert_eq!(probed["PROVIDE_TRACE_ENABLED"].type_name, "bool");
    assert_eq!(probed["PROVIDE_TRACE_ENABLED"].default, "true");
    assert_eq!(probed["PROVIDE_SAMPLING_LOGS_RATE"].type_name, "float");
    assert_eq!(probed["PROVIDE_SAMPLING_LOGS_RATE"].default, "1.0");
    assert_eq!(probed["PROVIDE_BACKPRESSURE_LOGS_MAXSIZE"].type_name, "int");
    assert_eq!(probed["PROVIDE_BACKPRESSURE_LOGS_MAXSIZE"].default, "0");
}

/// A map-valued variable adds flattened keys instead of changing existing ones,
/// so the "new key" arm is the only thing that can detect it.
#[test]
fn probe_test_detects_variables_that_only_add_keys() {
    let probed = config_defaults_probe(&["OTEL_EXPORTER_OTLP_LOGS_HEADERS".to_string()]);
    let entry = &probed["OTEL_EXPORTER_OTLP_LOGS_HEADERS"];

    assert!(entry.applicable);
    assert_eq!(entry.type_name, "str");
    assert_eq!(entry.default, "");
}

/// A variable whose every probe value is rejected leaves nothing to measure,
/// but a rejection is still proof the parser read it.
#[test]
fn probe_test_a_variable_only_ever_rejected_is_still_applicable() {
    let baseline = build(&HashMap::new()).expect("empty environment must yield a config");

    let entry = probe_one(&baseline, "PROVIDE_LOG_INCLUDE_TIMESTAMP", &["not-a-bool"])
        .expect("a rejected value must still report the variable as read");

    assert!(entry.applicable);
    assert_eq!(entry.type_name, "");
    assert_eq!(entry.default, "");
}

#[test]
fn probe_test_serializes_type_under_its_spec_name() {
    let json = serde_json::to_value(ProbedConfigEntry {
        type_name: "int".to_string(),
        default: "7".to_string(),
        applicable: true,
    })
    .expect("entry should serialize");

    assert_eq!(json["type"], "int");
    assert_eq!(json["default"], "7");
    assert_eq!(json["applicable"], true);
}

/// The scale is measured from the probe value, so a config that stores a
/// variable in different units still reports the default in the variable's own.
#[test]
fn probe_test_scaled_defaults_are_expressed_in_variable_units() {
    // Baseline 10000 stored units, probe of 3 observed as 3000 => scale 1000.
    assert_eq!(default_in_variable_units("10000", "3", "3000"), "10");
    // A non-integer scale is not a unit conversion — report the baseline as-is.
    assert_eq!(default_in_variable_units("10000", "3", "4000"), "10000");
    // Scale 1 means the units already agree.
    assert_eq!(default_in_variable_units("10", "3", "3"), "10");
    // A negative scale is nonsense as a unit conversion.
    assert_eq!(default_in_variable_units("10", "3", "-6"), "10");
    // Non-numeric values have no units to convert.
    assert_eq!(default_in_variable_units("INFO", "DEBUG", "DEBUG"), "INFO");
    // Zero on either side would divide the measurement away.
    assert_eq!(default_in_variable_units("10", "0", "5"), "10");
    assert_eq!(default_in_variable_units("10", "3", "0"), "10");
    // A fractional result keeps its fraction rather than truncating to an int.
    assert_eq!(default_in_variable_units("5", "1", "2"), "2.5");
}
