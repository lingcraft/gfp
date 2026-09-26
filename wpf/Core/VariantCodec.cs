using System.Text;

namespace Gfp.Core;

public sealed class VReader
{
    private readonly byte[] _b;
    private int _p;
    public VReader(byte[] b) { _b = b; }

    public byte[] Take(int n)
    {
        if (_p + n > _b.Length) throw new Exception("Variant 流不完整（数据被截断）。");
        var r = new byte[n];
        Array.Copy(_b, _p, r, 0, n);
        _p += n;
        return r;
    }
    public uint U32() => BitConverter.ToUInt32(Take(4), 0);
    public int I32() => (int)U32();
    public long I64() => (long)BitConverter.ToUInt64(Take(8), 0);
    public float F32() => BitConverter.ToSingle(Take(4), 0);
    public double F64() => BitConverter.ToDouble(Take(8), 0);

    public string Str()
    {
        int n = (int)U32();
        var s = Encoding.UTF8.GetString(Take(n));
        int pad = (4 - n % 4) % 4;
        if (pad > 0) Take(pad);
        return s;
    }

    private void ContainerType(uint kind)
    {
        if (kind == 1) U32();
        else if (kind == 2 || kind == 3) Str();
        else if (kind != 0) throw new Exception("非法的容器类型。");
    }

    public Variant Value(int depth)
    {
        if (depth > 1024) throw new Exception("Variant 嵌套过深。");
        uint h = U32();
        int t = (int)(h & 0xFF);
        bool is64 = (h & (1 << 16)) != 0;
        switch (t)
        {
            case 0: return Variant.Nil();
            case 1: return Variant.OfBool(U32() != 0);
            case 2: return Variant.OfInt(is64 ? I64() : I32());
            case 3: return Variant.OfFloat(is64 ? F64() : F32());
            case 4:
            case 21: return Variant.OfStr(Str());
            case 27:
                {
                    ContainerType((h >> 16) & 3);
                    ContainerType((h >> 18) & 3);
                    int n = (int)(U32() & 0x7FFFFFFF);
                    var d = Variant.OfDict();
                    for (int i = 0; i < n; i++) d.Dic!.Add(new(Value(depth + 1), Value(depth + 1)));
                    return d;
                }
            case 28:
                {
                    ContainerType((h >> 16) & 3);
                    int n = (int)(U32() & 0x7FFFFFFF);
                    var a = new List<Variant>(n);
                    for (int i = 0; i < n; i++) a.Add(Value(depth + 1));
                    return Variant.OfArray(a);
                }
            case 29:
                {
                    int n = (int)U32();
                    var a = new List<Variant>(n);
                    foreach (var b in Take(n)) a.Add(Variant.OfInt(b));
                    int pad = (4 - n % 4) % 4;
                    if (pad > 0) Take(pad);
                    return Variant.OfArray(a);
                }
            case 30:
                {
                    int n = (int)U32();
                    var a = new List<Variant>(n);
                    for (int i = 0; i < n; i++) a.Add(Variant.OfInt((int)U32()));
                    return Variant.OfArray(a);
                }
            case 31:
                {
                    int n = (int)U32();
                    var a = new List<Variant>(n);
                    for (int i = 0; i < n; i++) a.Add(Variant.OfInt(I64()));
                    return Variant.OfArray(a);
                }
            case 32:
            case 33:
                {
                    bool d64 = t == 33;
                    int n = (int)U32();
                    var a = new List<Variant>(n);
                    for (int i = 0; i < n; i++) a.Add(Variant.OfFloat(d64 ? F64() : F32()));
                    return Variant.OfArray(a);
                }
            case 34:
                {
                    int n = (int)U32();
                    var a = new List<Variant>(n);
                    for (int i = 0; i < n; i++) a.Add(Variant.OfStr(Str()));
                    return Variant.OfArray(a);
                }
            case 23: return Variant.OfInt(I64());
            case 24:
                {
                    if ((h & (1 << 16)) != 0)
                    {
                        long id = I64();
                        if (id == 0) return Variant.Nil();
                        var d = Variant.OfDict();
                        d.Set("__object_id", Variant.OfInt(id));
                        return d;
                    }
                    throw new Exception("完整对象编码在不允许对象的环境中不受支持。");
                }
            case 25: return Variant.Nil(); // 与原实现一致：不消费字节
            case 26:
                {
                    var name = Str();
                    var id = I64();
                    var d = Variant.OfDict();
                    d.Set("__signal", Variant.OfStr(name));
                    d.Set("__object_id", Variant.OfInt(id));
                    return d;
                }
            default:
                {
                    // 数学类型（向量/矩形/矩阵/颜色等）：按分量个数读 float（COLOR 固定 f32）
                    int comp = t switch
                    {
                        5 or 6 or 35 => 2,
                        9 or 10 or 36 => 3,
                        7 or 8 or 12 or 13 or 14 or 15 or 20 or 37 or 38 => 4,
                        11 or 16 => 6,
                        17 => 9,
                        18 => 12,
                        19 => 16,
                        _ => 0,
                    };
                    if (comp == 0) throw new Exception($"不支持的 Variant 类型：{t}");
                    bool d64 = (t != 20 && t != 37) && is64;
                    var a = new List<Variant>(comp);
                    for (int i = 0; i < comp; i++) a.Add(Variant.OfFloat(d64 ? F64() : F32()));
                    return Variant.OfArray(a);
                }
        }
    }
}

