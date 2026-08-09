// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

/// <summary>
/// Field binding, unbinding, session identity and the clearing semantics of the
/// async-local context.
/// </summary>
[Collection("Telemetry")]
public class ContextBindingTests
{
    public ContextBindingTests() => Testing.ResetForTests();

    [Fact]
    public void BindContext_MergesSuccessiveCallsAndLastWriteWins()
    {
        Context.BindContext(new Dictionary<string, object?> { ["tenant"] = "acme", ["region"] = "eu" });
        Context.BindContext(new Dictionary<string, object?> { ["region"] = "us", ["user"] = "u1" });

        var bound = Context.GetBoundFields();

        Assert.Equal("acme", bound["tenant"]);
        Assert.Equal("us", bound["region"]);
        Assert.Equal("u1", bound["user"]);
    }

    [Fact]
    public void GetBoundFields_HandsBackACopyThatCannotWriteThroughToTheContext()
    {
        Context.BindContext(new Dictionary<string, object?> { ["tenant"] = "acme" });

        var snapshot = (Dictionary<string, object?>)Context.GetBoundFields();
        snapshot["tenant"] = "tampered";
        snapshot["injected"] = true;

        Assert.Equal("acme", Context.GetBoundFields()["tenant"]);
        Assert.False(Context.GetBoundFields().ContainsKey("injected"));
    }

    [Fact]
    public void UnbindContext_RemovesOnlyTheNamedKeys()
    {
        Context.BindContext(new Dictionary<string, object?>
        {
            ["tenant"] = "acme",
            ["region"] = "eu",
            ["user"] = "u1",
        });

        Context.UnbindContext("region", "user", "never-bound");

        var bound = Context.GetBoundFields();
        Assert.Equal(new[] { "tenant" }, bound.Keys.ToArray());
    }

    [Fact]
    public void UnbindContext_OnAnEmptyContextIsANoOp()
    {
        Context.UnbindContext("tenant");

        Assert.Empty(Context.GetBoundFields());
    }

    [Fact]
    public void ClearContext_DropsFieldsAndTraceAndPropagationButKeepsTheSessionId()
    {
        // The session outlives a single request's fields on purpose: a session id
        // is bound once at connect and re-bound by BindSessionContext, so
        // clearing per-request state must not silently orphan it.
        Context.BindSessionContext("sess-1");
        Context.BindContext(new Dictionary<string, object?> { ["tenant"] = "acme" });
        Context.SetTraceContext("0af7651916cd43dd8448eb211c80319c", "b7ad6b7169203331");
        Propagation.BindPropagationContext(new PropagationContext { Traceparent = "tp" });

        Context.ClearContext();

        Assert.Empty(Context.GetBoundFields());
        Assert.Equal(("", ""), Context.GetTraceContext());
        Assert.Equal("", Context.GetPropagationContext().Traceparent);
        Assert.Equal("sess-1", Context.GetSessionID());
    }

    [Fact]
    public void BindSessionContext_PublishesTheIdBothAsTheSessionAndAsABoundField()
    {
        Context.BindSessionContext("sess-42");

        Assert.Equal("sess-42", Context.GetSessionID());
        Assert.Equal("sess-42", Context.GetBoundFields()["session_id"]);
    }

    [Fact]
    public void BindSessionContext_ReplacesAPreviousSession()
    {
        Context.BindSessionContext("sess-1");
        Context.BindSessionContext("sess-2");

        Assert.Equal("sess-2", Context.GetSessionID());
        Assert.Equal("sess-2", Context.GetBoundFields()["session_id"]);
    }

    [Fact]
    public void ClearSessionContext_RemovesBothTheIdAndItsBoundFieldAndLeavesOthers()
    {
        Context.BindContext(new Dictionary<string, object?> { ["tenant"] = "acme" });
        Context.BindSessionContext("sess-1");

        Context.ClearSessionContext();

        Assert.Equal("", Context.GetSessionID());
        Assert.False(Context.GetBoundFields().ContainsKey("session_id"));
        Assert.Equal("acme", Context.GetBoundFields()["tenant"]);
    }

    [Fact]
    public void GetSessionID_IsEmptyRatherThanNullWhenNothingIsBound()
    {
        Assert.Equal("", Context.GetSessionID());
    }

    [Fact]
    public void SetTraceContext_TreatsNullIdentifiersAsEmpty()
    {
        Context.SetTraceContext(null!, null!);

        Assert.Equal(("", ""), Context.GetTraceContext());
    }

    [Fact]
    public void GetPropagationContext_DefaultsToAnEmptyContextRatherThanNull()
    {
        var pc = Context.GetPropagationContext();

        Assert.Equal("", pc.Traceparent);
        Assert.Equal("", pc.Tracestate);
        Assert.Equal("", pc.Baggage);
    }

    [Fact]
    public void BindContext_IsRefusedWhenConsentForbidsContext()
    {
        // Functional consent permits logs, traces and metrics but not context or
        // baggage: binding must be a no-op rather than a silent leak of the
        // identity fields the caller was told would not be collected.
        Consent.SetConsentLevel(ConsentLevel.Functional);

        Context.BindContext(new Dictionary<string, object?> { ["tenant"] = "acme" });
        Context.BindSessionContext("sess-1");

        Assert.Empty(Context.GetBoundFields());
        // The session slot itself is not consent-gated; only the bound field is.
        Assert.Equal("sess-1", Context.GetSessionID());
    }

    [Fact]
    public async Task BoundFieldsDoNotLeakBetweenConcurrentTasks()
    {
        Context.BindContext(new Dictionary<string, object?> { ["tenant"] = "root" });

        var observed = await Task.WhenAll(
            Task.Run(() =>
            {
                Context.BindContext(new Dictionary<string, object?> { ["tenant"] = "a" });
                return (string?)Context.GetBoundFields()["tenant"];
            }),
            Task.Run(() =>
            {
                Context.BindContext(new Dictionary<string, object?> { ["tenant"] = "b" });
                return (string?)Context.GetBoundFields()["tenant"];
            }));

        Assert.Equal(new[] { "a", "b" }, observed);
        Assert.Equal("root", Context.GetBoundFields()["tenant"]);
    }
}
