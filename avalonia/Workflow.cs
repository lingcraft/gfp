using Gfp.Core;

namespace Gfp.Mobile;

/// <summary>
/// 移动端的业务编排：只做 Core 调用 + 生成提示文案，完全不碰 UI。
///
/// ⚠ 为什么要单独抽出来：手机模拟器（MuMu 多 display）截不了图、点不准坐标，
///   没法用 UI 操作回归。于是让 <see cref="MainView"/>（真人点按钮）和
///   <see cref="Demo"/>（--demo 命令行自测）走【同一份逻辑】——
///   这样 --demo 跑通就等价于按钮背后的流程跑通，只是少了几个控件的点击。
/// </summary>
internal static class Workflow
{
    /// <summary>导出目录覆盖点，仅供 --demo 自测把输出引到临时目录，运行时保持 null。</summary>
    public static string? ExportDirOverride;

    /// <summary>导出目录，按用户要求直接落内部存储根目录，方便在文件管理器里一眼看到。</summary>
    public static string ExportDir => ExportDirOverride ??
#if ANDROID
        // ⚠ 写 /storage/emulated/0 而不是 /sdcard：二者对主用户等价（后者是指向 /storage/self/primary 的符号链接），
        //   但写死绝对路径更明确，也避免"应用分身"场景下 /sdcard 指向 /storage/emulated/10 的歧义。
        "/storage/emulated/0";
#else
        Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
#endif

    // ---------- 开荒减负 ----------

    // ⚠ 方法名刻意不叫 Relief / Backup —— 那样会在本类内遮蔽 Gfp.Core 的同名类型，
    //   导致下面所有 Relief.KunpengIds(...) / Backup.Dir(...) 报 CS0119。
    //
    // ⚠ 文案严格对齐 PySide6 版（gfp.py）：
    //   等级过高 → "角色【…】当前 Lv.x，开荒减负仅限等级 <= 10 的新手角色。"
    //   已拥有   → "角色【…】已拥有鲲鹏之征服者套装，无需减负。"
    //   完成     → "已给予角色【…】n 件鲲鹏装备到背包"（⚠ 原文没有句号）
    public static (bool ok, string title, string msg, Variant payload, string version) ApplyRelief(Profile p, CharInfo c)
    {
        if (c.Level > 10)
            return (false, "等级过高", $"角色【{c.Name}（{c.RoleId}）】当前 Lv.{c.Level}，开荒减负仅限等级 <= 10 的新手角色。",
                    Variant.Nil(), "");

        try
        {
            var (payload, version) = Save.LoadPayload(p);
            var ids = Relief.KunpengIds(c.RoleId);

            // ⚠ 对齐 PySide6 版：先判"找不到该角色的套装数据"，否则 ids 为空会被下面
            //   missing.Count == 0 误判成"已拥有鲲鹏之征服者套装"，语义完全相反。
            if (ids.Count == 0)
                return (false, "无套装数据", $"找不到角色【{c.RoleId}】的鲲鹏套装数据。", payload, version);

            var owned = Relief.OwnedKunpengIds(payload, c.Idx);
            var missing = ids.Where(x => !owned.Contains(x)).ToList();

            if (missing.Count == 0)
                return (true, "已拥有", $"角色【{c.Name}（{c.RoleId}）】已拥有鲲鹏之征服者套装，无需减负。",
                        payload, version);

            Relief.AddToInventory(payload, c.Idx, missing);
            Save.SavePayload(p, payload);

            // 重新读一遍，确认真的落盘了（而不是只改了内存里的对象）
            var (payload2, version2) = Save.LoadPayload(p);
            return (true, "完成", $"已给予角色【{c.Name}（{c.RoleId}）】{missing.Count} 件鲲鹏装备到背包",
                    payload2, version2);
        }
        catch (Exception e)
        {
            return (false, "写回失败", "加密回写失败：\n" + e.Message, Variant.Nil(), "");
        }
    }

    // ---------- 备份 / 恢复 / 删除 ----------

    // ⚠ 以下文案全部对齐 PySide6 版（gfp.py）：
    //   备份 → "账号【…】已备份存档：…"   恢复 → "账号【…】已恢复备份存档：…"
    //   删除 → "账号【…】已删除备份存档：…"
    //   失败 → "压缩出错：\n…" / "解压出错：\n…" / "删除出错：\n…"
    public static (bool ok, string title, string msg) MakeBackup(Profile p)
    {
        try
        {
            var dir = Backup.Dir(p.Name);
            Directory.CreateDirectory(dir);
            var stamp = Backup.NowStamp();

            // ⚠ 文件名只用时间戳，不带版本号 —— 手机版存档没有 save_version，
            //   强行带上就会出现「V0.0.0_20260926_091714.zip」这种前缀。
            //   Backup.ParseName 已支持无版本号格式（并保持对旧文件名的兼容）。
            Archive.ZipDir(p.Dir, Path.Combine(dir, $"{stamp}.zip"));

            var d = Backup.DtFromStamp(stamp);
            return (true, "", $"账号【{p.Name}】已备份存档：{d?.Render(Disp.YmdHms) ?? stamp}");
        }
        catch (Exception e)
        {
            return (false, "备份失败", "压缩出错：\n" + e.Message);
        }
    }

