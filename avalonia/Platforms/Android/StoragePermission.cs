using Android.App;
using Android.Content;
using Android.Provider;

namespace Gfp.Mobile;

/// <summary>
/// 「所有文件访问权限」（MANAGE_EXTERNAL_STORAGE）的检测与引导。
///
/// ⚠ 这个权限与普通运行时权限不同：**系统不会弹窗**，只能由用户到系统设置页手动打开，
///   所以 App 必须自己给出入口，否则用户只会看到"读不到存档"而不知所措。
/// ⚠ 只在 Android 目标编译；调用处必须用 #if ANDROID 包起来。
/// </summary>
internal static class StoragePermission
{
    private static Activity? _activity;

    /// <summary>Activity 恢复前台时触发（典型场景：用户刚从这个权限的设置页返回）。</summary>
    internal static event Action? Resumed;

    internal static void Attach(Activity activity) => _activity = activity;

    internal static void Detach(Activity activity)
    {
        if (ReferenceEquals(_activity, activity)) _activity = null;
    }

    internal static void NotifyResumed()
    {
        if (_activity is null) return;
        Resumed?.Invoke();
    }

    /// <summary>是否已获得「所有文件访问权限」。Android 11 以下没有该概念，公共目录直接可写，视为已授权。</summary>
    internal static bool IsGranted()
    {
        if (!OperatingSystem.IsAndroidVersionAtLeast(30)) return true;
#pragma warning disable CA1416 // 上面已做版本判断
        return Android.OS.Environment.IsExternalStorageManager;
#pragma warning restore CA1416
    }

    /// <summary>跳到本 App 的「所有文件访问权限」设置页。</summary>
    internal static void OpenSettings()
    {
        var act = _activity;
        if (act is null)
        {
            Console.WriteLine("[GFP-PERM] 无法跳转设置：Activity 引用为空");
            return;
        }

#pragma warning disable CA1416 // 这两个 action 字符串在低版本上只是打不开，不会崩
        try
        {
            // 优先跳"本应用"的授权页（带 package: 数据）
            var intent = new Intent(Settings.ActionManageAppAllFilesAccessPermission);
            intent.SetData(Android.Net.Uri.Parse("package:" + act.PackageName));
            act.StartActivity(intent);
            Console.WriteLine("[GFP-PERM] 已跳转到应用专属授权页");
            return;
        }
        catch (Exception e)
        {
            Console.WriteLine("[GFP-PERM] 应用专属授权页打不开，改用全部应用列表: " + e.Message);
        }

        try
        {
            act.StartActivity(new Intent(Settings.ActionManageAllFilesAccessPermission));
            Console.WriteLine("[GFP-PERM] 已跳转到「所有文件访问」总列表");
        }
        catch (Exception e)
        {
            Console.WriteLine("[GFP-PERM] 跳转设置失败: " + e.Message);
        }
#pragma warning restore CA1416
    }
}
