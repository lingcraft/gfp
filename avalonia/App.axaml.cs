using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using Avalonia.Platform;
using Gfp.Core;

namespace Gfp.Mobile;

public partial class App : Application
{
    public override void Initialize()
    {
#if ANDROID
        // 游戏 SAVE_ROOT = /storage/emulated/0/YierPai/saves（= /sdcard/YierPai/saves）
        // 这里指向其父目录，于是 Save.SavesDir = /storage/emulated/0/YierPai/saves。
        // 必须在任何 Save.* 访问之前设置，Initialize() 是最早的时机。
        // ⚠ 共享存储根下的目录，跨应用读写必须 MANAGE_EXTERNAL_STORAGE
        //   （界面上的"所有文件访问权限"引导区就是干这个的）。
        Save.DataDirOverride = "/storage/emulated/0/YierPai";
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
                Title = "存档工具",
                // ⚠ 任务栏/标题栏图标必须在 Window.Icon 上显式给，ApplicationIcon（csproj）
                //   只管 exe 文件本身的图标；不设的话窗口显示 Avalonia 默认图标。
                //   icon.ico 以 AvaloniaResource 嵌入（见 csproj），从 avares:// 流构造。
                Icon = new WindowIcon(AssetLoader.Open(new Uri("avares://gfp-mobile/icon.ico"))),
                // 桌面只用来本地调试；尺寸按手机竖屏比例给，方便一眼看到完整布局
                Width = 420,
                Height = 680,
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
