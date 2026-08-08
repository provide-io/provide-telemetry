// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

namespace Provide.Telemetry;

internal static class Signals
{
    public const string Logs = "logs";
    public const string Traces = "traces";
    public const string Metrics = "metrics";
    /// <summary>Context/baggage binding (consent only; not a queue signal).</summary>
    public const string Context = "context";

    private static readonly HashSet<string> Valid = new(StringComparer.Ordinal)
    {
        Logs, Traces, Metrics,
    };

    public static void Validate(string signal)
    {
        if (!Valid.Contains(signal))
        {
            throw new ConfigurationError(
                $"unknown signal \"{signal}\", expected one of [logs, metrics, traces]");
        }
    }
}

/// <summary>Named stages of the canonical signal pipeline.</summary>
/// <remarks>
/// The order is fixed by <c>spec/pipeline_fixtures.yaml</c>. A stage may be
/// skipped on a rejection path, but two stages may never swap places.
/// </remarks>
internal static class PipelineStages
{
    public const string Consent = "consent";
    public const string Sampling = "sampling";
    public const string Backpressure = "backpressure";
    public const string Hardening = "hardening";
    public const string Pii = "pii";
    public const string Receipt = "receipt";
    public const string Local = "local";
    public const string Backend = "backend";
    public const string Health = "health";
    public const string Release = "release";

    public static readonly IReadOnlyList<string> CanonicalOrder = new[]
    {
        Consent, Sampling, Backpressure, Hardening, Pii, Receipt, Local, Backend, Health, Release,
    };
}

/// <summary>Observes pipeline stages as they run. Test-only seam.</summary>
internal interface ISignalPipelineObserver
{
    void OnStage(string stage);
}

/// <summary>
/// The result of admission control: whether to proceed, and the ticket to return.
/// </summary>
/// <remarks>
/// Carries the ticket rather than leaving it with the caller so that
/// <see cref="Release"/> is the single exit for every path — admitted or not.
/// </remarks>
internal readonly struct SignalAdmission
{
    private readonly QueueTicket? _ticket;

    private SignalAdmission(bool admitted, QueueTicket? ticket)
    {
        Admitted = admitted;
        _ticket = ticket;
    }

    public bool Admitted { get; }

    internal static SignalAdmission Accepted(QueueTicket? ticket) => new(true, ticket);

    internal static SignalAdmission Rejected(QueueTicket? ticket) => new(false, ticket);

    /// <summary>Return the queue ticket. Idempotent.</summary>
    public void Release() => Backpressure.Release(_ticket);
}

/// <summary>The one ordered path every signal takes.</summary>
internal static class SignalPipeline
{
    /// <summary>
    /// Run consent, sampling and backpressure for one signal.
    /// </summary>
    /// <remarks>
    /// Every emit site — the fallback instruments, the OTLP instruments, the
    /// logger — funnels through here so the three gates cannot drift apart or
    /// change order per call site, which is how the live metrics path came to
    /// check sampling that the live trace path did not.
    /// </remarks>
    /// <param name="signal">Canonical signal name.</param>
    /// <param name="samplingKey">Key the sampler hashes; the event or instrument name.</param>
    /// <param name="logLevel">Log level for consent; empty for non-log signals.</param>
    /// <param name="sample">
    /// False when the backend's own sampler already decided, so the event is not
    /// sampled twice.
    /// </param>
    /// <param name="observer">Optional stage recorder.</param>
    public static SignalAdmission Admit(
        string signal,
        string samplingKey,
        string logLevel = "",
        bool sample = true,
        ISignalPipelineObserver? observer = null)
    {
        if (!SignalEnabled(signal)) return SignalAdmission.Rejected(null);

        observer?.OnStage(PipelineStages.Consent);
        if (!Consent.ShouldAllow(signal, logLevel)) return Reject(signal, null, observer);

        if (sample)
        {
            observer?.OnStage(PipelineStages.Sampling);
            if (!Sampling.ShouldSample(signal, samplingKey)) return Reject(signal, null, observer);
        }

        observer?.OnStage(PipelineStages.Backpressure);
        var ticket = Backpressure.TryAcquire(signal);
        // A null ticket with an unlimited queue is not a rejection: TryAcquire
        // returns one only to say "nothing is bounded here".
        if (ticket is null && Backpressure.MaxSize(signal) > 0) return Reject(signal, null, observer);

        return SignalAdmission.Accepted(ticket);
    }

    /// <summary>Record the drop in health, then release — in that order.</summary>
    private static SignalAdmission Reject(string signal, QueueTicket? ticket, ISignalPipelineObserver? observer)
    {
        observer?.OnStage(PipelineStages.Health);
        Health.RecordDropped(signal);
        observer?.OnStage(PipelineStages.Release);
        Backpressure.Release(ticket);
        return SignalAdmission.Rejected(null);
    }

    /// <summary>
    /// Whether the runtime has this signal switched on at all.
    /// </summary>
    /// <remarks>
    /// A disabled signal is not a drop: nothing was ever offered to the
    /// pipeline, so counting it would make <c>metrics_dropped</c> climb on a
    /// service that deliberately runs without metrics.
    /// </remarks>
    private static bool SignalEnabled(string signal) => signal switch
    {
        Signals.Traces => Setup.IsTracingEnabled(),
        Signals.Metrics => Setup.IsMetricsEnabled(),
        _ => true,
    };

    /// <summary>
    /// Drive one log event through every stage, in canonical order.
    /// </summary>
    /// <remarks>
    /// The ticket is released in a <c>finally</c> so that exactly one release
    /// happens per admitted event whatever a later stage does — an exception out
    /// of a renderer used to leak queue capacity until the process restarted.
    /// </remarks>
    public static bool Process(LogDispatch dispatch, ISignalPipelineObserver? observer = null)
    {
        var admission = Admit(
            dispatch.Signal, dispatch.SamplingKey, dispatch.LogLevel, sample: true, observer);
        if (!admission.Admitted) return false;

        try
        {
            observer?.OnStage(PipelineStages.Hardening);
            var hardened = dispatch.Harden();

            observer?.OnStage(PipelineStages.Pii);
            var (sanitized, redactions) = dispatch.Sanitize(hardened);

            observer?.OnStage(PipelineStages.Receipt);
            Receipts.RecordAll(redactions);

            var record = dispatch.Build(sanitized);

            observer?.OnStage(PipelineStages.Local);
            dispatch.EmitLocal(record);

            var backend = dispatch.Backend;
            if (backend is not null)
            {
                observer?.OnStage(PipelineStages.Backend);
                backend(record);
            }

            observer?.OnStage(PipelineStages.Health);
            Health.RecordEmitted(dispatch.Signal);
            return true;
        }
        finally
        {
            observer?.OnStage(PipelineStages.Release);
            admission.Release();
        }
    }
}

/// <summary>Everything <see cref="SignalPipeline.Process"/> needs to run a log event.</summary>
internal sealed record LogDispatch
{
    public string Signal { get; init; } = Signals.Logs;
    public required string SamplingKey { get; init; }
    public required string LogLevel { get; init; }
    public required Func<Dictionary<string, object?>> Harden { get; init; }
    public required Func<
        Dictionary<string, object?>,
        (IReadOnlyDictionary<string, object?> Payload, IReadOnlyList<PendingRedaction> Redactions)> Sanitize
    { get; init; }
    public required Func<IReadOnlyDictionary<string, object?>, CanonicalLogRecord> Build { get; init; }
    public required Action<CanonicalLogRecord> EmitLocal { get; init; }
    public Action<CanonicalLogRecord>? Backend { get; init; }
}
