// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.


namespace Provide.Telemetry;

public static class Sampling
{
    private static readonly object Gate = new();
    private static readonly Dictionary<string, SamplingPolicy> Policies = new(StringComparer.Ordinal);

    public static SamplingPolicy SetSamplingPolicy(string signal, SamplingPolicy policy)
    {
        Signals.Validate(signal);
        policy ??= new SamplingPolicy();
        var clamped = new SamplingPolicy
        {
            DefaultRate = ClampRate(policy.DefaultRate),
            Overrides = policy.Overrides is null
                ? null
                : policy.Overrides.ToDictionary(kv => kv.Key, kv => ClampRate(kv.Value), StringComparer.Ordinal),
        };
        lock (Gate)
        {
            Policies[signal] = clamped;
        }
        return clamped;
    }

    public static SamplingPolicy GetSamplingPolicy(string signal)
    {
        Signals.Validate(signal);
        lock (Gate)
        {
            return Policies.TryGetValue(signal, out var p)
                ? Clone(p)
                : new SamplingPolicy { DefaultRate = 1.0 };
        }
    }

    public static bool ShouldSample(string signal, string key)
    {
        var policy = GetSamplingPolicy(signal);
        var rate = policy.DefaultRate;
        if (policy.Overrides is not null && policy.Overrides.TryGetValue(key, out var over))
        {
            rate = over;
        }

        bool sampled;
        if (rate <= 0.0)
        {
            sampled = false;
        }
        else if (rate >= 1.0)
        {
            sampled = true;
        }
        else
        {
            sampled = Random.Shared.NextDouble() < rate;
        }

        // No Health.RecordDropped here. SignalPipeline.Admit rejects through
        // Reject(), which records the drop, so recording it here too counted a
        // sampled-out signal twice where a consent rejection counted once —
        // against SignalPipeline's own contract that admission accounting
        // happens exactly once. Backpressure.TryAcquire was moved off this
        // pattern for the same reason; sampling was missed.
        //
        // A caller invoking ShouldSample directly (PublicApi.ShouldSample) is
        // asking the sampler a question, not admitting a signal, and no longer
        // moves the counter.
        return sampled;
    }

    internal static void Reset()
    {
        lock (Gate) { Policies.Clear(); }
    }

    private static double ClampRate(double r)
    {
        if (double.IsNaN(r)) return 0.0;
        return Math.Clamp(r, 0.0, 1.0);
    }

    private static SamplingPolicy Clone(SamplingPolicy p) => new()
    {
        DefaultRate = p.DefaultRate,
        Overrides = p.Overrides is null
            ? null
            : new Dictionary<string, double>(p.Overrides, StringComparer.Ordinal),
    };
}
