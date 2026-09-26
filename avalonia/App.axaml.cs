using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using Gfp.Core;

namespace Gfp.Mobile;

public partial class App : Application
{
    public override void Initialize()
    {
#if ANDROID
        // 游戏的 SAVE_ROOT 是 /storage/emulated/0/Documents/YierPai/saves（见 local_save_manager.gd），
        // 这里把工具的数据根指到它的父目录，于是 Save.SavesDir = .../Documents/YierPai/saves。
        // 必须在任何 Save.* 访问之前设置，Initialize() 是最早的时机。
        Save.DataDirOverride = "/storage/emulated/0/Documents/YierPai";
#endif
        Console.WriteLine("[GFP] App.Initialize()");
        FontProbe.Run();
        AvaloniaXamlLoader.Load(this);
    }

    public override void OnFrameworkInitializationCompleted()
    {
        Console.WriteLine($"[GFP] OnFrameworkInitializationCompleted, lifetime={ApplicationLifetime?.GetType().FullName ?? "null"}");

        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            desktop.MainWindow = new Window
            {
                Title = "功夫派怀旧服存档工具（移动版）",
                Width = 420,
                Height = 320,
                Content = new MainView(),
            };
            Console.WriteLine("[GFP] desktop window set");
        }
        else if (ApplicationLifetime is ISingleViewApplicationLifetime singleView)
        {
            try
            {
                singleView.MainView = new MainView();
                Console.WriteLine($"[GFP] MainView set, isNull={singleView.MainView is null}");
            }
            catch (Exception e)
            {
                Console.WriteLine("[GFP] MainView creation FAILED: " + e);
            }
        }
        else
        {
            Console.WriteLine("[GFP] unexpected lifetime type!");
        }

        base.OnFrameworkInitializationCompleted();
        Console.WriteLine("[GFP] OnFrameworkInitializationCompleted done");
    }
}
