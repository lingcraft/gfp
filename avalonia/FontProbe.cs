namespace Gfp.Mobile;

/// <summary>
/// 字体诊断：列出 Android 系统里 Skia 能看到的字体族名，并检查 sans-serif 到底解析到了什么、
/// 是否含中文字形（用 "你" U+4F60 试）。用来定位"中文显示成豆腐块"。
/// 仅在 Android 目标下编译。
/// </summary>
internal static class FontProbe
{
    public static void Run()
    {
#if ANDROID
        try
        {
            var fm = SkiaSharp.SKFontManager.Default;
            var names = fm.FontFamilies?.ToList();
            Console.WriteLine($"[GFP-FONT] 系统字体族总数 = {names?.Count ?? -1}");

            if (names is not null)
            {
                foreach (var n in names)
                {
                    if (n.Contains("CJK", StringComparison.OrdinalIgnoreCase)
                        || n.Contains("Han", StringComparison.OrdinalIgnoreCase)
                        || n.Contains("Noto Sans", StringComparison.OrdinalIgnoreCase)
                        || n.Contains("sans", StringComparison.OrdinalIgnoreCase))
                    {
                        Console.WriteLine($"[GFP-FONT] family: {n}");
                    }
                }
            }

            foreach (var tryName in new[] { "sans-serif", "Noto Sans CJK SC", "Noto Sans CJK JP", "Noto Sans SC", "Noto Sans" })
            {
                var tf = fm.MatchFamily(tryName);
                if (tf is null)
                {
                    Console.WriteLine($"[GFP-FONT] MatchFamily('{tryName}') -> null");
                    continue;
                }
                var g = tf.GetGlyph(0x4F60); // "你"
                Console.WriteLine($"[GFP-FONT] MatchFamily('{tryName}') -> FamilyName='{tf.FamilyName}', '你' 的字形 id={g}");
            }
        }
        catch (Exception e)
        {
            Console.WriteLine("[GFP-FONT] probe failed: " + e);
        }
#endif
    }
}
