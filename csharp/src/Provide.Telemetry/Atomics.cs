// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

namespace Provide.Telemetry;

/// <summary>
/// A <see cref="double"/> that can be read and accumulated from many threads.
/// </summary>
/// <remarks>
/// .NET guarantees atomic reads and writes for 32-bit values, not for
/// <see cref="double"/>, and <c>_sum += value</c> is a read-modify-write in any
/// case. Gauges and histogram sums were plain fields, so two concurrent
/// <c>Record</c> calls could lose one of them — a metric that silently
/// undercounts under exactly the load worth measuring. Storing the bits in a
/// <see cref="long"/> lets <see cref="Interlocked"/> do the work.
/// </remarks>
internal sealed class AtomicDouble
{
    private long _bits;

    public double Read() => BitConverter.Int64BitsToDouble(Interlocked.Read(ref _bits));

    public void Write(double value) =>
        Interlocked.Exchange(ref _bits, BitConverter.DoubleToInt64Bits(value));

    public void Add(double value)
    {
        long before, after;
        do
        {
            before = Interlocked.Read(ref _bits);
            after = BitConverter.DoubleToInt64Bits(BitConverter.Int64BitsToDouble(before) + value);
        }
        while (Interlocked.CompareExchange(ref _bits, after, before) != before);
    }

    public void Reset() => Interlocked.Exchange(ref _bits, 0);
}

/// <summary>
/// Restores an <see cref="AsyncLocal{T}"/> to the value it had before a write.
/// </summary>
/// <remarks>
/// Spans used to clear the ambient trace context on dispose, so leaving an inner
/// span left the outer span's own log lines with no trace id at all. Capturing
/// the predecessor and putting it back makes nesting work. Disposal is
/// idempotent because a scope disposed twice — a <c>using</c> plus an explicit
/// call — would otherwise roll the slot back one level too far.
/// </remarks>
internal sealed class AsyncLocalScope<T> : IDisposable
{
    private readonly AsyncLocal<T> _slot;
    private readonly T _predecessor;
    private int _disposed;

    public AsyncLocalScope(AsyncLocal<T> slot, T predecessor)
    {
        _slot = slot;
        _predecessor = predecessor;
    }

    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) == 0)
        {
            _slot.Value = _predecessor;
        }
    }
}
