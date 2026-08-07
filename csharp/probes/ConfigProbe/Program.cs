// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
// Emit observed config metadata for the C# SDK.
//
// The probe never reads spec/telemetry-api.yaml. Applicability is determined
// differentially: build the config with a clean environment for the baseline,
// then rebuild once per variable with that variable set. A variable this SDK
// parses changes the config; one it ignores leaves it identical. The reported
// default and type come from the baseline config object, reached by reflection
// rather than declared by hand.

using System.Collections;
using System.Globalization;
using System.Reflection;
using System.Text.Json;
using System.Text.Json.Nodes;

using Provide.Telemetry;

// Values chosen to differ from every spec default, including valid values for
// validated fields (a rejected value proves the variable is read but leaves no
// config object to diff).
string[] probeValues =
[
    "DEBUG", "json", "red", "3", "1327", "0.4271", "probe-sentinel-value",
    "false", "true", "http://probe.invalid:4318", "probe-module=DEBUG", "probe-key=probe-value",
];

string[] ownedPrefixes = ["PROVIDE_", "OTEL_"];

var envVars = args;
if (envVars.Length == 0)
{
    Console.Error.WriteLine("usage: ConfigProbe ENV_VAR [ENV_VAR ...]");
    return 2;
}

var baseEnv = CleanEnv();
if (!TryBuild(baseEnv, out var baseline, out var kinds))
{
    Console.Error.WriteLine("baseline config failed");
    return 1;
}

var entries = new JsonObject();
foreach (var envVar in envVars)
{
    var settled = false;
    var rejected = false;

    foreach (var probeValue in probeValues)
    {
        var env = new Dictionary<string, string>(baseEnv) { [envVar] = probeValue };
        if (!TryBuild(env, out var observed, out _))
        {
            rejected = true; // a rejected value still proves the variable is read
            continue;
        }

        var changed = baseline.Keys
            .Where(k => observed.ContainsKey(k) && observed[k] != baseline[k])
            .OrderBy(k => k, StringComparer.Ordinal)
            .FirstOrDefault();

        if (changed is not null)
        {
            entries[envVar] = new JsonObject
            {
                ["type"] = kinds[changed],
                ["default"] = DefaultInVariableUnits(baseline[changed], probeValue, observed[changed]),
                ["applicable"] = true,
            };
            settled = true;
            break;
        }

        // A key the probe *added* counts too: an empty dictionary contributes no
        // flattened keys, so comparing only shared keys would read as "ignored".
        if (observed.Keys.Any(k => !baseline.ContainsKey(k)))
        {
            entries[envVar] = new JsonObject { ["type"] = "str", ["default"] = "", ["applicable"] = true };
            settled = true;
            break;
        }
    }

    if (!settled)
    {
        entries[envVar] = new JsonObject { ["type"] = "", ["default"] = "", ["applicable"] = rejected };
    }
}

var payload = new JsonObject { ["language"] = "csharp", ["entries"] = entries };
Console.WriteLine(payload.ToJsonString(new JsonSerializerOptions { WriteIndented = false }));
return 0;

Dictionary<string, string> CleanEnv()
{
    var env = new Dictionary<string, string>(StringComparer.Ordinal);
    foreach (DictionaryEntry kv in System.Environment.GetEnvironmentVariables())
    {
        var key = kv.Key.ToString()!;
        if (!ownedPrefixes.Any(p => key.StartsWith(p, StringComparison.Ordinal)))
        {
            env[key] = kv.Value?.ToString() ?? "";
        }
    }
    return env;
}

bool TryBuild(
    Dictionary<string, string> env,
    out Dictionary<string, string> values,
    out Dictionary<string, string> kinds)
{
    var saved = new Dictionary<string, string?>(StringComparer.Ordinal);
    foreach (DictionaryEntry kv in System.Environment.GetEnvironmentVariables())
    {
        saved[kv.Key.ToString()!] = kv.Value?.ToString();
    }

    foreach (var key in saved.Keys) System.Environment.SetEnvironmentVariable(key, null);
    foreach (var (key, value) in env) System.Environment.SetEnvironmentVariable(key, value);

    values = new Dictionary<string, string>(StringComparer.Ordinal);
    kinds = new Dictionary<string, string>(StringComparer.Ordinal);
    try
    {
        var cfg = ConfigEnv.ConfigFromEnv();
        Flatten(cfg, "", values, kinds);
        return true;
    }
    catch
    {
        return false;
    }
    finally
    {
        foreach (var key in env.Keys) System.Environment.SetEnvironmentVariable(key, null);
        foreach (var (key, value) in saved) System.Environment.SetEnvironmentVariable(key, value);
    }
}

// Flatten the config graph into dotted-path -> rendered scalar. Dictionaries and
// sequences render as strings so comparison is by value; comparing them as
// objects would make every field look changed on every call.
static void Flatten(object? node, string prefix, Dictionary<string, string> values, Dictionary<string, string> kinds)
{
    var key = prefix.TrimEnd('.');
    if (node is null)
    {
        values[key] = "";
        kinds[key] = "str";
        return;
    }

    switch (node)
    {
        case string s:
            values[key] = s;
            kinds[key] = "str";
            return;
        case bool b:
            values[key] = b ? "true" : "false";
            kinds[key] = "bool";
            return;
        case double or float or decimal:
            values[key] = Convert.ToDouble(node, CultureInfo.InvariantCulture)
                .ToString("R", CultureInfo.InvariantCulture);
            kinds[key] = "float";
            return;
        case sbyte or byte or short or ushort or int or uint or long or ulong:
            values[key] = Convert.ToInt64(node, CultureInfo.InvariantCulture)
                .ToString(CultureInfo.InvariantCulture);
            kinds[key] = "int";
            return;
        case IDictionary dict:
        {
            var pairs = dict.Keys.Cast<object>()
                .Select(k => $"{k}={dict[k]}")
                .OrderBy(x => x, StringComparer.Ordinal);
            values[key] = string.Join(",", pairs);
            kinds[key] = "str";
            return;
        }
        case IEnumerable seq:
            values[key] = string.Join(",", seq.Cast<object?>().Select(x => x?.ToString() ?? ""));
            kinds[key] = "str";
            return;
    }

    foreach (var prop in node.GetType()
                 .GetProperties(BindingFlags.Public | BindingFlags.Instance)
                 .Where(p => p.CanRead && p.GetIndexParameters().Length == 0)
                 .OrderBy(p => p.Name, StringComparer.Ordinal))
    {
        object? value;
        try { value = prop.GetValue(node); }
        catch { continue; }
        Flatten(value, $"{prefix}{prop.Name}.", values, kinds);
    }
}

// Express a numeric default in the units the environment variable uses. An SDK
// may store a `..._TIMEOUT_SECONDS` value in milliseconds; rather than
// hardcoding which fields are scaled, measure the SDK's own conversion factor
// from a known probe value.
static string DefaultInVariableUnits(string baseline, string probeValue, string observed)
{
    var culture = CultureInfo.InvariantCulture;
    if (!double.TryParse(baseline, NumberStyles.Float, culture, out var baseNum)
        || !double.TryParse(probeValue, NumberStyles.Float, culture, out var probed)
        || !double.TryParse(observed, NumberStyles.Float, culture, out var obs)
        || probed == 0 || obs == 0)
    {
        return baseline;
    }

    var scale = obs / probed;
    if (scale == 1 || scale <= 0 || scale != Math.Truncate(scale)) return baseline;
    return (baseNum / scale).ToString("R", culture);
}
