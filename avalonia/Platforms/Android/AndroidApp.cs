using Android.App;
using Android.Runtime;
using Avalonia.Android;

namespace Gfp.Mobile;

/// <summary>
/// ⚠ Avalonia 12 的 Android 入口模式：App 不是由 MainActivity 提供的，
/// 而是由这个带 [Application] 特性的类提供（继承泛型 AvaloniaAndroidApplication&lt;TApp&gt;）。
///
/// MainActivity 那边 AvaloniaMainActivity.InitializeAvaloniaView 里检查的是
/// 「Activity.Application is IAndroidApplication」—— 只有在清单里正确注册了这个类，
/// 该判断才成立，否则会抛：
///   System.InvalidOperationException: Unknown error: AvaloniaView initialization has failed.
///
/// ⚠ 只有 AvaloniaActivity / AvaloniaMainActivity 里没有 CustomizeAppBuilder 这类可重写方法，
/// 不要试图在 MainActivity 里 override 它们（CS0115）。
/// </summary>
[Application]
public class AndroidApp : AvaloniaAndroidApplication<App>
{
    public AndroidApp(IntPtr handle, JniHandleOwnership transfer) : base(handle, transfer)
    {
    }
}
