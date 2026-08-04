// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Text.Json;
using Provide.Telemetry;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

var caseId = Environment.GetEnvironmentVariable("PROVIDE_CONTRACT_CASE")
    ?? throw new InvalidOperationException("PROVIDE_CONTRACT_CASE required");

var fixturesPath = FindFixtures();
var yaml = File.ReadAllText(fixturesPath);
var deserializer = new DeserializerBuilder()
    .WithNamingConvention(UnderscoredNamingConvention.Instance)
    .IgnoreUnmatchedProperties()
    .Build();
var doc = deserializer.Deserialize<FixtureFile>(yaml)
    ?? throw new InvalidOperationException("empty fixtures");
if (!doc.ContractCases.TryGetValue(caseId, out var c))
{
    throw new InvalidOperationException($"unknown case {caseId}");
}

// Bound fields survive clear_propagation (mirrors Go baseCtx).
var boundFields = new Dictionary<string, object?>(StringComparer.Ordinal);
var variables = new Dictionary<string, object?>();
foreach (var step in c.Steps)
{
    RunStep(step, variables, boundFields);
}

var output = new Dictionary<string, object?>
{
    ["case"] = caseId,
    ["variables"] = variables,
};
Console.WriteLine(JsonSerializer.Serialize(output));

static string FindFixtures()
{
    var candidates = new[]
    {
        Path.GetFullPath(Path.Combine(Directory.GetCurrentDirectory(), "..", "spec", "contract_fixtures.yaml")),
        Path.GetFullPath(Path.Combine(Directory.GetCurrentDirectory(), "spec", "contract_fixtures.yaml")),
        Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "..", "spec", "contract_fixtures.yaml")),
        Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "spec", "contract_fixtures.yaml")),
        Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "..", "..", "spec", "contract_fixtures.yaml")),
    };
    foreach (var c in candidates)
    {
        if (File.Exists(c)) return c;
    }
    throw new FileNotFoundException("contract_fixtures.yaml not found; tried: " + string.Join(", ", candidates));
}