    public static (bool ok, string title, string msg) Restore(Profile p, BackupEntry b)
    {
        try
        {
            Archive.ZipExtractAll(b.Path, p.Dir);
            return (true, "", $"账号【{p.Name}】已恢复备份存档：{Backup.Fmt(b)}");
        }
        catch (Exception e)
        {
            return (false, "恢复失败", "解压出错：\n" + e.Message);
        }
    }

    public static (bool ok, string title, string msg) DeleteBackup(Profile p, BackupEntry b)
    {
        try
        {
            File.Delete(b.Path);
            try
            {
                var bd = Backup.Dir(p.Name);
                if (Directory.Exists(bd) && !Directory.EnumerateFileSystemEntries(bd).Any())
                    Directory.Delete(bd);
            }
            catch { }
            return (true, "", $"账号【{p.Name}】已删除备份存档：{Backup.Fmt(b)}");
        }
        catch (Exception e)
        {
            return (false, "删除失败", "删除出错：\n" + e.Message);
        }
    }

    // ---------- 导出 / 导入 ----------

    /// <summary>
    /// 导出预检：算出目标路径，并判断同名文件是否已存在（存在则调用方需先弹"确认覆盖"）。
    ///
    /// ⚠ 文件名严格对齐电脑版 gfp.py::do_export_save：
    ///       dst = desktop_dir() / f"{name}.zip"
    ///   —— 就是【账号名.zip】，不带版本号、不带时间戳。
    ///   （之前移动端是 "{name}_{yyyyMMdd_HHmmss}.zip"，已按用户要求改掉。）
    /// </summary>
    public static (bool ok, string msg, string path, bool exists) PrepareExport(Profile p)
    {
        try
        {
            Directory.CreateDirectory(ExportDir);
            var path = Path.Combine(ExportDir, p.Name + ".zip");
            return (true, "", path, File.Exists(path));
        }
        catch (Exception e)
        {
            return (false, "导出出错：\n" + e.Message, "", false);
        }
    }

    /// <summary>
    /// 执行导出。⚠ 同名文件的覆盖确认由调用方在 <see cref="PrepareExport"/> 之后完成 ——
    /// 对应电脑版 gfp.py::do_export_save 里那段 QMessageBox.question（标题"确认覆盖"）。
    /// </summary>
    public static (bool ok, string title, string msg) Export(Profile p, string path)
    {
        try
        {
            Archive.ZipDir(p.Dir, path);
            // ⚠ 对齐电脑版：正文为"账号【…】的存档已导出到桌面。" ——
            //   移动端没有"桌面"，目的地改成实际输出路径（语序保持一致）。
            //   ⚠ 不要在冒号后加 \n：由 TextWrapping 自动折行即可，短路径能一行放下。
            return (true, "导出成功", $"账号【{p.Name}】的存档已导出到：{path}");
        }
        catch (Exception e)
        {
            return (false, "导出失败", "导出出错：\n" + e.Message);
        }
    }

    /// <summary>导入源的类型。</summary>
    public enum SaveOrigin
    {
        /// 手机版存档：schema_version=1、无 save_version、无 profile.cfg
        Mobile,
        /// 电脑版存档：schema_version=2、有 save_version、通常还有 profile.cfg
        Desktop,
    }

    /// <summary>导入计划：来源判定 + 需要的兼容转换清单 + 转换所需参数。</summary>
    public sealed class ImportPlan
    {
        public string ZipPath = "";
        /// 目标账号名（同时也是手机版的 encryption_id，因为手机版没有 profile.cfg）
        public string Name = "";
        public string Prefix = "";
        public bool TargetExists;

        public SaveOrigin Origin = SaveOrigin.Mobile;

        /// 源存档解密用的 encryption_id（电脑版可能与账号名不同，如目录「桃子」而 encryption_id=「桃姊」）
        public string SourceEncryptionId = "";

        public bool NeedReencrypt;
        public bool NeedSchemaDowngrade;
        public bool NeedDropSaveVersion;
        public bool NeedDropProfileCfg;

        public string SourceSchema = "?";
        /// 给用户看的转换说明（为空 = 原样导入）
        public List<string> Conversions = new();

