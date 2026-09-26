using System.Collections.Generic;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using Gfp.Core;

namespace Gfp;

public sealed partial class MainWindow : Window
{
    private List<Profile> _profiles = new();
    private Profile? _cur;
    private Variant _payload = Variant.Nil();
    private string _version = "V0.0.0";
    private List<CharInfo> _chars = new();
    private List<BackupEntry> _backups = new();
    private SelectionChangedEventHandler? _accHandler;

    public MainWindow()
    {
        InitializeComponent();
        InitLogic();
    }

    // 标题栏按钮对齐 PySide6：用 ResizeMode=CanMinimize ——
    // 窗口不可拉伸，系统自动给出「最小化 + 最大化(禁用灰) + 关闭」三个按钮
    //（NoResize 会把最小化和最大化一起去掉，只剩关闭）。
    protected override void OnSourceInitialized(EventArgs e)
    {
        base.OnSourceInitialized(e);

        var hwnd = new System.Windows.Interop.WindowInteropHelper(this).Handle;

        // 双保险：双击标题栏 / 系统菜单里的「最大化」「大小」也禁掉
        System.Windows.Interop.HwndSource.FromHwnd(hwnd)?.AddHook(SysCmdHook);

        var menu = GetSystemMenu(hwnd, false);
        if (menu != IntPtr.Zero)
        {
            EnableMenuItem(menu, SC_MAXIMIZE, MF_BYCOMMAND | MF_GRAYED);
            EnableMenuItem(menu, SC_SIZE, MF_BYCOMMAND | MF_GRAYED);
        }
    }

    private static IntPtr SysCmdHook(IntPtr hwnd, int msg, IntPtr wParam, IntPtr lParam,
        ref bool handled)
    {
        const int WM_SYSCOMMAND = 0x0112;
        const long SC_MAXIMIZE = 0xF030;
        if (msg == WM_SYSCOMMAND && (wParam.ToInt64() & 0xFFF0) == SC_MAXIMIZE)
        {
            handled = true;   // 吞掉「最大化」命令，窗口不会有任何反应
            return IntPtr.Zero;
        }
        return IntPtr.Zero;
    }

    [System.Runtime.InteropServices.DllImport("user32.dll")]
    private static extern IntPtr GetSystemMenu(IntPtr hWnd, bool bRevert);

    [System.Runtime.InteropServices.DllImport("user32.dll")]
    private static extern uint EnableMenuItem(IntPtr hMenu, uint uIDEnableItem, uint uEnable);

    private const uint MF_BYCOMMAND = 0x00000000;
    private const uint MF_GRAYED = 0x00000001;
    private const uint SC_SIZE = 0xF000;
    private const uint SC_MAXIMIZE = 0xF030;

    private void InitLogic()
    {
        Win.Hotkey += k => Dispatcher.Invoke(() =>
        {
            if (k == HotKey.Backup) DoBackup();
            else if (k == HotKey.Restore) DoRestore();
            else DoDelete();
        });
        Win.StartHotkeys();

        _accHandler = (_, _) => LoadAccount();
        _acc.SelectionChanged += _accHandler;
        _relief.Click += (_, _) => DoRelief();
        _export.Click += (_, _) => DoExport();
        _import.Click += (_, _) => DoImport();
        _backup.Click += (_, _) => DoBackup();
        _restore.Click += (_, _) => DoRestore();
        _delete.Click += (_, _) => DoDelete();

        RefreshAccounts();
    }

    private static string Shorten(string p)
    {
        var app = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
        return p.StartsWith(app, StringComparison.OrdinalIgnoreCase) ? "%appdata%" + p[app.Length..] : p;
    }

    private void RefreshAccounts(string? select = null)
    {
        _profiles = Save.ListProfiles();
        var active = Save.ActiveProfileName();
        if (active is not null)
        {
            int i = _profiles.FindIndex(p => p.Name == active);
            if (i > 0) { var p = _profiles[i]; _profiles.RemoveAt(i); _profiles.Insert(0, p); }
        }
        if (_accHandler is not null) _acc.SelectionChanged -= _accHandler;
        _acc.Items.Clear();
        foreach (var p in _profiles) _acc.Items.Add(p.Name);
        if (_accHandler is not null) _acc.SelectionChanged += _accHandler;

        if (_profiles.Count == 0) { _path.Text = "存档位置：" + Shorten(Save.SavesDir); _path.ToolTip = Save.SavesDir; LoadEmpty(); return; }
        _acc.SelectedIndex = select is null ? 0 : Math.Max(0, _profiles.FindIndex(p => p.Name == select));
    }