public sealed class VWriter
{
    private readonly List<byte> _o = new();
    public byte[] Bytes => _o.ToArray();
    public void U32(uint v) => _o.AddRange(BitConverter.GetBytes(v));
    public void U64(ulong v) => _o.AddRange(BitConverter.GetBytes(v));
    public void F32(float v) => _o.AddRange(BitConverter.GetBytes(v));
    public void F64(double v) => _o.AddRange(BitConverter.GetBytes(v));

    public void Str(string s)
    {
        var b = Encoding.UTF8.GetBytes(s);
        U32((uint)b.Length);
        _o.AddRange(b);
        int pad = (4 - b.Length % 4) % 4;
        for (int i = 0; i < pad; i++) _o.Add(0);
    }

    public void Value(Variant v)
    {
        switch (v.Kind)
        {
            case VKind.Nil: U32(0); break;
            case VKind.Bool: U32(1); U32(v.B ? 1u : 0u); break;
            case VKind.Int:
                {
                    bool big = v.I < int.MinValue || v.I > int.MaxValue;
                    U32(2 | (big ? 1u << 16 : 0));
                    if (big) U64((ulong)v.I); else U32((uint)(int)v.I);
                    break;
                }
            case VKind.Float:
                {
                    float f = (float)v.D;
                    bool big = (double)f != v.D;
                    U32(3 | (big ? 1u << 16 : 0));
                    if (big) F64(v.D); else F32(f);
                    break;
                }
            case VKind.Str: U32(4); Str(v.S); break;
            case VKind.Array:
                {
                    var a = v.Arr ?? new();
                    U32(28); U32((uint)a.Count);
                    foreach (var e in a) Value(e);
                    break;
                }
            case VKind.Dict:
                {
                    var d = v.Dic ?? new();
                    U32(27); U32((uint)d.Count);
                    foreach (var kv in d) { U32(4); Str(kv.Key.S); Value(kv.Value); }
                    break;
                }
        }
    }
}

public static class Envelope
{
    /// 存储流 = [u32 长度][Variant 字节]
    public static byte[] ToRawStream(Variant v)
    {
        var w = new VWriter();
        w.Value(v);
        var body = w.Bytes;
        var outb = new byte[4 + body.Length];
        BitConverter.GetBytes((uint)body.Length).CopyTo(outb, 0);
        body.CopyTo(outb, 4);
        return outb;
    }

    public static Variant FromRawStream(byte[] raw)
    {
        var r = new VReader(raw);
        int n = (int)r.U32();
        var body = r.Take(n);
        return new VReader(body).Value(0);
    }
}