        public bool NeedsConversion => Conversions.Count > 0;
    }

    /// <summary>
    /// 分析导入源：解包 → 试解密 → 判定是手机版还是电脑版存档 → 列出需要的兼容转换。
    ///
    /// ⚠ 为什么必须做兼容（依据反编译的 GDScript，见 wpf/../GDRE）：
    ///   手机版 local_save_manager.gd 的 _get_save_validation_error() 里有
    ///       if schema_version > SCHEMA_VERSION: return "存档版本 %d 高于当前支持版本 %d"
    ///   而手机版 const SCHEMA_VERSION = 1、电脑版是 2 ⇒ 电脑版存档直接导入会被手机版【拒绝打开】。
    ///   另外手机版【没有 profile.cfg 机制】，encryption_id 直接用账号名，
    ///   若原样复制电脑版存档（其 encryption_id 可能不等于账号名），游戏会解密失败。
    /// </summary>
    public static (bool ok, string msg, ImportPlan plan) Analyze(string zipPath, string? hintStem = null)
    {
        var plan = new ImportPlan { ZipPath = zipPath };

        if (!File.Exists(zipPath)) return (false, "找不到压缩包：" + zipPath, plan);
        if (Archive.KindOf(zipPath) != Kind.Zip)
            return (false, "移动端只支持 zip 格式，7z / rar 请先在电脑上转成 zip。", plan);

        List<string> names;
        try { names = Archive.ListNames(zipPath); }
        catch (Exception e) { return (false, "读取压缩包失败：" + e.Message, plan); }

        var (name, prefix) = Archive.ArchiveTarget(names, Path.GetFileNameWithoutExtension(zipPath));
        if (name is null)
            return (false, $"压缩包【{Path.GetFileName(zipPath)}】里没有 .dat 存档，无法导入。", plan);

        plan.Name = name;
        plan.Prefix = prefix;

        string? tmp = null;
        try
        {
            tmp = Archive.ExtractAllToTemp(zipPath, Kind.Zip);
            var dir = prefix.Length > 0
                ? Path.Combine(tmp, prefix.TrimEnd('/').Replace('/', Path.DirectorySeparatorChar))
                : tmp;

            var savePath = Path.Combine(dir, "save.dat");
            if (!File.Exists(savePath))
            {
                var found = Directory.GetFiles(tmp, "save.dat", SearchOption.AllDirectories).FirstOrDefault()
                         ?? Directory.GetFiles(tmp, "*.dat", SearchOption.AllDirectories).FirstOrDefault();
                if (found is null) return (false, "压缩包里找不到 save.dat。", plan);
                dir = Path.GetDirectoryName(found)!;
                savePath = found;
            }

            // 源 encryption_id：优先 profile.cfg（电脑版），否则账号名（手机版）
            var cfgEnc = Cfg.Read(Path.Combine(dir, "profile.cfg"), "Profile", "encryption_id");
            var candidates = new List<string>();
            if (!string.IsNullOrWhiteSpace(cfgEnc)) candidates.Add(cfgEnc!);
            if (!candidates.Contains(name)) candidates.Add(name);
            // ⚠ hintStem = 用户所选文件的原始文件名（不含扩展名）。
            //   手机版导出的 zip 没有 profile.cfg、也没有目录前缀，账号名只能靠文件名猜，
            //   多一个候选多一分成功率（例如临时副本名字被改坏时兜底）。
            if (!string.IsNullOrWhiteSpace(hintStem) && !candidates.Contains(hintStem))
                candidates.Add(hintStem!);

            Variant? payload = null;
            string usedEnc = name;
            foreach (var enc in candidates)
            {
                try
                {
                    var raw = Gdec.ReadEncryptedFile(savePath, Gdec.SaveKey(enc));
                    payload = Envelope.FromRawStream(raw).Get("payload");
                    usedEnc = enc;
                    break;
                }
                catch { /* 换下一个候选 */ }
            }

            if (payload is null)
                return (false, "无法解密该存档（profile.cfg、账号名、原始文件名三种 encryption_id 都试过了）。", plan);

            plan.SourceEncryptionId = usedEnc;
            var target = Path.Combine(Save.SavesDir, name);
            plan.TargetExists = Directory.Exists(target) && Archive.HasDat(target);

            // 判定来源：出现电脑版独有特征即为电脑版存档
            var sv = payload.Get("schema_version");
            long schemaNo = sv?.Kind switch
            {
                VKind.Int => sv.I,
                VKind.Float => (long)sv.D,
                _ => 0,
            };
            plan.SourceSchema = schemaNo > 0 ? schemaNo.ToString() : "缺失";

            bool hasSaveVersion = payload.Get("save_version") is not null;
            bool hasProfileCfg = File.Exists(Path.Combine(dir, "profile.cfg"));

            plan.Origin = (hasSaveVersion || schemaNo > 1 || hasProfileCfg)
                ? SaveOrigin.Desktop
                : SaveOrigin.Mobile;

            if (plan.Origin == SaveOrigin.Desktop)
            {
                if (schemaNo != 1)
                {
                    plan.NeedSchemaDowngrade = true;
                    plan.Conversions.Add($"schema_version {plan.SourceSchema} → 1（手机版只认 ≤1，否则直接拒绝打开）");
                }
                if (hasSaveVersion)
                {
                    plan.NeedDropSaveVersion = true;
                    plan.Conversions.Add("移除 save_version（手机版没有这套机制）");
                }
                if (hasProfileCfg)
                {
                    plan.NeedDropProfileCfg = true;
                    plan.Conversions.Add("移除 profile.cfg（手机版无此机制，且会让本工具取到错误的 encryption_id）");
                }
                if (plan.SourceEncryptionId != name)
                {
                    plan.NeedReencrypt = true;
                    plan.Conversions.Add($"换密钥重新加密：「{plan.SourceEncryptionId}」→「{name}」（手机版以账号名为密钥）");
                }
            }

            return (true, "", plan);
        }
        catch (Exception e)
        {
            return (false, "分析压缩包失败：" + e.Message, plan);
        }
        finally
        {
            if (tmp is not null) { try { Directory.Delete(tmp, true); } catch { } }
        }
    }

