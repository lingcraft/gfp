using Avalonia.Controls;
using Avalonia.Media;
using Avalonia.Platform.Storage;
using Avalonia.Threading;
using Gfp.Core;

namespace Gfp.Mobile;

public partial class MainView : UserControl
{
    private List<Profile> _profiles = new();
    private List<CharInfo> _chars = new();
    private List<BackupEntry> _backups = new();
    private Profile? _cur;
    private CharInfo? _curChar;
    private Variant _payload = Variant.Nil();

    /// 最近一次检测到的「所有文件访问权限」状态（桌面/低版本恒为 true）
    private bool _permissionGranted;

    /// 确认遮罩的"确定"回调
    private Action? _confirmAction;

    /// 导入流程中从系统文件选择器拿到的 zip 被复制成的临时文件，用完/取消都要删
    private string? _pendingZip;

    /// Toast 自动消失用的计时器
    private DispatcherTimer? _toastTimer;

    // 注意：PermPanel / GrantBtn / RecheckBtn / PathText / AccBox / CharBox /
    // ReliefBtn / BackupBtn / ExportBtn / ImportBtn / BakBox / RestoreBtn / DelBakBtn /
    // StatusText / ToastBox / ToastText /
    // ConfirmOverlay / ConfirmTitle / ConfirmMsg / ConfirmNo / ConfirmYes / IconCircle / IconGlyph
    // 这些字段由 Avalonia.Generators.NameGenerator 依据 xaml 里的 x:Name 自动生成
    // （internal 可见性），所以这里不能再手写同名成员，否则报 CS0102。

    public MainView()
    {
        Console.WriteLine("[GFP] MainView ctor begin");
        try
        {
            InitializeComponent();

            AccBox!.SelectionChanged += (_, _) => LoadAccount();
            CharBox!.SelectionChanged += (_, _) => SyncCurrentChar();
            BakBox!.SelectionChanged += (_, _) => { };

            GrantBtn!.Click += (_, _) => RequestPermission();
            RecheckBtn!.Click += (_, _) => RefreshByPermission();

            ReliefBtn!.Click += (_, _) => DoRelief();
            BackupBtn!.Click += (_, _) => DoBackup();
            ExportBtn!.Click += (_, _) => DoExport();
            ImportBtn!.Click += (_, _) => DoImport();
            RestoreBtn!.Click += (_, _) => DoRestore();
            DelBakBtn!.Click += (_, _) => DoDeleteBackup();

            ConfirmNo!.Click += (_, _) =>
            {
                HideConfirm();
                CleanupPendingZip();   // 用户取消，临时包没用了
            };
            ConfirmYes!.Click += (_, _) =>
            {
                var act = _confirmAction;
                // ⚠ 先把回调取出来再隐藏遮罩：HideConfirm 会清空 _confirmAction，
                //   而 _pendingZip 交给回调自己删（它要用这个文件）。
                HideConfirm();
                act?.Invoke();
            };

#if ANDROID
            // 用户从系统设置页返回时会触发（MainActivity.OnResume）
            StoragePermission.Resumed += OnActivityResumed;
#endif

            // 诊断：Android 上 Avalonia 有没有可用的 StorageProvider（"导入"依赖它调系统文件管理器）
            Loaded += (_, _) =>
            {
                try
                {
                    var top = TopLevel.GetTopLevel(this);
                    Console.WriteLine($"[GFP] TopLevel={top?.GetType().Name ?? "null"} "
                                    + $"StorageProvider={top?.StorageProvider?.GetType().Name ?? "null"}");
                }
                catch (Exception e)
                {
                    Console.WriteLine("[GFP] StorageProvider 探测失败: " + e.Message);
                }
            };

            RefreshByPermission();
            SelfCheck();
            Console.WriteLine("[GFP] MainView ctor done");
        }
        catch (Exception e)
        {
            Console.WriteLine("[GFP] MainView ctor FAILED: " + e);
            throw;
        }
    }

    // ---------- 提示 / 确认 / Toast ----------

    /// 状态栏留痕（底部那块浅色区域），同时也是日志
    private void Status(string msg)
    {
        StatusText!.Text = msg;
        Console.WriteLine("[GFP] " + msg.Replace('\n', ' '));
    }

