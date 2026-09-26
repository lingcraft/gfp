namespace Gfp.Core;

public enum Disp { Ymd, YmdHm, YmdHms }

public readonly record struct Dt(int Y, int Mo, int D, int H, int Mi, int S)
{
    public static readonly Dt Min = new(0, 0, 0, 0, 0, 0);
    public string Render(Disp d) => d switch
    {
        Disp.Ymd => $"{Y:0000}-{Mo:00}-{D:00}",
        Disp.YmdHm => $"{Y:0000}-{Mo:00}-{D:00} {H:00}:{Mi:00}",
        _ => $"{Y:0000}-{Mo:00}-{D:00} {H:00}:{Mi:00}:{S:00}",
    };
    public bool Valid => Y >= 1000 && Mo >= 1 && Mo <= 12 && D >= 1 && D <= 31;
}

public sealed class BackupEntry
{
    public string Ver = "";
    public Dt? T;
    public string Path = "";
    public string Note = "";
    public Disp Disp = Disp.Ymd;
}

public static class Backup
{
    public static string Dir(string account) => System.IO.Path.Combine(Save.BackupsDir, account);

    /// 中国时区 UTC+8，无夏令时
    public static DateTime NowLocal() => DateTime.UtcNow.AddHours(8);

    public static string NowStamp()
    {
        var t = NowLocal();
        return $"{t.Year:0000}{t.Month:00}{t.Day:00}_{t.Hour:00}{t.Minute:00}{t.Second:00}";
    }

    public static Dt? DtFromStamp(string s)
    {
        if (s.Length < 15 || s[8] != '_') return null;
        int N(int i, int n) => int.TryParse(s.Substring(i, n), out var v) ? v : -1;
        var d = new Dt(N(0, 4), N(4, 2), N(6, 2), N(9, 2), N(11, 2), N(13, 2));
        return d.Valid && d.H < 24 && d.Mi < 60 && d.S < 60 ? d : null;
    }

    /// 版本号去 V 后按 . 拆整数；非纯数字回退 (0)
    private static long[] VersionKey(string ver)
    {
        var s = ver.TrimStart('V', 'v');
        if (s.Length == 0) return new long[] { 0 };
        var parts = s.Split('.');
        var r = new long[parts.Length];
        for (int i = 0; i < parts.Length; i++)
            if (!long.TryParse(parts[i], out r[i])) return new long[] { 0 };
        return r;
    }

    private static int CmpDt(Dt a, Dt b)
    {
        int c;
        if ((c = a.Y.CompareTo(b.Y)) != 0) return c;
        if ((c = a.Mo.CompareTo(b.Mo)) != 0) return c;
        if ((c = a.D.CompareTo(b.D)) != 0) return c;
        if ((c = a.H.CompareTo(b.H)) != 0) return c;
        if ((c = a.Mi.CompareTo(b.Mi)) != 0) return c;
        return a.S.CompareTo(b.S);
    }

    private static int CmpKey(long[] a, long[] b)
    {
        int n = Math.Min(a.Length, b.Length);
        for (int i = 0; i < n; i++)
            if (a[i] != b[i]) return a[i] < b[i] ? -1 : 1;
        return a.Length.CompareTo(b.Length);
    }

    public static List<BackupEntry> List(string account)
    {
        var list = new List<BackupEntry>();
        var dir = Dir(account);
        if (!Directory.Exists(dir)) return list;
        foreach (var f in Directory.GetFiles(dir))
        {
            if (!string.Equals(Path.GetExtension(f), ".zip", StringComparison.OrdinalIgnoreCase)) continue;
            var stem = Path.GetFileNameWithoutExtension(f);
            var (ver, t, note, disp) = ParseName(stem);
            list.Add(new BackupEntry { Ver = ver, T = t, Path = f, Note = note, Disp = disp });
        }
        list.Sort((a, b) =>
        {
            int c = CmpKey(VersionKey(b.Ver), VersionKey(a.Ver)); // 版本号降序
            if (c != 0) return c;
            return CmpDt(b.T ?? Dt.Min, a.T ?? Dt.Min); // 时间降序
        });
        return list;
    }

    public static string Fmt(BackupEntry e)
    {
        if (e.T is null) return string.IsNullOrEmpty(e.Note) ? Path.GetFileNameWithoutExtension(e.Path) : e.Note;
        // ⚠ 没有版本号时（手机版存档无 save_version）不要留出多余的前导空格
        var b = string.IsNullOrEmpty(e.Ver)
            ? e.T.Value.Render(e.Disp)
            : $"{e.Ver} {e.T.Value.Render(e.Disp)}";
        return string.IsNullOrEmpty(e.Note) ? b : $"{b} {e.Note}";
    }

