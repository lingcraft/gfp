using Avalonia;

namespace Gfp.Mobile;

internal static class Program
{
    // 桌面入口用；Android 侧由 MainActivity 驱动，不走 Main。
    // 注意 UsePlatformDetect() 来自 Avalonia.Desktop，Android 目标不引用该包，故用条件编译。
    // ⚠ 不调用 .WithInterFont() —— Inter 不含 CJK 字形，会让中文变成豆腐块；字体统一在 App.axaml 里指定。
    public static AppBuilder BuildAvaloniaApp()
        => AppBuilder.Configure<App>()
#if !ANDROID
            .UsePlatformDetect()
#endif
            .LogToTrace();

#if !ANDROID
    [System.STAThread]
    public static void Main(string[] args)
    {
        // --probe：命令行自检，不起 UI，直接把存档读一遍打出来。
        if (System.Array.IndexOf(args, "--probe") >= 0)
        {
            Probe.Run();
            return;
        }

        // --demo：命令行端到端自测，跑「减负/备份/恢复/导出/导入/删备份」全流程。
        // ⚠ 只操作真实存档的临时副本，跑完自动删除。
        if (System.Array.IndexOf(args, "--demo") >= 0)
        {
            Demo.Run();
            return;
        }

        BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);
    }
#endif
}
