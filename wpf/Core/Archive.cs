using System.IO.Compression;

namespace Gfp.Core;

public enum Kind { Zip, SevenZ, Rar }

public static class Archive
{
    public static Kind? KindOf(string path) => Path.GetExtension(path).ToLowerInvariant() switch
    {
        ".zip" => Kind.Zip,
        ".7z" => Kind.SevenZ,
        ".rar" => Kind.Rar,
        _ => null,
    };

    public static bool HasDat(string dir)
        => Directory.Exists(dir) && Directory.GetFiles(dir)
            .Any(f => string.Equals(Path.GetExtension(f), ".dat", StringComparison.OrdinalIgnoreCase));

    /// 备份：只打包目录下的一层文件
    public static void ZipDir(string dir, string outPath)
    {
        if (File.Exists(outPath)) File.Delete(outPath);
        using var zip = ZipFile.Open(outPath, ZipArchiveMode.Create);
        foreach (var f in Directory.GetFiles(dir))
            zip.CreateEntryFromFile(f, Path.GetFileName(f), CompressionLevel.Optimal);
    }

    public static void ZipExtractAll(string zipPath, string target)
    {
        Directory.CreateDirectory(target);
        // net48 的 ExtractToDirectory 无 overwrite 重载，先清空目标目录
        foreach (var f in Directory.GetFiles(target)) File.Delete(f);
        foreach (var d in Directory.GetDirectories(target)) Directory.Delete(d, true);
        ZipFile.ExtractToDirectory(zipPath, target);
    }

    private static string UniqueTemp()
        => Path.Combine(Path.GetTempPath(), $"gfp_{System.Diagnostics.Process.GetCurrentProcess().Id}_{DateTime.UtcNow.Ticks}");

    /// 解压到临时目录，返回路径（调用方负责删除）
    public static string ExtractAllToTemp(string src, Kind kind)
    {
        var baseDir = UniqueTemp();
        Directory.CreateDirectory(baseDir);
        try
        {
            switch (kind)
            {
                case Kind.Zip: ZipExtractAll(src, baseDir); break;
                // 7z / rar（RAR4 + RAR5）统一交给 7z.dll
                default: SevenZip.ExtractTo(src, baseDir); break;
            }
            return baseDir;
        }
        catch (Exception e)
        {
            try { Directory.Delete(baseDir, true); } catch { }
            throw new Exception($"解压失败：{e.Message}");
        }
    }

    /// 规范化 entry.Key（统一 '/'、去首 '/'；目录项返回 ""）
    private static string NormKey(string? key)
    {
        var rel = (key ?? "").Replace('\\', '/').TrimStart('/');
        return rel.EndsWith("/", StringComparison.Ordinal) ? "" : rel;
    }

    /// 按「包内顺序」列出压缩包内文件相对路径（导入前推导账号名/前缀用，与 PySide6 对齐）。
    /// zip 走 .NET 内置（ZipArchive.Entries 即包内顺序）；7z / rar 走 7z.dll。
    public static List<string> ListNames(string src)
    {
        if (KindOf(src) == Kind.Zip)
        {
            using var zip = ZipFile.OpenRead(src);
            var zipped = new List<string>();
            foreach (var entry in zip.Entries)
            {
                var k = NormKey(entry.FullName);
                if (k.Length > 0) zipped.Add(k);
            }
            return zipped;
        }
        return SevenZip.ListNames(src);
    }

    public static List<string> CollectFiles(string root)
    {
        var list = new List<string>();
        foreach (var f in Directory.GetFiles(root, "*", SearchOption.AllDirectories))
            list.Add(RelPath(root, f));
        return list;
    }

    /// 找首个 .dat：在根目录→账号名取压缩包名；在子目录→取该目录名，且只解压该目录内容
    public static (string? name, string prefix) ArchiveTarget(IEnumerable<string> names, string arcStem)
    {
        var dat = names.FirstOrDefault(n => n.EndsWith(".dat", StringComparison.OrdinalIgnoreCase));
        if (dat is null) return (null, "");
        int slash = dat.LastIndexOf('/');
        if (slash < 0) return (arcStem, "");
        var dir = dat[..slash];
        var name = dir.Contains("/") ? dir[(dir.LastIndexOf('/') + 1)..] : dir;
        return (name, dir + "/");
    }

    public static void CopyPrefix(string tmp, string target, string prefix)
    {
        foreach (var rel in CollectFiles(tmp))
        {
            if (prefix.Length > 0 && !rel.StartsWith(prefix, StringComparison.Ordinal)) continue;
            var rel2 = prefix.Length > 0 ? rel[prefix.Length..] : rel;
            if (rel2.Length == 0) continue;
            var dst = Path.Combine(target, rel2.Replace('/', Path.DirectorySeparatorChar));
            Directory.CreateDirectory(Path.GetDirectoryName(dst)!);
            File.Copy(Path.Combine(tmp, rel.Replace('/', Path.DirectorySeparatorChar)), dst, true);
        }
    }

    /// net48 无 Path.GetRelativePath，自实现（返回以 / 分隔的相对路径）
    private static string RelPath(string root, string path)
    {
        var sep = new[] { Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar };
        root = root.TrimEnd(sep) + Path.DirectorySeparatorChar;
        string rel = path.StartsWith(root, StringComparison.OrdinalIgnoreCase)
            ? path.Substring(root.Length)
            : path;
        return rel.Replace(Path.DirectorySeparatorChar, '/');
    }
}
