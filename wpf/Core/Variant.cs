using System.Text;

namespace Gfp.Core;

public enum VKind { Nil = 0, Bool = 1, Int = 2, Float = 3, Str = 4, Array = 5, Dict = 6 }

/// Godot Variant。字典用有序列表实现（与 Rust 的 indexmap 保序一致）
public sealed class Variant
{
    public VKind Kind = VKind.Nil;
    public bool B;
    public long I;
    public double D;
    public string S = "";
    public List<Variant>? Arr;
    public List<KeyValuePair<Variant, Variant>>? Dic;

    public static Variant Nil() => new();
    public static Variant OfBool(bool v) => new() { Kind = VKind.Bool, B = v };
    public static Variant OfInt(long v) => new() { Kind = VKind.Int, I = v };
    public static Variant OfFloat(double v) => new() { Kind = VKind.Float, D = v };
    public static Variant OfStr(string v) => new() { Kind = VKind.Str, S = v };
    public static Variant OfArray(List<Variant> v) => new() { Kind = VKind.Array, Arr = v };
    public static Variant OfDict() => new() { Kind = VKind.Dict, Dic = new() };

    public Variant? Get(string key)
    {
        if (Kind != VKind.Dict || Dic is null) return null;
        foreach (var kv in Dic)
            if (kv.Key.Kind == VKind.Str && kv.Key.S == key) return kv.Value;
        return null;
    }

    public void Set(string key, Variant v)
    {
        if (Kind != VKind.Dict) { Kind = VKind.Dict; Dic = new(); }
        var d = Dic!;
        for (int i = 0; i < d.Count; i++)
            if (d[i].Key.Kind == VKind.Str && d[i].Key.S == key) { d[i] = new(OfStr(key), v); return; }
        d.Add(new(OfStr(key), v));
    }

    public List<Variant> AsArray() => Kind == VKind.Array && Arr is not null ? Arr : new();

    public string AsString() => Kind switch
    {
        VKind.Nil => "null",
        VKind.Bool => B ? "true" : "false",
        VKind.Int => I.ToString(),
        VKind.Float => Fmt(D),
        VKind.Str => S,
        _ => "",
    };

    /// 与 Python 版对齐：整数值且不太大时补一位小数
    public static string Fmt(double f)
        => (!double.IsNaN(f) && !double.IsInfinity(f)) && f == Math.Floor(f) && Math.Abs(f) < 1e16 ? f.ToString("F1") : f.ToString("R");
}