    /// <summary>
    /// 轻提示 Toast：底部浮出、3 秒后自动消失、不阻塞操作。用于"成功"类消息。
    /// ⚠ 纯 Avalonia 自绘 —— Android 原生 Toast 要走 Android 插件（Java 侧），
    ///   自绘的好处是桌面/手机行为完全一致，也不需要在 Platforms/Android 里加代码。
    /// </summary>
    private void Toast(string msg)
    {
        Status(msg);                       // 顺便留痕到状态栏
        ToastText!.Text = msg;
        ToastBox!.IsVisible = true;

        _toastTimer?.Stop();
        _toastTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(3) };
        _toastTimer.Tick += (_, _) =>
        {
            _toastTimer!.Stop();
            ToastBox!.IsVisible = false;
        };
        _toastTimer.Start();
    }

    /// <summary>弹窗图标类型，对齐电脑版 MessageWindow 的 MsgIcon。</summary>
    private enum MsgIcon { Info, Warn, Error, Question }

    /// <summary>
    /// ⚠ 只用 ASCII 字符（i / ? / ! / x）画图标里的符号，配纯几何的圆底 ——
    ///   ⚠ ❌ ℹ 这类 Unicode 符号不在内嵌字体的 GB2312 子集里，会渲染成豆腐块。
    ///   （电脑版也是用几何图形画的，避开了字体度量差异。）
    /// </summary>
    private void SetIcon(MsgIcon icon)
    {
        (string fill, string glyph) = icon switch
        {
            MsgIcon.Warn => ("#FAC832", "!"),
            MsgIcon.Error => ("#D63C3C", "x"),
            MsgIcon.Question => ("#2E7CB3", "?"),
            _ => ("#2E7CB3", "i"),
        };
        IconCircle!.Fill = new SolidColorBrush(Color.Parse(fill));
        IconGlyph!.Text = glyph;
    }

    /// <summary>
    /// 提示弹窗：与确认框共用同一块遮罩，但只留「确定」一个按钮。
    /// 用于"失败 / 做不了"这类必须让用户明确看到的消息（不像 Toast 会自己消失）。
    /// </summary>
    private void Alert(string title, string msg, MsgIcon icon = MsgIcon.Warn)
    {
        _confirmAction = null;             // 点确定只是关掉，不执行任何动作
        SetIcon(icon);
        ConfirmTitle!.Text = title;
        ConfirmMsg!.Text = msg;
        ConfirmNo!.IsVisible = false;      // 隐藏「否」
        ConfirmYes!.Content = "确定";      // ⚠ 单按钮按电脑版用「确定」，不是「是」
        // ⚠ 「是」在 Grid.Column 0，隐藏「否」后只剩它占左半边 —— 让它跨两列铺满
        Grid.SetColumnSpan(ConfirmYes, 2);
        ConfirmOverlay!.IsVisible = true;
        Console.WriteLine($"[GFP-ALERT] {title}: {msg.Replace('\n', ' ')}");
    }

    private void Confirm(string title, string msg, Action onYes)
    {
        _confirmAction = onYes;
        SetIcon(MsgIcon.Question);
        ConfirmTitle!.Text = title;
        ConfirmMsg!.Text = msg;
        ConfirmNo!.IsVisible = true;       // 恢复「否」（Alert 会把它藏起来）
        ConfirmNo!.Content = "否";         // ⚠ 电脑版是「是」/「否」，不是「确定」/「取消」
        ConfirmYes!.Content = "是";
        Grid.SetColumnSpan(ConfirmYes, 1); // 恢复成半宽（与「否」并排）
        ConfirmOverlay!.IsVisible = true;
    }

    private void HideConfirm()
    {
        ConfirmOverlay!.IsVisible = false;
        _confirmAction = null;
    }

    private void CleanupPendingZip()
    {
        var p = _pendingZip;
        _pendingZip = null;
        if (p is null) return;
        try { File.Delete(p); } catch { }
    }

    private void RefreshPathText()
    {
        PathText!.Text = _cur is null ? "存档位置：" + Save.SavesDir : "存档位置：" + _cur.Dir;
    }

    // ---------- 权限 ----------

    private static bool CheckStoragePermission()
    {
#if ANDROID
        return StoragePermission.IsGranted();
#else
        // 桌面版没有这个权限概念，直接读本机 %APPDATA%
        return true;
#endif
    }

    private static void RequestPermission()
    {
#if ANDROID
        StoragePermission.OpenSettings();
#else
        Console.WriteLine("[GFP-PERM] 桌面目标无需该权限");
#endif
    }

