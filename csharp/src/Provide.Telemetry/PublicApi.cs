// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

namespace Provide.Telemetry;

/// <summary>
/// Public surface aliases so conformance scanners find the canonical names
/// at the Provide.Telemetry namespace level. Methods delegate to domain modules.
/// </summary>
public static class ProvideTelemetry
{
    // Lifecycle
    public static TelemetryConfig SetupTelemetry(TelemetryConfig? config = null) => Setup.SetupTelemetry(config);
    public static void ShutdownTelemetry() => Setup.ShutdownTelemetry();
    public static FlushResult FlushTelemetry(TimeSpan? timeout = null) => Setup.FlushTelemetry(timeout);

    // Logging
    public static Logger GetLogger(string name) => Logging.GetLogger(name);
    public static Logger Logger => Logging.Logger;
    public static void BindContext(IReadOnlyDictionary<string, object?> fields) => Context.BindContext(fields);
    public static void UnbindContext(params string[] keys) => Context.UnbindContext(keys);
    public static void ClearContext() => Context.ClearContext();
    public static void BindSessionContext(string sessionId) => Context.BindSessionContext(sessionId);
    public static string GetSessionID() => Context.GetSessionID();
    public static void ClearSessionContext() => Context.ClearSessionContext();

    // Tracing
    public static ITracer GetTracer(string name = "") => Tracing.GetTracer(name);
    public static ITracer Tracer => Tracing.Tracer;
    public static void Trace(string name, Action action) => Tracing.Trace(name, action);
    public static TraceContextValue GetTraceContext()
    {
        var (tid, sid) = Tracing.GetTraceContext();
        return new TraceContextValue(tid, sid);
    }

    public static void SetTraceContext(string traceId, string spanId) => Tracing.SetTraceContext(traceId, spanId);

    // Metrics
    public static IMeter GetMeter(string name = "") => Metrics.GetMeter(name);
    public static ICounter Counter(string name) => Metrics.Counter(name);
    public static IGauge Gauge(string name) => Metrics.Gauge(name);
    public static IHistogram Histogram(string name) => Metrics.Histogram(name);

    // Propagation
    public static PropagationContext ExtractW3CContext(IReadOnlyDictionary<string, string> headers) =>
        Propagation.ExtractW3CContext(headers);
    public static void BindPropagationContext(PropagationContext pc) => Propagation.BindPropagationContext(pc);
    public static void InjectTraceparent(IDictionary<string, string> headers) => Propagation.InjectTraceparent(headers);

    // Sampling
    public static SamplingPolicy GetSamplingPolicy(string signal) => Sampling.GetSamplingPolicy(signal);
    public static SamplingPolicy SetSamplingPolicy(string signal, SamplingPolicy policy) =>
        Sampling.SetSamplingPolicy(signal, policy);
    public static bool ShouldSample(string signal, string key) => Sampling.ShouldSample(signal, key);

    // Backpressure
    public static QueuePolicy GetQueuePolicy() => Backpressure.GetQueuePolicy();
    public static void SetQueuePolicy(QueuePolicy policy) => Backpressure.SetQueuePolicy(policy);

    // Resilience
    public static ExporterPolicy GetExporterPolicy(string signal) => Resilience.GetExporterPolicy(signal);
    public static void SetExporterPolicy(string signal, ExporterPolicy policy) =>
        Resilience.SetExporterPolicy(signal, policy);

    // Cardinality
    public static IReadOnlyDictionary<string, CardinalityLimit> GetCardinalityLimits() =>
        Cardinality.GetCardinalityLimits();
    public static void RegisterCardinalityLimit(string key, CardinalityLimit limit) =>
        Cardinality.RegisterCardinalityLimit(key, limit);
    public static void ClearCardinalityLimits() => Cardinality.ClearCardinalityLimits();
    public static Dictionary<string, string> GuardAttributes(IReadOnlyDictionary<string, string> attrs) =>
        Cardinality.GuardAttributes(attrs);

    // PII
    public static IReadOnlyList<PIIRule> GetPIIRules() => Pii.GetPIIRules();
    public static void RegisterPIIRule(PIIRule rule) => Pii.RegisterPIIRule(rule);
    public static void ReplacePIIRules(IEnumerable<PIIRule> rules) => Pii.ReplacePIIRules(rules);

    // Health
    public static HealthSnapshot GetHealthSnapshot() => Health.GetHealthSnapshot();

    // Schema
    public static EventRecord Event(params string[] segments) => Schema.Event(segments);
    public static void SetStrictSchema(bool enabled) => Schema.SetStrictSchema(enabled);
    public static bool GetStrictSchema() => Schema.GetStrictSchema();

    // Runtime
    public static TelemetryConfig? GetRuntimeConfig() => Setup.GetRuntimeConfig();
    public static void UpdateRuntimeConfig(RuntimeOverrides overrides) => Setup.UpdateRuntimeConfig(overrides);
    public static TelemetryConfig ReloadRuntimeFromEnv() => Setup.ReloadRuntimeFromEnv();
    public static TelemetryConfig ReconfigureTelemetry(TelemetryConfig? config = null) =>
        Setup.ReconfigureTelemetry(config);
    public static RuntimeStatus GetRuntimeStatus() => Setup.GetRuntimeStatus();

    // Governance
    public static void RegisterClassificationRules(IEnumerable<ClassificationRule> rules) =>
        Classification.RegisterClassificationRules(rules);
    public static void RegisterClassificationRule(ClassificationRule rule) =>
        Classification.RegisterClassificationRule(rule);
    public static DataClass? ClassifyKey(string key) => Classification.ClassifyKey(key);
    public static void SetClassificationPolicy(ClassificationPolicy policy) =>
        Classification.SetClassificationPolicy(policy);
    public static ClassificationPolicy GetClassificationPolicy() => Classification.GetClassificationPolicy();
    public static void SetConsentLevel(ConsentLevel level) => Consent.SetConsentLevel(level);
    public static ConsentLevel GetConsentLevel() => Consent.GetConsentLevel();
    public static bool ShouldAllow(string signal, string logLevel) => Consent.ShouldAllow(signal, logLevel);
    public static void LoadConsentFromEnv() => Consent.LoadConsentFromEnv();
    public static void EnableReceipts(
        bool enabled, string signingKey = "", string serviceName = "", IReceiptSink? sink = null) =>
        Receipts.EnableReceipts(enabled, signingKey, serviceName, sink);
    public static IReadOnlyList<RedactionReceipt> GetEmittedReceiptsForTests() =>
        Receipts.GetEmittedReceiptsForTests();
    public static Dictionary<string, object?> RedactConfig(TelemetryConfig c) => ConfigEnv.RedactConfig(c);
}

/// <summary>Test isolation helpers.</summary>
public static class Testing
{
    public static void ResetForTests() => Setup.ResetForTests();
}
