using System.Runtime.InteropServices;
using System.Text;

namespace Gfp.Core;

public enum HotKey { Backup, Restore, Delete }

public static class Win
{
    private const int MOD_NOREPEAT = 0x4000;
    private const int WM_HOTKEY = 0x0312;
    private const int SM_CXSCREEN = 0, SM_CYSCREEN = 1;
    private const uint SWP_NOACTIVATE = 0x0010;
    private static readonly IntPtr HWND_TOPMOST = new(-1);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool RegisterHotKey(IntPtr hWnd, int id, uint fsModifiers, uint vk);
    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumCb cb, IntPtr lParam);
    private delegate bool EnumCb(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")]
    private static extern bool IsIconic(IntPtr hWnd);
    [DllImport("user32.dll")]
    private static extern int GetWindowTextLengthW(IntPtr hWnd);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetWindowTextW(IntPtr hWnd, StringBuilder s, int n);
    [DllImport("user32.dll")]
    private static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr FindWindowW(string? cls, string? title);
    [DllImport("user32.dll")]
    private static extern bool SetWindowPos(IntPtr hWnd, IntPtr after, int x, int y, int cx, int cy, uint flags);
    [DllImport("user32.dll")]
    private static extern int GetSystemMetrics(int n);

    [StructLayout(LayoutKind.Sequential)]
    private struct RECT { public int Left, Top, Right, Bottom; }

    [StructLayout(LayoutKind.Sequential)]
    private struct MSG
    {
        public IntPtr hwnd; public uint message; public IntPtr wParam; public IntPtr lParam;
        public uint time; public POINT pt;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct POINT { public int X, Y; }

    [DllImport("user32.dll")]
    private static extern int GetMessageW(out MSG msg, IntPtr hWnd, uint min, uint max);

    public static event Action<HotKey>? Hotkey;

    /// 后台线程注册 F7/F8/F9（hwnd=NULL，走线程消息队列）
    public static void StartHotkeys()
    {
        var t = new Thread(() =>
        {
            RegisterHotKey(IntPtr.Zero, 1, MOD_NOREPEAT, 0x76); // F7 备份
            RegisterHotKey(IntPtr.Zero, 2, MOD_NOREPEAT, 0x77); // F8 恢复
            RegisterHotKey(IntPtr.Zero, 3, MOD_NOREPEAT, 0x78); // F9 删除
            while (GetMessageW(out var msg, IntPtr.Zero, 0, 0) > 0)
            {
                if (msg.message != WM_HOTKEY) continue;
                var k = msg.wParam.ToInt32() switch { 1 => HotKey.Backup, 2 => HotKey.Restore, _ => HotKey.Delete };
                Hotkey?.Invoke(k);
            }
        }) { IsBackground = true };
        t.Start();
    }

    /// 找标题含关键字的可见窗口中心；找不到或最小化则回退屏幕中心
    public static (int cx, int cy) Center(string keyword)
    {
        IntPtr found = IntPtr.Zero;
        EnumWindows((h, _) =>
        {
            if (!IsWindowVisible(h) || IsIconic(h)) return true;
            int n = GetWindowTextLengthW(h);
            if (n <= 0) return true;
            var sb = new StringBuilder(n + 1);
            GetWindowTextW(h, sb, sb.Capacity);
            if (sb.ToString().ToLowerInvariant().Contains(keyword.ToLowerInvariant()))
            {
                found = h;
                return false;
            }
            return true;
        }, IntPtr.Zero);

        if (found != IntPtr.Zero && GetWindowRect(found, out var r) && r.Right > r.Left && r.Bottom > r.Top)
            return ((r.Left + r.Right) / 2, (r.Top + r.Bottom) / 2);

        return (GetSystemMetrics(SM_CXSCREEN) / 2, GetSystemMetrics(SM_CYSCREEN) / 2);
    }

    public static IntPtr FindByTitle(string title) => FindWindowW(null, title);

    public static void PlaceTopmost(IntPtr hWnd, int x, int y, int w, int h)
        => SetWindowPos(hWnd, HWND_TOPMOST, x, y, w, h, SWP_NOACTIVATE);
}
