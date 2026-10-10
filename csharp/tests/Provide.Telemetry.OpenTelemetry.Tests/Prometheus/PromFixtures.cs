// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using YamlDotNet.Serialization;

namespace Provide.Telemetry.OpenTelemetry.Tests.Prometheus;

/// <summary>Reads spec/prometheus_fixtures.yaml; the cases are never copied into C#.</summary>
internal static class PromFixtures
{
    private static readonly Lazy<Dictionary<object, object?>> Root = new(Load);

    public static List<Dictionary<object, object?>> Section(string name) =>
        ((List<object?>)Root.Value[name]!).Cast<Dictionary<object, object?>>().ToList();

    /// <summary>xUnit MemberData rows: (id, case) for one section.</summary>
    public static IEnumerable<object[]> Rows(string name) =>
        Section(name).Select((c, i) => new object[] { Id(c, i), c });

    public static string Id(Dictionary<object, object?> c, int index) =>
        c.TryGetValue("id", out var id) && id is string s ? s : $"{index}";

    public static string? Str(this Dictionary<object, object?> c, string key) =>
        c.TryGetValue(key, out var v) ? v as string : null;

    public static bool Flag(this Dictionary<object, object?> c, string key) =>
        c.TryGetValue(key, out var v) && v is string s && s == "true";

    public static Dictionary<object, object?>? Map(this Dictionary<object, object?> c, string key) =>
        c.TryGetValue(key, out var v) ? v as Dictionary<object, object?> : null;

    public static List<string> Strings(this Dictionary<object, object?> c, string key) =>
        ((List<object?>)c[key]!).Select(x => (string)x!).ToList();

    public static string RepoRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "spec", "prometheus_fixtures.yaml")))
            {
                return directory.FullName;
            }
            directory = directory.Parent;
        }
        throw new FileNotFoundException("spec/prometheus_fixtures.yaml not found from " + AppContext.BaseDirectory);
    }

    private static Dictionary<object, object?> Load()
    {
        var text = File.ReadAllText(Path.Combine(RepoRoot(), "spec", "prometheus_fixtures.yaml"));
        return new DeserializerBuilder().Build().Deserialize<Dictionary<object, object?>>(text);
    }
}