    private void LoadEmpty()
    {
        _payload = Variant.Nil(); _version = "V0.0.0"; _chars = new(); _backups = new();
        _char.Items.Clear(); _bak.Items.Clear();
    }

    private void LoadAccount()
    {
        if (_acc.SelectedIndex < 0 || _acc.SelectedIndex >= _profiles.Count) { LoadEmpty(); return; }
        _cur = _profiles[_acc.SelectedIndex];
        try
        {
            (_payload, _version) = Save.LoadPayload(_cur);
        }
        catch (Exception e)
        {
            _payload = Variant.Nil(); _version = "V0.0.0";
            Err("读取失败", $"无法解密存档：\n{e.Message}");
        }
        _path.Text = "存档位置：" + Shorten(_cur.Dir);
        _path.ToolTip = _cur.Dir;

        _chars = Relief.Chars(_payload);
        _char.Items.Clear();
        foreach (var c in _chars) _char.Items.Add(Relief.Display(c));
        if (_char.Items.Count > 0) _char.SelectedIndex = 0;
        RefreshBackups();
    }

    private void RefreshBackups()
    {
        _backups = _cur is null ? new() : Backup.List(_cur.Name);
        _bak.Items.Clear();
        foreach (var b in _backups) _bak.Items.Add(Backup.Fmt(b));
        if (_bak.Items.Count > 0) _bak.SelectedIndex = 0;
    }

    private void Toast(string msg) => Gfp.Toast.Show(msg);

    private void Info(string title, string msg) => MessageWindow.Info(this, title, msg);
    private void Warn(string title, string msg) => MessageWindow.Warn(this, title, msg);
    private void Err(string title, string msg) => MessageWindow.Err(this, title, msg);
    private void Err(string msg) => Err("错误", msg);
    private bool Confirm(string title, string msg) => MessageWindow.Confirm(this, title, msg);

    private void DoRelief()
    {
        if (_cur is null) { Warn("提示", "请先选择有效账号。"); return; }
        if (_chars.Count == 0) { Warn("提示", "该存档没有角色数据。"); return; }
        int i = _char.SelectedIndex;
        if (i < 0 || i >= _chars.Count) { Warn("提示", "请选择角色。"); return; }
        var c = _chars[i];
        if (c.Level > 10)
        {
            Warn("等级过高",
                $"角色【{c.Name}（{c.RoleId}）】当前 Lv.{c.Level}，开荒减负仅限等级 <= 10 的新手角色。");
            return;
        }
        try
        {
            var ids = Relief.KunpengIds(c.RoleId);
            var owned = Relief.OwnedKunpengIds(_payload, c.Idx);
            var missing = ids.Where(x => !owned.Contains(x)).ToList();
            if (missing.Count == 0)
            {
                Info("已拥有", $"角色【{c.Name}（{c.RoleId}）】已拥有鲲鹏之征服者套装，无需减负。");
                return;
            }
            Relief.AddToInventory(_payload, c.Idx, missing);
            Save.SavePayload(_cur, _payload);
            Info("完成", $"已给予角色【{c.Name}（{c.RoleId}）】{missing.Count} 件鲲鹏装备到背包");
        }
        catch (Exception e) { Err("写回失败", $"加密回写失败：\n{e.Message}"); }
    }

    private void DoBackup()
    {
        if (_cur is null) return;
        try
        {
            Directory.CreateDirectory(Backup.Dir(_cur.Name));
            var stamp = Backup.NowStamp();
            Archive.ZipDir(_cur.Dir, Path.Combine(Backup.Dir(_cur.Name), $"{_version}_{stamp}.zip"));
            RefreshBackups();
            var d = Backup.DtFromStamp(stamp);
            Toast($"账号【{_cur.Name}】已备份存档：{_version} {d?.Render(Disp.YmdHms) ?? stamp}");
        }
        catch (Exception e) { Err("备份失败", $"压缩出错：\n{e.Message}"); }
    }