static void RunStep(Step s, Dictionary<string, object?> variables, Dictionary<string, object?> boundFields)
{
    switch (s.Op)
    {
        case "setup":
            Testing.ResetForTests();
            boundFields.Clear();
            Context.ClearContext();
            ApplyOverrides(s.Overrides);
            ProvideTelemetry.SetupTelemetry();
            break;
        case "setup_invalid":
            Testing.ResetForTests();
            boundFields.Clear();
            Context.ClearContext();
            ApplyOverrides(s.Overrides);
            try
            {
                ProvideTelemetry.SetupTelemetry();
                variables[s.Into ?? "err"] = new Dictionary<string, object?> { ["raised"] = false, ["error"] = "" };
            }
            catch (Exception ex)
            {
                variables[s.Into ?? "err"] = new Dictionary<string, object?> { ["raised"] = true, ["error"] = ex.Message };
            }
            break;
        case "shutdown":
            ProvideTelemetry.ShutdownTelemetry();
            break;
        case "flush":
            _ = ProvideTelemetry.FlushTelemetry();
            variables[s.Into ?? "flush"] = new Dictionary<string, object?> { ["ok"] = true };
            break;
        case "bind_propagation":
        {
            var headers = new Dictionary<string, string>();
            if (!string.IsNullOrEmpty(s.Traceparent)) headers["traceparent"] = s.Traceparent!;
            if (!string.IsNullOrEmpty(s.Baggage)) headers["baggage"] = s.Baggage!;
            var pc = ProvideTelemetry.ExtractW3CContext(headers);
            // Re-apply preserved bound fields after propagation overlay.
            ProvideTelemetry.BindPropagationContext(pc);
            if (boundFields.Count > 0)
            {
                ProvideTelemetry.BindContext(boundFields);
            }
            break;
        }
        case "clear_propagation":
            // Clear only propagation-derived state; restore bound fields.
            Context.ClearContext();
            if (boundFields.Count > 0)
            {
                ProvideTelemetry.BindContext(boundFields);
            }
            break;
        case "get_trace_context":
        {
            var tc = ProvideTelemetry.GetTraceContext();
            variables[s.Into ?? "tc"] = new Dictionary<string, object?>
            {
                ["trace_id"] = tc.TraceId,
                ["span_id"] = tc.SpanId,
            };
            break;
        }
        case "bind_context":
            if (s.Fields is not null)
            {
                foreach (var (k, v) in s.Fields)
                {
                    boundFields[k] = v;
                }
                ProvideTelemetry.BindContext(boundFields);
            }
            break;
        case "emit_log":
        {
            var sw = new StringWriter();
            var orig = Console.Error;
            Console.SetError(sw);
            var fields = s.Fields?.ToDictionary(kv => kv.Key, kv => (object?)kv.Value);
            ProvideTelemetry.GetLogger("probe").Info(s.Message ?? "event", fields);
            Console.SetError(orig);
            variables["__log_buffer"] = sw.ToString();
            break;
        }
        case "capture_log":
        {
            var buf = variables.GetValueOrDefault("__log_buffer")?.ToString() ?? "";
            Dictionary<string, object?>? parsed = null;
            foreach (var line in buf.Split('\n'))
            {
                var t = line.Trim();
                if (!t.StartsWith('{')) continue;
                try
                {
                    parsed = JsonSerializer.Deserialize<Dictionary<string, object?>>(t);
                    break;
                }
                catch { /* next */ }
            }
            parsed ??= new Dictionary<string, object?>();
            // Normalise dotted OTel-style keys to contract snake_case.
            if (parsed.TryGetValue("trace.id", out var tid))
            {
                parsed["trace_id"] = tid is JsonElement je ? je.GetString() : tid;
                parsed.Remove("trace.id");
            }
            if (parsed.TryGetValue("span.id", out var sid))
            {
                parsed["span_id"] = sid is JsonElement je2 ? je2.GetString() : sid;
                parsed.Remove("span.id");
            }
            // Unwrap JsonElement values for path resolution
            var plain = new Dictionary<string, object?>();
            foreach (var (k, v) in parsed)
            {
                plain[k] = Unwrap(v);
            }
            variables[s.Into ?? "log"] = plain;
            break;
        }
        case "register_secret_pattern":
            if (!string.IsNullOrEmpty(s.Name) && !string.IsNullOrEmpty(s.Pattern))
            {
                Pii.RegisterSecretPattern(s.Name!, new System.Text.RegularExpressions.Regex(s.Pattern!));
            }
            break;
        case "should_sample":
            variables[s.Into ?? "sampled"] = ProvideTelemetry.ShouldSample("logs", s.Name ?? "evt");
            break;
        case "get_runtime_status":
        {
            var st = ProvideTelemetry.GetRuntimeStatus();
            var cfg = ProvideTelemetry.GetRuntimeConfig();
            variables[s.Into ?? "status"] = new Dictionary<string, object?>
            {
                ["active"] = st.SetupDone,
                ["service_name"] = cfg?.ServiceName ?? "",
                ["setup_done"] = st.SetupDone,
                ["logs"] = st.Signals.Logs,
                ["traces"] = st.Signals.Traces,
                ["metrics"] = st.Signals.Metrics,
            };
            break;
        }
        default:
            break;
    }
}

static object? Unwrap(object? v)
{
    if (v is JsonElement je)
    {
        return je.ValueKind switch
        {
            JsonValueKind.String => je.GetString(),
            JsonValueKind.Number => je.TryGetInt64(out var l) ? l : je.GetDouble(),
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            JsonValueKind.Null => null,
            _ => je.ToString(),
        };
    }
    return v;
}

static void ApplyOverrides(Dictionary<string, object>? overrides)
{
    Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "json");
    if (overrides is null) return;
    if (overrides.TryGetValue("serviceName", out var sn))
        Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_SERVICE_NAME", sn?.ToString());
    if (overrides.TryGetValue("environment", out var env))
        Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_ENVIRONMENT", env?.ToString());
    if (overrides.TryGetValue("samplingLogsRate", out var lr))
        Environment.SetEnvironmentVariable("PROVIDE_SAMPLING_LOGS_RATE", lr?.ToString());
    if (overrides.TryGetValue("samplingTracesRate", out var tr))
        Environment.SetEnvironmentVariable("PROVIDE_SAMPLING_TRACES_RATE", tr?.ToString());
}

sealed class FixtureFile
{
    public Dictionary<string, ContractCase> ContractCases { get; set; } = new();
}
sealed class ContractCase
{
    public string? Description { get; set; }
    public List<Step> Steps { get; set; } = new();
    public Dictionary<string, object>? Expect { get; set; }
}
sealed class Step
{
    public string Op { get; set; } = "";
    public string? Traceparent { get; set; }
    public string? Baggage { get; set; }
    public string? Message { get; set; }
    public Dictionary<string, object>? Fields { get; set; }
    public string? Into { get; set; }
    public Dictionary<string, object>? Overrides { get; set; }
    public string? Name { get; set; }
    public string? Pattern { get; set; }
}