    /// <summary>
    /// 备份文件名解析，两种格式都认（sep 为 _ 或空格）：
    ///   ① 版本{sep}日期[{sep}时间][{sep}注释]  —— 电脑版（存档有 save_version）
    ///   ② 日期[{sep}时间][{sep}注释]           —— 手机版（存档无 save_version，故不带版本前缀）
    ///
    /// ⚠ 为什么必须认第 ② 种：旧实现固定把"第一个分隔符前的部分"当版本号，
    ///   遇到「20260926_091714」会把日期 20260926 当成版本号，
    ///   结果 T 解析成 null ⇒ 排序退化成按字符串比，同日多份备份顺序不定。
    /// </summary>
    public static (string ver, Dt? t, string note, Disp disp) ParseName(string stem)
    {
        string AsNote(string s) => s.Replace('_', ' ').Trim();

        // ★ 优先试新格式（无版本号）：整个 stem 以 yyyyMMdd 开头。
        //   可以安全优先匹配 —— 旧格式第一段是版本号（形如 V1.0.2 或纯数字版本），
        //   不可能正好是"8 位纯数字且紧跟分隔符"的年月日。
        var (usedHead, dtHead) = MatchDate(stem);
        if (dtHead is not null && usedHead == 8)
        {
            var rest0 = stem[usedHead..].TrimStart('_', ' ');
            var (usedT0, time0) = MatchTime(rest0);
            if (time0 is null) return ("", dtHead, AsNote(rest0), Disp.Ymd);

            var d0 = dtHead.Value with { H = time0.Value.H, Mi = time0.Value.Mi, S = time0.Value.S };
            var note0 = rest0[usedT0..].TrimStart('_', ' ');
            return ("", d0, AsNote(note0), time0.Value.S == 0 && usedT0 <= 5 ? Disp.YmdHm : Disp.YmdHms);
        }

        // 旧格式：先切出版本号
        int i = 0;
        while (i < stem.Length && stem[i] != '_' && !char.IsWhiteSpace(stem[i])) i++;
        string ver = stem[..i];
        string rest = i < stem.Length ? stem[(i + 1)..] : "";
        rest = rest.TrimStart('_', ' ');

        var (used, dt) = MatchDate(rest);
        if (dt is null) return ("", null, AsNote(stem), Disp.Ymd);
        rest = rest[used..].TrimStart('_', ' ');

        var (usedT, time) = MatchTime(rest);
        if (time is null) return (ver, dt, AsNote(rest), Disp.Ymd);
        rest = rest[usedT..].TrimStart('_', ' ');
        var d = dt.Value with { H = time.Value.H, Mi = time.Value.Mi, S = time.Value.S };
        return (ver, d, AsNote(rest), time.Value.S == 0 && usedT <= 5 ? Disp.YmdHm : Disp.YmdHms);
    }

    private static (int, Dt?) MatchDate(string s)
    {
        // kind 0: YYYYMMDD；1/2/3: 分隔符 - / .
        if (s.Length >= 8 && s[..8].All(char.IsDigit))
        {
            var d = new Dt(int.Parse(s[..4]), int.Parse(s[4..6]), int.Parse(s[6..8]), 0, 0, 0);
            return d.Valid ? (8, d) : (8, null);
        }
        foreach (char sep in new[] { '-', '/', '.' })
        {
            if (s.Length < 10 || s[4] != sep || s[7] != sep) continue;
            if (!(s[..4].All(char.IsDigit) && s[5..7].All(char.IsDigit) && s[8..10].All(char.IsDigit))) continue;
            var d = new Dt(int.Parse(s[..4]), int.Parse(s[5..7]), int.Parse(s[8..10]), 0, 0, 0);
            if (d.Valid) return (10, d);
        }
        return (0, null);
    }

    private static (int, (int H, int Mi, int S)?) MatchTime(string s)
    {
        bool Dig(string x) => x.Length > 0 && x.All(char.IsDigit);
        if (s.Length >= 8 && s[2] == ':' && s[5] == ':' && Dig(s[..2]) && Dig(s[3..5]) && Dig(s[6..8]))
        {
            var t = (int.Parse(s[..2]), int.Parse(s[3..5]), int.Parse(s[6..8]));
            return ValidTime(t) ? (8, t) : (8, null);
        }
        if (s.Length >= 6 && Dig(s[..6]))
        {
            var t = (int.Parse(s[..2]), int.Parse(s[2..4]), int.Parse(s[4..6]));
            if (ValidTime(t)) return (6, t);
        }
        if (s.Length >= 5 && s[2] == ':' && Dig(s[..2]) && Dig(s[3..5]))
        {
            var t = (int.Parse(s[..2]), int.Parse(s[3..5]), 0);
            if (ValidTime(t)) return (5, t);
        }
        if (s.Length >= 4 && Dig(s[..4]))
        {
            var t = (int.Parse(s[..2]), int.Parse(s[2..4]), 0);
            if (ValidTime(t)) return (4, t);
        }
        return (0, null);
    }

    private static bool ValidTime((int H, int Mi, int S) t) => t.H < 24 && t.Mi < 60 && t.S < 60;
}