    private void DoRestore()
    {
        if (_cur is null) return;
        int i = _bak.SelectedIndex;
        if (i < 0 || i >= _backups.Count) { Warn("提示", "该账号还没有备份。"); return; }
        var b = _backups[i];
        try
        {
            Archive.ZipExtractAll(b.Path, _cur.Dir);
            LoadAccount();
            Toast($"账号【{_cur.Name}】已恢复备份存档：{Backup.Fmt(b)}");
        }
        catch (Exception e) { Err("恢复失败", $"解压出错：\n{e.Message}"); }
    }

    private void DoDelete()
    {
        if (_cur is null) return;
        int i = _bak.SelectedIndex;
        if (i < 0 || i >= _backups.Count) { Warn("提示", "该账号还没有备份。"); return; }
        var b = _backups[i];
        if (_backups.Count == 1 &&
            !Confirm("确认删除", $"【{Backup.Fmt(b)}】是账号【{_cur.Name}】的最后一个备份存档，是否删除？")) return;
        try
        {
            File.Delete(b.Path);
            try
            {
                var bd = Backup.Dir(_cur.Name);
                if (Directory.Exists(bd) && !Directory.EnumerateFileSystemEntries(bd).Any())
                    Directory.Delete(bd);
            }
            catch { }
            RefreshBackups();
            Toast($"账号【{_cur.Name}】已删除备份存档：{Backup.Fmt(b)}");
        }
        catch (Exception e) { Err("删除失败", $"删除出错：\n{e.Message}"); }
    }

    private void DoExport()
    {
        if (_cur is null) return;
        var dst = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), $"{_cur.Name}.zip");
        try
        {
            if (File.Exists(dst) && !Confirm("确认覆盖", $"桌面已存在存档文件【{_cur.Name}.zip】，是否覆盖？")) return;
            Archive.ZipDir(_cur.Dir, dst);
            Info("导出成功", $"账号【{_cur.Name}】的存档已导出到桌面。");
        }
        catch (Exception e) { Err("导出失败", $"导出出错：\n{e.Message}"); }
    }

    private void DoImport()
    {
        var dlg = new Microsoft.Win32.OpenFileDialog
        {
            Title = "选择存档文件",
            Filter = "存档压缩包|*.zip;*.7z;*.rar",
            InitialDirectory = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),
        };
        if (dlg.ShowDialog() != true) return;
        var kind = Archive.KindOf(dlg.FileName);
        if (kind is null) { Warn("提示", "仅支持 .zip / .7z / .rar 压缩包。"); return; }

        // 与 PySide6 一致：先按「包内顺序」列名并校验 .dat（没有 .dat 就不解压）
        List<string> names;
        try { names = Archive.ListNames(dlg.FileName); }
        catch (Exception e) { Err("导入失败", $"无法读取压缩包：\n{e.Message}"); return; }

        var (name, prefix) = Archive.ArchiveTarget(names, Path.GetFileNameWithoutExtension(dlg.FileName));
        if (name is null) { Warn("提示", "该压缩包内没有 .dat 存档数据，无法导入。"); return; }

        var target = Path.Combine(Save.SavesDir, name);
        if (Directory.Exists(target) && Archive.HasDat(target))
        {
            if (!Confirm("确认导入", $"将覆盖账号【{name}】的当前存档，是否确定？")) return;
            Directory.CreateDirectory(Backup.Dir(name));
            var ver = "V0.0.0";
            try { (_, ver) = Save.LoadPayload(new Profile { Name = name, Dir = target }); } catch { }
            Archive.ZipDir(target, Path.Combine(Backup.Dir(name), $"{ver}_{Backup.NowStamp()}.zip"));
        }

        string? tmp = null;
        try
        {
            Directory.CreateDirectory(target);
            tmp = Archive.ExtractAllToTemp(dlg.FileName, kind.Value);
            Archive.CopyPrefix(tmp, target, prefix);
            RefreshAccounts(name);
            Info("导入成功", $"账号【{name}】的存档已恢复。");
        }
        catch (Exception e) { Err("导入失败", $"解压出错：\n{e.Message}"); }
        finally
        {
            if (tmp is not null) { try { Directory.Delete(tmp, true); } catch { } }
        }
    }
}
