using Gfp.Core;

namespace Gfp.Mobile;

/// <summary>
/// 命令行自检（--probe）：不启动 UI，直接验证复用来的 Core 能否读出真实存档。
/// 结果同时写 stdout 和 exe 目录下的 probe.log —— WinExe 子系统的 stdout
/// 在部分环境下抓不到，写文件更保险。
/// </summary>
internal static class Probe
{
    public static void Run()
    {
        var sb = new StringBuilder();
        void Line(string s) => sb.AppendLine(s);

        Line("=== gfp-mobile 自检 ===");
        Line($"存档根目录: {Save.SavesDir}");

        var profiles = Save.ListProfiles();
        Line($"账号数: {profiles.Count}");

        foreach (var p in profiles)
        {
            Line($"--- {p.Name}（encryption_id={p.EncryptionId()}）---");
            try
            {
                var (payload, ver) = Save.LoadPayload(p);
                var chars = Relief.Chars(payload);
                Line($"  版本={ver}  有效角色={chars.Count}");
                foreach (var c in chars) Line($"    {Relief.Display(c)}");
            }
            catch (Exception e)
            {
                Line($"  读取失败: {e.Message}");
            }
        }

        var text = sb.ToString();
        Console.Write(text);

        try
        {
            File.WriteAllText(
                Path.Combine(AppContext.BaseDirectory, "probe.log"),
                text,
                new UTF8Encoding(false));
        }
        catch
        {
            // 写不进去也不影响，stdout 那份还在
        }
    }
}
