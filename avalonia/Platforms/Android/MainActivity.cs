using Android.App;
using Android.Content.PM;
using Android.OS;
using Avalonia.Android;

namespace Gfp.Mobile;

/// <summary>
/// ⚠ Avalonia 12：MainActivity 保持空类即可，App 由同目录的 AndroidApp
/// （[Application] + AvaloniaAndroidApplication&lt;App&gt;）提供。
/// 不要再试图重写 CustomizeAppBuilder / CreateAppBuilder —— 这两个基类里都没有（CS0115）。
///
/// 这里只挂三处生命周期回调，服务于「所有文件访问权限」的检测与引导。
/// </summary>
[Activity(
    Label = "存档工具",
    Icon = "@mipmap/ic_launcher",
    // ⚠ AvaloniaActivity 继承自 AppCompatActivity，主题必须是 Theme.AppCompat 系，
    //   用 @android:style/Theme.Material.* 会在 set_Content 时抛：
    //   IllegalStateException: You need to use a Theme.AppCompat theme (or descendant) with this activity.
    Theme = "@style/Theme.AppCompat.Light.NoActionBar",
    MainLauncher = true,
    ConfigurationChanges = ConfigChanges.Orientation
                         | ConfigChanges.ScreenSize
                         | ConfigChanges.ScreenLayout
                         | ConfigChanges.KeyboardHidden
                         | ConfigChanges.UiMode)]
public class MainActivity : AvaloniaMainActivity
{
    protected override void OnCreate(Bundle? savedInstanceState)
    {
        base.OnCreate(savedInstanceState);
        StoragePermission.Attach(this);
    }

    protected override void OnResume()
    {
        base.OnResume();   // ⚠ 基类在这里维护 AndroidActivatableLifetime，必须调
        // 用户可能刚从系统设置页返回 —— 重新检测权限状态
        StoragePermission.Attach(this);
        StoragePermission.NotifyResumed();
    }

    protected override void OnDestroy()
    {
        StoragePermission.Detach(this);
        base.OnDestroy();
    }
}