#if ANDROID
    private void OnActivityResumed()
    {
        bool now = StoragePermission.IsGranted();
        if (now == _permissionGranted) return;   // 没变化就不打扰
        Console.WriteLine($"[GFP-PERM] 从设置返回，权限状态变化：{_permissionGranted} -> {now}");
        RefreshByPermission();
    }
#endif

    /// <summary>检测权限：没有则显示引导区并清空列表；有则加载存档。</summary>
    private void RefreshByPermission()
    {
        _permissionGranted = CheckStoragePermission();
        PermPanel!.IsVisible = !_permissionGranted;
        Console.WriteLine($"[GFP-PERM] 权限已授予 = {_permissionGranted}");

        if (_permissionGranted)
        {
            Console.WriteLine("[GFP-PERM] 开始读取存档");
            LoadProfiles();
            return;
        }

        // 未授权：把列表清干净，避免显示上一次的残留
        _profiles = new();
        _chars = new();
        _backups = new();
        _cur = null;
        _curChar = null;
        _payload = Variant.Nil();
        AccBox!.ItemsSource = null;
        CharBox!.ItemsSource = null;
        BakBox!.ItemsSource = null;
        PathText!.Text = "存档位置：—";
        Status("尚未授予「所有文件访问权限」，无法读取存档目录。");
    }

    // ---------- 数据加载 ----------

    /// <summary>
    /// 启动自检：验证 Trim 构建下【内嵌资源 + System.Text.Json】这条链路没被裁坏。
    /// Relief.KunpengIds 内部用 Assembly.GetManifestResourceStream 读装备库 JSON 并用
    /// JsonDocument 解析 —— 这正是 Release(trimming) 最容易被裁掉的地方，
    /// 而它平时只在"减负"时才被调用，不主动验证的话上真机才会发现问题。
    /// </summary>
    private static void SelfCheck()
    {
        try
        {
            foreach (var role in new[] { "伊尔", "派派", "大竹", "敖天" })
            {
                var ids = Relief.KunpengIds(role);
                Console.WriteLine($"[GFP-SELF] 装备库 {role}：鲲鹏 id 数 = {ids.Count}");
            }
            var uid = Relief.GenUid();
            Console.WriteLine($"[GFP-SELF] GenUid() = {uid}");
        }
        catch (Exception e)
        {
            Console.WriteLine("[GFP-SELF] 自检失败（很可能是 trimming 裁掉了内嵌资源/JSON）: " + e);
        }
    }

    private void LoadProfiles(string? select = null)
    {
        _profiles = Save.ListProfiles();

        // PC 版会把"当前游戏账号"提到第一位（读 login_credentials.cfg），移动端保持一致
        var active = Save.ActiveProfileName();
        if (active is not null)
        {
            int k = _profiles.FindIndex(p => p.Name == active);
            if (k > 0) { var p = _profiles[k]; _profiles.RemoveAt(k); _profiles.Insert(0, p); }
        }

        AccBox!.ItemsSource = _profiles.Select(p => p.Name).ToList();

        if (_profiles.Count == 0)
        {
            CharBox!.ItemsSource = null;
            _chars = new();
            _backups = new();
            BakBox!.ItemsSource = null;
            PathText!.Text = "存档位置：" + Save.SavesDir;
            Status("没有可用账号。");
            return;
        }

        int idx = 0;
        if (select is not null)
        {
            int k = _profiles.FindIndex(p => p.Name == select);
            if (k >= 0) idx = k;
        }
        AccBox.SelectedIndex = idx;
    }

    private void LoadAccount()
    {
        int i = AccBox!.SelectedIndex;
        if (i < 0 || i >= _profiles.Count) return;
        _cur = _profiles[i];

        try
        {
            // ⚠ 不保留 version —— 手机版存档没有 save_version，取到的恒是哨兵值 V0.0.0
            (_payload, _) = Save.LoadPayload(_cur);
        }
        catch (Exception e)
        {
            CharBox!.ItemsSource = null;
            BakBox!.ItemsSource = null;
            _chars = new();
            _backups = new();
            _curChar = null;
            RefreshPathText();
            Status($"账号【{_cur.Name}】读取失败：{e.Message}");
            return;
        }

        _chars = Relief.Chars(_payload);
        CharBox!.ItemsSource = _chars.Select(Relief.Display).ToList();
        if (_chars.Count > 0) CharBox.SelectedIndex = 0;
        else { _curChar = null; }

        Console.WriteLine($"[GFP] 账号 {_cur.Name}（{_cur.EncryptionId()}）：{_chars.Count} 个有效角色");
        foreach (var c in _chars)
            Console.WriteLine($"[GFP]   {Relief.Display(c)}");

        RefreshPathText();
        RefreshBackups();
        SyncCurrentChar();
    }

    /// <summary>
    /// 把「角色下拉框的选中项」同步到 _curChar（减负等操作要用它拿角色下标与等级）。
    /// ⚠ 只做数据同步，不再往界面写任何角色详情文本 —— 界面上那一块已按要求整块移除。
    /// </summary>
    private void SyncCurrentChar()
    {
        int i = CharBox!.SelectedIndex;
        _curChar = (i >= 0 && i < _chars.Count) ? _chars[i] : null;
    }

    private void RefreshBackups()
    {
        if (_cur is null) { _backups = new(); BakBox!.ItemsSource = null; return; }
        _backups = Backup.List(_cur.Name);
        // 备份文件名已改成纯时间戳（手机版存档没有 save_version），无需再做版本号的美化替换。
        // 旧版本留下的「V0.0.0_xxx.zip」仍能被 Backup.ParseName 正确解析。
        BakBox!.ItemsSource = _backups.Select(Backup.Fmt).ToList();
        if (_backups.Count > 0) BakBox.SelectedIndex = 0;
    }

    // ---------- 功能：一律委托给 Workflow ----------
    // ⚠ 这里只做"取 UI 选中项 → 调 Workflow → 显示文案/弹确认"，真正的 Core 编排在 Workflow 里，
    //   与 --demo 命令行自测【共用同一份代码】，所以自测跑通即代表这里点按钮的流程也通。

    private void ReloadChars(int? keepIdx = null)
    {
        _chars = Relief.Chars(_payload);
        CharBox!.ItemsSource = _chars.Select(Relief.Display).ToList();

        int idx = 0;
        if (keepIdx is not null)
        {
            int k = _chars.FindIndex(x => x.Idx == keepIdx.Value);
            if (k >= 0) idx = k;
        }
        if (_chars.Count > 0) CharBox.SelectedIndex = idx;
        else _curChar = null;
    }

    private void DoRelief()
    {
        if (_cur is null) { Toast("请先选择账号。"); return; }
        if (_curChar is null) { Toast("请先选择角色。"); return; }

        var keep = _curChar.Idx;
        var (ok, msg, payload, version) = Workflow.ApplyRelief(_cur, _curChar);

        if (ok)
        {
            _payload = payload;
            ReloadChars(keep);
            Toast(msg);
        }
        else
        {
            // 失败/不符合条件（例如等级 > 10）都走弹窗，避免 Toast 一闪而过被忽略
            Alert("无法减负", msg);
        }
    }

    private void DoBackup()
    {
        if (_cur is null) { Toast("请先选择账号。"); return; }

        var (ok, msg) = Workflow.MakeBackup(_cur);
        if (ok)
        {
            RefreshBackups();
            Toast(msg);
        }
        else
        {
            Alert("备份失败", msg, MsgIcon.Error);
        }
    }

    private void DoRestore()
    {
        if (_cur is null) { Toast("请先选择账号。"); return; }
        int i = BakBox!.SelectedIndex;
        if (i < 0 || i >= _backups.Count) { Toast("请先选择要恢复的备份。"); return; }

        var p = _cur;
        var b = _backups[i];
        Confirm("确认恢复",
            $"将用备份【{Backup.Fmt(b)}】\n覆盖账号【{p.Name}】的当前存档。\n\n当前存档会被替换，是否继续？",
            () =>
            {
                var (ok, msg) = Workflow.Restore(p, b);
                if (ok)
                {
                    LoadAccount();   // 存档整个换了，重新加载账号
                    Toast(msg);
                }
                else
                {
                    Alert("恢复失败", msg, MsgIcon.Error);
                }
            });
    }

    private void DoDeleteBackup()
    {
        if (_cur is null) { Toast("请先选择账号。"); return; }
        int i = BakBox!.SelectedIndex;
        if (i < 0 || i >= _backups.Count) { Toast("请先选择要删除的备份。"); return; }

        var p = _cur;
        var b = _backups[i];

        // ⚠ 确认时机对齐电脑版 DoDelete：
        //   只有删【最后一个备份】才弹确认，删其它备份直接执行。
        //   电脑版原文：if (_backups.Count == 1 && !Confirm(...)) return;
        if (_backups.Count == 1)
        {
            Confirm("确认删除",
                $"【{Backup.Fmt(b)}】是账号【{p.Name}】的最后一个备份存档，是否删除？",
                () => DeleteBackupNow(p, b));
            return;
        }

        DeleteBackupNow(p, b);
    }

    /// <summary>真正的删除动作，被 DoDeleteBackup 的两条分支共用。</summary>
    private void DeleteBackupNow(Profile p, BackupEntry b)
    {
        var (ok, msg) = Workflow.DeleteBackup(p, b);
        if (ok)
        {
            RefreshBackups();
            Toast(msg);
        }
        else
        {
            Alert("删除失败", msg, MsgIcon.Error);
        }
    }

    private void DoExport()
    {
        if (_cur is null) { Toast("请先选择账号。"); return; }
        var (ok, msg) = Workflow.Export(_cur);
        if (ok) Toast(msg);
        else Alert("导出失败", msg, MsgIcon.Error);
    }

    private async void DoImport()
    {
        var top = TopLevel.GetTopLevel(this);
        if (top?.StorageProvider is null)
        {
            Alert("无法导入", "当前平台没有可用的文件选择器。");
            return;
        }

        IReadOnlyList<IStorageFile> files;
        try
        {
            files = await top.StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions
            {
                Title = "选择存档压缩包",
                AllowMultiple = false,
                FileTypeFilter = new[]
                {
                    new FilePickerFileType("ZIP 压缩包") { Patterns = new[] { "*.zip" } },
                    new FilePickerFileType("所有文件") { Patterns = new[] { "*" } },
                },
            });
        }
        catch (Exception e)
        {
            Alert("无法导入", "打开文件选择器失败：" + e.Message);
            return;
        }

        if (files.Count == 0) { Toast("已取消选择。"); return; }

        // ⚠ SAF（系统文件管理器）返回的是 content:// URI，拿不到真实文件路径，
        //   而 Archive.* 全都要路径，所以先复制成临时文件再走原流程。
        string tmp;
        try
        {
            tmp = Path.Combine(Path.GetTempPath(), "gfp_import_" + Backup.NowStamp() + ".zip");
            await using (var src = await files[0].OpenReadAsync())
            await using (var dst = File.Create(tmp))
                await src.CopyToAsync(dst);
        }
        catch (Exception e)
        {
            Alert("无法导入", "读取所选文件失败：" + e.Message);
            return;
        }

        var (ok, msg, plan) = Workflow.Analyze(tmp);
        if (!ok)
        {
            try { File.Delete(tmp); } catch { }
            Alert("无法导入", msg);
            return;
        }

        _pendingZip = tmp;
        var display = files[0].Name;

        // 组装确认文案：电脑版存档要明确告诉用户会做哪些兼容转换
        var sb = new StringBuilder();
        sb.AppendLine($"压缩包：{display}");
        sb.AppendLine();
        sb.AppendLine(plan.TargetExists
            ? $"将【覆盖】已有账号【{plan.Name}】的存档（覆盖前会自动备份一次）。"
            : $"将新建账号【{plan.Name}】。");
        if (plan.Origin == Workflow.SaveOrigin.Desktop)
        {
            sb.AppendLine();
            sb.AppendLine("⚠ 检测到这是电脑版存档，导入时会自动做兼容处理：");
            foreach (var c in plan.Conversions) sb.AppendLine("   · " + c);
        }
        sb.AppendLine();
        sb.Append("是否继续？");

        Confirm("确认导入", sb.ToString(), () =>
        {
            var zip = _pendingZip;
            _pendingZip = null;
            if (zip is null) { Status("导入失败：临时文件已丢失。"); return; }

            plan.ZipPath = zip;
            var (ok2, msg2) = Workflow.Import(plan);
            try { File.Delete(zip); } catch { }
            if (ok2)
            {
                LoadProfiles(plan.Name);
                Toast(msg2);
            }
            else
            {
                Alert("导入失败", msg2, MsgIcon.Error);
            }
        });
    }
}
