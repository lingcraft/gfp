using Gfp.Core;

namespace Gfp.Mobile;

/// <summary>
/// 命令行端到端自测（--demo）：不起 UI，把「减负 / 备份 / 恢复 / 导出 / 导入 / 删备份」
/// 整条流程跑一遍。
///
/// ⚠⚠ 全程只操作【真实存档的临时副本】：先把 %APPDATA%\Godot\app_userdata\YierPai
///     整个复制到 %TEMP%，再把 Save.DataDirOverride 指过去，跑完删掉副本。
///     真实存档一个字节都不会被改。
///
/// 之所以要用它替代"在模拟器上点按钮"：MuMu 是多 display 环境（App 跑在 display 12），
/// screencap 对虚拟 display 一律返回 Status: -2，截不了图也点不准坐标。
/// 而这里调用的 Workflow.* 与 MainView 按钮回调是【同一份代码】，所以跑通即等价于按钮跑通。
/// </summary>
internal static class Demo
{
    private static readonly StringBuilder Sb = new();
    private static int _pass, _fail;

    private static void Line(string s = "")
    {
        Sb.AppendLine(s);
        Console.WriteLine(s);
    }

    private static void Check(string name, bool ok, string detail = "")
    {
        if (ok) { _pass++; Line($"  [OK]   {name}{(detail.Length > 0 ? " —— " + detail : "")}"); }
        else { _fail++; Line($"  [FAIL] {name}{(detail.Length > 0 ? " —— " + detail : "")}"); }
    }

    public static void Run()
    {
        Line("=== gfp-mobile 端到端自测（--demo）===");
        Line("Core 复用自 wpf/Core，逻辑入口 = Workflow.*（与 MainView 按钮共用同一份代码）");
        Line();

        // ---------- 0) 准备副本 ----------
        var real = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "Godot", "app_userdata", "YierPai");
        Line($"[0] 真实存档根: {real}");

        if (!Directory.Exists(real))
        {
            Line("    真实存档目录不存在，自测中止。");
            Finish();
            return;
        }

        var work = Path.Combine(Path.GetTempPath(), "gfp_demo_" + DateTime.Now.ToString("yyyyMMdd_HHmmss"));
        try
        {
            CopyDir(real, work);
        }
        catch (Exception e)
        {
            Line($"    复制副本失败：{e.Message}");
            Finish();
            return;
        }

        Save.DataDirOverride = work;
        // ⚠ 桌面目标的默认导出目录是"桌面"，自测不能往用户桌面扔文件，引到副本里
        Workflow.ExportDirOverride = Path.Combine(work, "exports");
        Line($"    副本工作目录: {work}");
        Line($"    Save.SavesDir = {Save.SavesDir}");
        Line($"    导出目录 = {Workflow.ExportDir}");
        Line();

        try
        {
            Step1_List();
            Step2_Read();
            Step3_Relief();
            Step4_BackupRestore();
            Step5_ExportImport();
            Step5b_DesktopCompat();
            Step6_DeleteBackup();
        }
        catch (Exception e)
        {
            Line($"!! 自测过程中抛异常：{e}");
            _fail++;
        }
        finally
        {
            try { Directory.Delete(work, true); Line(); Line($"（已清理副本 {work}）"); } catch { }
        }