    public static (bool ok, string title, string msg) Import(ImportPlan plan)
    {
        var name = plan.Name;
        var target = Path.Combine(Save.SavesDir, name);
        string? tmp = null;

        try
        {
            // 覆盖前自动备份一次，避免手滑
            if (plan.TargetExists)
            {
                var bdir = Backup.Dir(name);
                Directory.CreateDirectory(bdir);
                // ⚠ 文件名只用时间戳，对齐 MakeBackup —— 手机版存档没有 save_version，
                //   带版本号前缀恒为「V0.0.0_…」，纯噪声。
                Archive.ZipDir(target, Path.Combine(bdir, $"{Backup.NowStamp()}.zip"));
            }

            tmp = Archive.ExtractAllToTemp(plan.ZipPath, Kind.Zip);
            Directory.CreateDirectory(target);
            Archive.CopyPrefix(tmp, target, plan.Prefix);

            // ---------- 电脑版存档 → 手机版兼容转换 ----------
            if (plan.Origin == SaveOrigin.Desktop)
            {
                // ① 删掉手机版不认识、且会误导的附属文件
                foreach (var extra in new[] { "profile.cfg", "save.dat.pre_version_upgrade", "save.dat.bak" })
                {
                    var p = Path.Combine(target, extra);
                    if (File.Exists(p)) File.Delete(p);
                }

                // ② 改保存档本体：降 schema_version、删 save_version、必要时换密钥重加密
                var savePath = Path.Combine(target, "save.dat");
                if (File.Exists(savePath))
                {
                    var env = Envelope.FromRawStream(Gdec.ReadEncryptedFile(savePath, Gdec.SaveKey(plan.SourceEncryptionId)));
                    var payload = env.Get("payload");

                    if (payload is not null)
                    {
                        payload.Set("schema_version", Variant.OfInt(1));   // 手机版 SCHEMA_VERSION = 1
                        // ⚠ payload 的字典是 List<KeyValuePair<..>>（有序，对应 Godot indexmap），
                        //   所以删除条目要用 RemoveAll 而不是 Remove(key)。
                        payload.Dic?.RemoveAll(kv => kv.Key.Kind == VKind.Str && kv.Key.S == "save_version");
                    }

                    // ⚠ 无论 encryption_id 是否相同都用【账号名】重写一遍：
                    //   手机版没有 profile.cfg，key 恒为 sha256(pepper|YierPai|<账号名>)。
                    Gdec.WriteEncryptedFile(savePath, Gdec.SaveKey(name), Envelope.ToRawStream(env));
                }
            }

            // ⚠ 正文对齐 PySide6 版："账号【…】的存档已恢复。"
            //   电脑版存档的兼容处理说明附在后面（移动端特有，用户需要知道做了什么转换）。
            var note = plan.NeedsConversion
                ? "\n\n（已做电脑版兼容处理：" + string.Join("；", plan.Conversions) + "）"
                : "";
            return (true, "导入成功", $"账号【{name}】的存档已恢复。{note}");
        }
        catch (Exception e)
        {
            return (false, "导入失败", "解压出错：\n" + e.Message);
        }
        finally
        {
            if (tmp is not null) { try { Directory.Delete(tmp, true); } catch { } }
        }
    }
}
