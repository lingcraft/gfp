// net48 缺少 C# 8 的 Index/Range（".." 范围运算符）类型，补 polyfill。
// 编译器会把 string[range] 降级为 string.Substring(range.GetOffsetAndLength(len))。
namespace System
{
    internal readonly struct Index : IEquatable<Index>
    {
        private readonly int _value;
        public Index(int value, bool fromEnd = false)
        {
            if (value < 0) throw new ArgumentOutOfRangeException(nameof(value), "Non-negative number required.");
            _value = fromEnd ? ~value : value;
        }
        public int Value => _value < 0 ? ~_value : _value;
        public bool IsFromEnd => _value < 0;
        public int GetOffset(int length)
        {
            int offset = _value;
            if (IsFromEnd) offset += length + 1;
            return offset;
        }
        public static Index FromStart(int value) => new Index(value);
        public static Index FromEnd(int value) => new Index(value, fromEnd: true);
        public static implicit operator Index(int value) => FromStart(value);
        public bool Equals(Index other) => _value == other._value;
        public override bool Equals(object obj) => obj is Index other && Equals(other);
        public override int GetHashCode() => _value;
        public override string ToString() => IsFromEnd ? $"^{Value}" : Value.ToString();
    }

    internal readonly struct Range : IEquatable<Range>
    {
        public Index Start { get; }
        public Index End { get; }
        public Range(Index start, Index end) { Start = start; End = end; }
        public (int Offset, int Length) GetOffsetAndLength(int length)
        {
            int start = Start.GetOffset(length);
            int end = End.GetOffset(length);
            if ((uint)end > (uint)length || (uint)start > (uint)end)
                throw new ArgumentOutOfRangeException(nameof(length));
            return (start, end - start);
        }
        public static Range StartAt(Index start) => new Range(start, Index.FromEnd(0));
        public static Range EndAt(Index end) => new Range(Index.FromStart(0), end);
        public static Range All() => new Range(Index.FromStart(0), Index.FromEnd(0));
        public bool Equals(Range other) => Start.Equals(other.Start) && End.Equals(other.End);
        public override bool Equals(object obj) => obj is Range other && Equals(other);
        public override int GetHashCode() => Start.GetHashCode() * 397 ^ End.GetHashCode();
        public override string ToString() => $"{Start}..{End}";
    }
}