        Finish();
    }

    // ---------- 1) 列账号 ----------
    private static void Step1_List()
    {
        Line("[1] Save.ListProfiles()");
        var profiles = Save.ListProfiles();
        Line($"    账号数 = {profiles.Count} -> {string.Join(", ", profiles.Select(p => p.Name))}");
        Check("能列出账号", profiles.Count > 0);
        if (profiles.Count == 0) throw new Exception("没有账号，后续步骤无法继续。");
    }

    // ---------- 2) 读存档 ----------
    private static void Step2_Read()
    {
        Line();
        Line("[2] Save.LoadPayload() + Relief.Chars()");
        var p = Save.ListProfiles()[0];
        var (payload, version) = Save.LoadPayload(p);
        var chars = Relief.Chars(payload);

        Line($"    账号【{p.Name}】encryption_id={p.EncryptionId()} 版本={version} 角色={chars.Count}");
        foreach (var c in chars) Line($"      {Relief.Display(c)}");
        Check("能解密并读出角色", chars.Count > 0);
    }

    // ---------- 3) 减负 ----------
    private static void Step3_Relief()
    {
        Line();
        Line("[3] Workflow.ApplyRelief()（开荒减负）");

        var p = Save.ListProfiles()[0];
        var (payload, _) = Save.LoadPayload(p);
        var chars = Relief.Chars(payload);

        var target = chars.FirstOrDefault(c => c.Level <= 10);
        if (target is null)
        {
            Line("    该账号没有 ≤10 级的角色，跳过减负测试。");
            return;
        }

        var ids = Relief.KunpengIds(target.RoleId);
        var want = ids.Count;

        // 这个存档多半已被电脑版减负过（7/7 全满），直接跑只会得到"无需减负"，
        // 验证不到"补齐"能力。所以先在【副本】上人为把鲲鹏装备摘掉，制造缺口。
        // ⚠ 实测这存档的鲲鹏全在【身上穿戴】里（背包是空的），所以要连穿戴一起摘。
        var removed = StripKunpengWorn(payload, target.Idx, ids)
                    + StripKunpengFromBag(payload, target.Idx, ids);
        if (removed > 0) Save.SavePayload(p, payload);

        var before = Relief.OwnedKunpengIds(payload, target.Idx).Count;
        Line($"    目标角色 {Relief.Display(target)}：先摘掉背包里 {removed} 件鲲鹏，当前 {before}/{want} 件");

        var (ok, title, msg, payload2, version2) = Workflow.ApplyRelief(p, target);
        Line($"    返回：ok={ok} title={title} version={version2}");
        Line($"    文案：{msg}");
        Check("减负执行成功", ok, msg);

        if (ok)
        {
            var after = Relief.OwnedKunpengIds(payload2, target.Idx).Count;
            Line($"    减负后 鲲鹏 {after}/{want} 件");
            Check("装备数确实增加并落盘", after > before, $"{before} -> {after}");

            // 再跑一次应当提示"无需减负"
            var (ok2, title2, msg2, _, _) = Workflow.ApplyRelief(p, target);
            Check("重复减负被正确拦住", ok2 && msg2.Contains("已拥有"), $"title={title2} {msg2}");
        }
    }

    /// <summary>摘掉【身上穿戴】（characters[idx].equipment，槽位 -&gt; 物品）里的鲲鹏装备。</summary>
    private static int StripKunpengWorn(Variant payload, int idx, List<long> kunpeng)
    {
        var arr = payload.Get("characters")?.AsArray();
        if (arr is null || idx < 0 || idx >= arr.Count) return 0;

        var worn = arr[idx].Get("equipment");
        if (worn?.Dic is null) return 0;

        var set = new HashSet<long>(kunpeng);
        // ⚠ Dic 是 List<KeyValuePair<Variant, Variant>>（有序列表，语义等同 Godot 的 indexmap），
        //   不是 Dictionary，所以删除要用 RemoveAll。
        int before = worn.Dic.Count;
        worn.Dic.RemoveAll(kv =>
        {
            var idv = kv.Value?.Get("id");
            long x = idv?.Kind switch
            {
                VKind.Float => (long)idv.D,
                VKind.Int => idv.I,
                _ => 0,
            };
            return set.Contains(x);
        });
        return before - worn.Dic.Count;
    }

    /// <summary>只摘背包（inventory.equipment）里的鲲鹏装备，不动身上穿戴，返回摘掉的数量。</summary>
    private static int StripKunpengFromBag(Variant payload, int idx, List<long> kunpeng)
    {
        var arr = payload.Get("characters")?.AsArray();
        if (arr is null || idx < 0 || idx >= arr.Count) return 0;

        var eq = arr[idx].Get("inventory")?.Get("equipment");
        if (eq?.Arr is null) return 0;

        var set = new HashSet<long>(kunpeng);
        return eq.Arr.RemoveAll(v =>
        {
            var idv = v.Get("id");
            long x = idv?.Kind switch
            {
                VKind.Float => (long)idv.D,
                VKind.Int => idv.I,
                _ => 0,
            };
            return set.Contains(x);
        });
    }

    // ---------- 4) 备份 / 恢复 ----------
    private static void Step4_BackupRestore()
    {
        Line();
        Line("[4] Workflow.MakeBackup() / Restore()");

        var p = Save.ListProfiles()[0];
        var (payload, _) = Save.LoadPayload(p);
        var chars = Relief.Chars(payload);
        var target = chars.FirstOrDefault(c => c.Level <= 10);

        var (okB, _, msgB) = Workflow.MakeBackup(p);
        Line($"    备份：ok={okB} {msgB}");
        Check("备份成功", okB, msgB);

        var baks = Backup.List(p.Name);
        Line($"    备份列表 = {baks.Count} 条 -> {string.Join(" | ", baks.Select(Backup.Fmt))}");
        Check("备份文件能被识别", baks.Count > 0);
        if (baks.Count == 0) return;

        if (target is not null)
        {
            // 制造一笔差异，好观察 restore 是否真的把文件回滚了
            var beforeRestore = Relief.OwnedKunpengIds(Save.LoadPayload(p).payload, target.Idx).Count;

            // 再手动塞一件不存在的装备 id，制造差异（用一个肯定不在鲲鹏列表里的 id）
            var (pl, _) = Save.LoadPayload(p);
            Relief.AddToInventory(pl, target.Idx, new List<long> { 999999999L });
            Save.SavePayload(p, pl);
            var dirty = Relief.OwnedKunpengIds(Save.LoadPayload(p).payload, target.Idx).Count;
            Line($"    人为改动后（插入假 id）：{dirty} 件");

            var (okR, _, msgR) = Workflow.Restore(p, baks[0]);
            Line($"    恢复：ok={okR} {msgR}");
            Check("恢复成功", okR, msgR);

            var afterRestore = Relief.OwnedKunpengIds(Save.LoadPayload(p).payload, target.Idx).Count;
            Line($"    恢复后：{afterRestore} 件（期望回到 {beforeRestore}）");
            Check("存档确实回滚到备份状态", afterRestore == beforeRestore, $"{dirty} -> {afterRestore}");
        }
    }

    // ---------- 5) 导出 / 导入 ----------
    private static void Step5_ExportImport()
    {
        Line();
        Line("[5] Workflow.PrepareExport() / Export() / Analyze() / Import()");

        var p = Save.ListProfiles()[0];

        var (okEP, msgEP, expPath, expExists) = Workflow.PrepareExport(p);
        Line($"    导出预检：ok={okEP} 已存在={expExists}");
        Line($"    目标路径 = {expPath}");
        Check("导出预检通过", okEP, msgEP);

        // ⚠ 文件名必须是【账号名.zip】（对齐电脑版），不能带版本号 / 时间戳
        Check("导出文件名 = 账号名.zip",
            Path.GetFileName(expPath) == p.Name + ".zip", Path.GetFileName(expPath));

        var (okE, _, msgE) = Workflow.Export(p, expPath);
        Line($"    导出：ok={okE} {msgE.Replace('\n', ' ')}");
        Check("导出成功", okE, msgE);
        Check("导出文件存在", File.Exists(expPath));

        // 再预检一次：同名文件此时已存在 ⇒ 应触发"确认覆盖"分支
        var (okEP2, _, expPath2, expExists2) = Workflow.PrepareExport(p);
        Check("重复导出会提示覆盖", okEP2 && expExists2 && expPath2 == expPath);

        // --demo 没有 UI，模拟"用户在系统文件管理器里选中了刚导出的那个包"
        var picked = expPath;
        Line($"    模拟用户选中：{Path.GetFileName(picked)}");

        var (okP, msgP, plan) = Workflow.Analyze(picked);
        Line($"    Analyze: ok={okP} name={plan.Name} prefix=[{plan.Prefix}] exists={plan.TargetExists} "
           + $"来源={plan.Origin} schema={plan.SourceSchema} 转换={plan.Conversions.Count}项");
        if (!okP) { Check("导入预检通过", false, msgP); return; }
        Check("导入预检通过", okP, $"账号={plan.Name} 已存在={plan.TargetExists}");

        var (okI, _, msgI) = Workflow.Import(plan);
        Line($"    导入：ok={okI} {msgI}");
        Check("导入执行成功", okI, msgI);

        // 导入后账号仍应可读
        var again = Save.Find(plan.Name);
        Check("导入后账号可被重新列出", again is not null);
        if (again is not null)
        {
            var (pl, ver) = Save.LoadPayload(again);
            var cs = Relief.Chars(pl);
            Line($"    导入后：版本={ver} 角色={cs.Count}");
            Check("导入后存档可解密", cs.Count > 0);
        }
    }

    // ---------- 5b) 电脑版存档 → 手机版兼容转换 ----------
    private static void Step5b_DesktopCompat()
    {
        Line();
        Line("[5b] 电脑版存档导入的兼容转换（Analyze 判定 + Import 转换）");

        var p = Save.ListProfiles().FirstOrDefault();
        if (p is null) { Line("    没有账号，跳过。"); return; }

        // 造一个"电脑版风格"的存档：schema_version=2 + save_version + profile.cfg + 换过的 encryption_id
        var fakeName = "兼容测试_" + DateTime.Now.ToString("HHmmss");
        const string desktopEnc = "电脑端档案";     // ⚠ 故意让 encryption_id ≠ 账号名
        var srcDir = Path.Combine(Path.GetTempPath(), "gfp_compat_src_" + DateTime.Now.ToString("HHmmss"));
        Directory.CreateDirectory(srcDir);

        try
        {
            var (payload, _) = Save.LoadPayload(p);
            // 模拟成电脑版结构
            payload.Set("schema_version", Variant.OfInt(2));
            var svDict = Variant.OfDict();
            svDict.Set("last_client_version", Variant.OfStr("V1.0.2"));
            svDict.Set("last_client_build", Variant.OfInt(10002));
            svDict.Set("minimum_client_build", Variant.OfInt(10002));
            payload.Set("save_version", svDict);

            var env = Variant.OfDict();
            env.Set("magic", Variant.OfStr(Gdec.SaveMagic));
            env.Set("container_version", Variant.OfInt(Gdec.ContainerVersion));
            env.Set("payload", payload);

            // ⚠ 用【电脑端档案】当密钥加密，模拟"存档的 encryption_id 与账号名不同"
            Gdec.WriteEncryptedFile(Path.Combine(srcDir, "save.dat"), Gdec.SaveKey(desktopEnc), Envelope.ToRawStream(env));
            // 造出电脑版特有的 profile.cfg
            File.WriteAllText(Path.Combine(srcDir, "profile.cfg"),
                "[Profile]\n\nversion=1\nencryption_id=\"" + desktopEnc + "\"\n", new UTF8Encoding(false));
            // 造出电脑版特有的 pre_version_upgrade
            File.Copy(Path.Combine(srcDir, "save.dat"), Path.Combine(srcDir, "save.dat.pre_version_upgrade"), true);

            var zip = Path.Combine(Path.GetTempPath(), fakeName + ".zip");
            Archive.ZipDir(srcDir, zip);   // 复用工具自己的打包逻辑
            Line($"    已构造电脑版风格压缩包：{Path.GetFileName(zip)}");
            Line($"      schema_version=2、含 save_version、profile.cfg(encryption_id={desktopEnc})、pre_version_upgrade");

            var (okA, msgA, plan) = Workflow.Analyze(zip);
            Line($"    Analyze: ok={okA} 来源={plan.Origin} 源encryption_id={plan.SourceEncryptionId} schema={plan.SourceSchema}");
            foreach (var c in plan.Conversions) Line($"      转换：{c}");
            Check("能识别出电脑版存档", okA && plan.Origin == Workflow.SaveOrigin.Desktop, msgA);
            Check("列出了兼容转换项", plan.Conversions.Count >= 3, $"{plan.Conversions.Count} 项");

            plan.Name = fakeName;
            plan.TargetExists = false;
            var (okI, _, msgI) = Workflow.Import(plan);
            Line($"    Import: ok={okI} {msgI}");
            Check("带兼容转换的导入成功", okI, msgI);

            // 断言转换结果
            var dst = Path.Combine(Save.SavesDir, fakeName);
            Check("profile.cfg 已被移除", !File.Exists(Path.Combine(dst, "profile.cfg")));
            Check("pre_version_upgrade 已被移除", !File.Exists(Path.Combine(dst, "save.dat.pre_version_upgrade")));

            var (pl2, ver2) = Save.LoadPayload(new Profile { Name = fakeName, Dir = dst });
            var svx = pl2.Get("schema_version");
            long sNo = svx?.Kind switch { VKind.Int => svx.I, VKind.Float => (long)svx.D, _ => -1 };
            Line($"    转换后 schema_version={sNo}、save_version={pl2.Get("save_version")?.Kind.ToString() ?? "null"}、版本读到 {ver2}");
            Check("schema_version 已降到 1", sNo == 1, sNo.ToString());
            Check("save_version 已移除", pl2.Get("save_version") is null);
            Check("用账号名（而非电脑端 encryption_id）能解密", Relief.Chars(pl2).Count > 0);

            try { File.Delete(zip); } catch { }
        }
        catch (Exception e)
        {
            Line($"    构造/转换过程抛异常：{e.Message}");
            _fail++;
        }
        finally
        {
            try { Directory.Delete(srcDir, true); } catch { }
        }
    }

    // ---------- 6) 删除备份 ----------
    private static void Step6_DeleteBackup()
    {
        Line();
        Line("[6] Workflow.DeleteBackup()");

        var p = Save.ListProfiles()[0];
        var baks = Backup.List(p.Name);
        if (baks.Count == 0) { Line("    没有备份可删，跳过。"); return; }

        var victim = baks[0];
        var (ok, _, msg) = Workflow.DeleteBackup(p, victim);
        Line($"    删除：ok={ok} {msg}");
        Check("删除备份成功", ok, msg);

        var after = Backup.List(p.Name);
        Check("备份数确实减少", after.Count == baks.Count - 1, $"{baks.Count} -> {after.Count}");
    }

    // ---------- 工具 ----------

    private static void CopyDir(string src, string dst)
    {
        Directory.CreateDirectory(dst);
        foreach (var f in Directory.GetFiles(src))
            File.Copy(f, Path.Combine(dst, Path.GetFileName(f)), true);
        foreach (var d in Directory.GetDirectories(src))
            CopyDir(d, Path.Combine(dst, Path.GetFileName(d)));
    }

    private static void Finish()
    {
        Line();
        Line($"=== 结果：{_pass} 通过 / {_fail} 失败 ===");

        var text = Sb.ToString();
        try
        {
            File.WriteAllText(
                Path.Combine(AppContext.BaseDirectory, "demo.log"),
                text,
                new UTF8Encoding(false));
        }
        catch
        {
            // 写不了就算了，stdout 那份还在
        }
    }
}
