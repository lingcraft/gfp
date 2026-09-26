using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using SevenZipExtractor;

namespace Gfp.Core;

/// <summary>
/// 7z.dll（7-Zip 官方引擎）的封装：列出 / 解压 7z、rar（RAR4 / RAR5）、zip 等
/// 7-Zip 支持的全部格式，P/Invoke 层由 NuGet `SevenZipExtractor` 提供。
///
/// 7z.dll（x64）以 gzip 压缩后作为嵌入资源（逻辑名 gfp.sevenzip.gz）随 exe 分发，
/// 首次使用时解压到 %LOCALAPPDATA%\gfp\7z_{资源长度}\7z.dll 再交给 SevenZipExtractor。
///
/// 重新生成嵌入资源（更换 7-Zip 版本时）：把新的 7z.dll（x64）gzip 后覆盖 wpf/7z.dll.gz。
/// </summary>
public static class SevenZip
{
    private const string ResourceName = "gfp.sevenzip.gz";
    private static readonly object Gate = new object();
    private static string? _libraryPath;

    /// <summary>内嵌 7z.dll 的本地路径（首次访问时释放）。</summary>
    public static string LibraryPath
    {
        get
        {
            if (_libraryPath != null) return _libraryPath;
            lock (Gate)
            {
                if (_libraryPath != null) return _libraryPath;

                var baseDir = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "gfp");
                Directory.CreateDirectory(baseDir);

                using var res = typeof(SevenZip).Assembly.GetManifestResourceStream(ResourceName)
                                ?? throw new Exception("缺少内嵌资源 " + ResourceName);

                // 目录名带资源长度：换 7-Zip 版本时自动换目录，避免复用旧 dll
                var dir = Path.Combine(baseDir, "7z_" + res.Length);
                Directory.CreateDirectory(dir);
                var dll = Path.Combine(dir, "7z.dll");

                if (!File.Exists(dll) || new FileInfo(dll).Length == 0)
                {
                    var tmp = dll + ".tmp";
                    using (var gz = new GZipStream(res, CompressionMode.Decompress))
                    using (var dst = File.Create(tmp)) { gz.CopyTo(dst); }
                    try { File.Move(tmp, dll); }
                    catch (IOException) { if (File.Exists(tmp)) File.Delete(tmp); }
                }

                _libraryPath = dll;
            }
            return _libraryPath;
        }
    }

    /// <summary>按「包内顺序」列出非目录项的相对路径（统一 '/' 分隔）。</summary>
    public static List<string> ListNames(string path)
    {
        using var archive = new ArchiveFile(path, LibraryPath);
        var list = new List<string>();
        foreach (var entry in archive.Entries)
        {
            if (entry.IsFolder) continue;
            var name = Norm(entry.FileName);
            if (name.Length > 0) list.Add(name);
        }
        return list;
    }

    /// <summary>把压缩包全部内容解压到 target 目录（自动建子目录）。</summary>
    public static void ExtractTo(string path, string target)
    {
        Directory.CreateDirectory(target);
        using var archive = new ArchiveFile(path, LibraryPath);
        archive.Extract(target);
    }

    /// <summary>规范化路径：统一 '/'、去首 '/'、去尾 '/'。</summary>
    private static string Norm(string? key)
    {
        var rel = (key ?? string.Empty).Replace('\\', '/').TrimStart('/');
        return rel.TrimEnd('/');
    }
}
