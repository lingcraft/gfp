package com.yierpai.savetool

import com.yierpai.savetool.core.Archive
import com.yierpai.savetool.core.Backup
import com.yierpai.savetool.core.BackupEntry
import com.yierpai.savetool.core.CharInfo
import com.yierpai.savetool.core.Cfg
import com.yierpai.savetool.core.Disp
import com.yierpai.savetool.core.Envelope
import com.yierpai.savetool.core.Gdec
import com.yierpai.savetool.core.Kind
import com.yierpai.savetool.core.Profile
import com.yierpai.savetool.core.Relief
import com.yierpai.savetool.core.Save
import com.yierpai.savetool.core.VKind
import com.yierpai.savetool.core.Variant
import java.io.File

/** 通用结果：ok + 标题 + 正文（对应原 C# 的 (bool, string, string) 元组） */
data class WfResult(val ok: Boolean, val title: String, val msg: String)

data class ReliefResult(val ok: Boolean, val title: String, val msg: String, val payload: Variant)

enum class SaveOrigin { Mobile, Desktop }

class ImportPlan {
    var zipPath: String = ""
    /** 源压缩包格式（zip / 7z / rar）——导入时要按它选解压器 */
    var kind: Kind = Kind.Zip
    var name: String = ""
    var prefix: String = ""
    var targetExists: Boolean = false
    var origin: SaveOrigin = SaveOrigin.Mobile
    var sourceEncryptionId: String = ""
    var needReencrypt: Boolean = false
    var needSchemaDowngrade: Boolean = false
    var needDropSaveVersion: Boolean = false
    var needDropProfileCfg: Boolean = false
    var sourceSchema: String = "?"
    val conversions: MutableList<String> = mutableListOf()
    val needsConversion: Boolean get() = conversions.isNotEmpty()
}

/**
 * 业务编排：只做 Core 调用 + 生成提示文案，完全不碰 UI。
 * ⚠ 文案严格对齐 PySide6 版（gfp.py），移植时照抄、不要改写措辞。
 */
object Workflow {
    /** 导出目录覆盖点（自测用），运行时保持 null */
    var exportDirOverride: String? = null

    /** 导出目录：内部存储根目录，方便在文件管理器里一眼看到 */
    val exportDir: String get() = exportDirOverride ?: "/storage/emulated/0"

    // ---------- 开荒减负 ----------
    fun applyRelief(p: Profile, c: CharInfo): ReliefResult {
        if (c.level > 10) {
            return ReliefResult(
                false, "等级过高",
                "角色【${c.name}（${c.roleId}）】当前 Lv.${c.level}，开荒减负仅限等级 <= 10 的新手角色。",
                Variant.nil()
            )
        }
        try {
            val payload = Save.loadPayload(p)
            val ids = Relief.kunpengIds(c.roleId)

            // ⚠ 先判"找不到该角色的套装数据"，否则 ids 为空会被下面 missing 为空误判成"已拥有"
            if (ids.isEmpty()) {
                return ReliefResult(false, "无套装数据", "找不到角色【${c.roleId}】的鲲鹏套装数据。", payload)
            }
            val owned = Relief.ownedKunpengIds(payload, c.idx)
            val missing = ids.filter { it !in owned }
            if (missing.isEmpty()) {
                return ReliefResult(
                    true, "已拥有",
                    "角色【${c.name}（${c.roleId}）】已拥有鲲鹏之征服者套装，无需减负。", payload
                )
            }
            Relief.addToInventory(payload, c.idx, missing)
            Save.savePayload(p, payload)

            // 重新读一遍，确认真的落盘了（而不是只改了内存里的对象）
            val payload2 = Save.loadPayload(p)
            return ReliefResult(
                true, "完成",
                "已给予角色【${c.name}（${c.roleId}）】${missing.size} 件鲲鹏装备到背包", payload2
            )
        } catch (e: Exception) {
            return ReliefResult(false, "写回失败", "加密回写失败：\n${e.message}", Variant.nil())
        }
    }

    // ---------- 备份 / 恢复 / 删除 ----------
    fun makeBackup(p: Profile): WfResult {
        return try {
            val dir = Backup.dir(p.name)
            File(dir).mkdirs()
            val stamp = Backup.nowStamp()
            // ⚠ 文件名只用时间戳，不带版本号（手机版存档没有 save_version）
            Archive.zipDir(p.dir, "$dir/$stamp.zip")
            val d = Backup.dtFromStamp(stamp)
            WfResult(true, "", "账号【${p.name}】已备份存档：${d?.render(Disp.YmdHms) ?: stamp}")
        } catch (e: Exception) {
            WfResult(false, "备份失败", "压缩出错：\n${e.message}")
        }
    }

    fun restore(p: Profile, b: BackupEntry): WfResult {
        return try {
            Archive.zipExtractAll(b.path, p.dir)
            WfResult(true, "", "账号【${p.name}】已恢复备份存档：${Backup.fmt(b)}")
        } catch (e: Exception) {
            WfResult(false, "恢复失败", "解压出错：\n${e.message}")
        }
    }

    fun deleteBackup(p: Profile, b: BackupEntry): WfResult {
        return try {
            File(b.path).delete()
            try {
                val bdf = File(Backup.dir(p.name))
                if (bdf.isDirectory && (bdf.listFiles()?.isEmpty() ?: false)) bdf.delete()
            } catch (_: Exception) { }
            WfResult(true, "", "账号【${p.name}】已删除备份存档：${Backup.fmt(b)}")
        } catch (e: Exception) {
            WfResult(false, "删除失败", "删除出错：\n${e.message}")
        }
    }

    // ---------- 导出 ----------
    data class ExportPrep(val ok: Boolean, val msg: String, val path: String, val exists: Boolean)

    fun prepareExport(p: Profile): ExportPrep {
        return try {
            File(exportDir).mkdirs()
            val path = "$exportDir/${p.name}.zip"
            ExportPrep(true, "", path, File(path).exists())
        } catch (e: Exception) {
            ExportPrep(false, "导出出错：\n${e.message}", "", false)
        }
    }

    fun exportSave(p: Profile, path: String): WfResult {
        return try {
            Archive.zipDir(p.dir, path)
            WfResult(true, "导出成功", "账号【${p.name}】的存档已导出到：$path")
        } catch (e: Exception) {
            WfResult(false, "导出失败", "导出出错：\n${e.message}")
        }
    }

    // ---------- 导入 ----------
    data class AnalyzeResult(val ok: Boolean, val msg: String, val plan: ImportPlan)

    /**
     * 分析导入源：解包 → 试解密 → 判定手机版/电脑版 → 列出需要的兼容转换。
     *
     * ⚠ 必须做兼容的依据（反编译的 GDScript）：手机版 local_save_manager.gd 的
     *   `if schema_version > SCHEMA_VERSION: return "存档版本 … 高于当前支持版本"`
     *   而手机版 SCHEMA_VERSION = 1、电脑版是 2 ⇒ 电脑版存档直接导入会被游戏拒绝打开；
     *   且手机版没有 profile.cfg 机制，encryption_id 恒为账号名。
     */
    fun analyze(zipPath: String, hintStem: String? = null): AnalyzeResult {
        val plan = ImportPlan()
        plan.zipPath = zipPath

        if (!File(zipPath).exists()) return AnalyzeResult(false, "找不到压缩包：$zipPath", plan)
        val kind = Archive.kindOf(zipPath)
            ?: return AnalyzeResult(
                false,
                "不支持的压缩格式：${File(zipPath).name}\n（仅支持 zip / 7z / rar）",
                plan,
            )
        plan.kind = kind

        val names = try {
            Archive.listNames(zipPath)
        } catch (e: Exception) {
            return AnalyzeResult(false, "读取压缩包失败：${e.message}", plan)
        }

        val (arcName, arcPrefix) = Archive.archiveTarget(names, File(zipPath).nameWithoutExtension)
        if (arcName == null) {
            return AnalyzeResult(false, "压缩包【${File(zipPath).name}】里没有 .dat 存档，无法导入。", plan)
        }
        // ⚠ 必须显式落成非空 String：析构出来的 arcName 是 String?，Kotlin 不对它做智能转换，
        //   直接沿用会让后面 `plan.sourceEncryptionId = usedEnc` 报 "String? but String expected"。
        val name: String = arcName
        val prefix: String = arcPrefix
        plan.name = name
        plan.prefix = prefix

        var tmp: String? = null
        try {
            tmp = Archive.extractAllToTemp(zipPath, kind)
            var dir = if (prefix.isNotEmpty()) "$tmp/${prefix.trimEnd('/')}" else tmp

            var savePath = "$dir/save.dat"
            if (!File(savePath).exists()) {
                val found = File(tmp).walkTopDown().firstOrNull { it.isFile && it.name == "save.dat" }
                    ?: File(tmp).walkTopDown().firstOrNull { it.isFile && it.name.endsWith(".dat") }
                if (found == null) return AnalyzeResult(false, "压缩包里找不到 save.dat。", plan)
                dir = found.parentFile?.path ?: tmp
                savePath = found.path
            }

            // 源 encryption_id：优先 profile.cfg（电脑版），否则账号名（手机版）
            val cfgEnc = Cfg.read("$dir/profile.cfg", "Profile", "encryption_id")
            val candidates = mutableListOf<String>()
            if (!cfgEnc.isNullOrBlank()) candidates.add(cfgEnc)
            if (name !in candidates) candidates.add(name)
            // ⚠ hintStem = 用户所选文件的原始文件名（不含扩展名）
            if (!hintStem.isNullOrBlank() && hintStem !in candidates) candidates.add(hintStem)

            var payload: Variant? = null
            var usedEnc = name
            for (enc in candidates) {
                try {
                    payload = Envelope.fromRawStream(Gdec.readEncryptedFile(savePath, Gdec.saveKey(enc))).get("payload")
                    usedEnc = enc
                    break
                } catch (_: Exception) { /* 换下一个候选 */ }
            }
            if (payload == null) {
                return AnalyzeResult(
                    false, "无法解密该存档（profile.cfg、账号名、原始文件名三种 encryption_id 都试过了）。", plan
                )
            }

            plan.sourceEncryptionId = usedEnc
            val target = "${Save.savesDir}/$name"
            plan.targetExists = File(target).isDirectory && Archive.hasDat(target)

            val sv = payload.get("schema_version")
            val schemaNo = when (sv?.kind) {
                VKind.Int -> sv.i
                VKind.Float -> sv.d.toLong()
                else -> 0L
            }
            plan.sourceSchema = if (schemaNo > 0) schemaNo.toString() else "缺失"

            val hasSaveVersion = payload.get("save_version") != null
            val hasProfileCfg = File("$dir/profile.cfg").exists()
            plan.origin = if (hasSaveVersion || schemaNo > 1 || hasProfileCfg) SaveOrigin.Desktop else SaveOrigin.Mobile

            if (plan.origin == SaveOrigin.Desktop) {
                if (schemaNo != 1L) {
                    plan.needSchemaDowngrade = true
                    plan.conversions.add("schema_version ${plan.sourceSchema} → 1（手机版只认 ≤1，否则直接拒绝打开）")
                }
                if (hasSaveVersion) {
                    plan.needDropSaveVersion = true
                    plan.conversions.add("移除 save_version（手机版没有这套机制）")
                }
                if (hasProfileCfg) {
                    plan.needDropProfileCfg = true
                    plan.conversions.add("移除 profile.cfg（手机版无此机制，且会让本工具取到错误的 encryption_id）")
                }
                if (plan.sourceEncryptionId != name) {
                    plan.needReencrypt = true
                    plan.conversions.add("换密钥重新加密：「${plan.sourceEncryptionId}」→「$name」（手机版以账号名为密钥）")
                }
            }
            return AnalyzeResult(true, "", plan)
        } catch (e: Exception) {
            return AnalyzeResult(false, "分析压缩包失败：${e.message}", plan)
        } finally {
            tmp?.let { try { File(it).deleteRecursively() } catch (_: Exception) { } }
        }
    }

    fun importSave(plan: ImportPlan): WfResult {
        val name = plan.name
        val target = "${Save.savesDir}/$name"
        var tmp: String? = null
        return try {
            // 覆盖前自动备份一次，避免手滑
            if (plan.targetExists) {
                val bdir = Backup.dir(name)
                File(bdir).mkdirs()
                Archive.zipDir(target, "$bdir/${Backup.nowStamp()}.zip")
            }

            tmp = Archive.extractAllToTemp(plan.zipPath, plan.kind)
            File(target).mkdirs()
            Archive.copyPrefix(tmp, target, plan.prefix)

            // ---------- 电脑版存档 → 手机版兼容转换 ----------
            if (plan.origin == SaveOrigin.Desktop) {
                for (extra in listOf("profile.cfg", "save.dat.pre_version_upgrade", "save.dat.bak")) {
                    val f = File(target, extra)
                    if (f.exists()) f.delete()
                }
                val savePath = "$target/save.dat"
                if (File(savePath).exists()) {
                    val env = Envelope.fromRawStream(
                        Gdec.readEncryptedFile(savePath, Gdec.saveKey(plan.sourceEncryptionId))
                    )
                    val payload = env.get("payload")
                    if (payload != null) {
                        payload.set("schema_version", Variant.ofInt(1)) // 手机版 SCHEMA_VERSION = 1
                        // ⚠ payload 字典是有序 List<Pair>，删条目要按 key 过滤重排
                        payload.dic?.let { d ->
                            val kept = d.filterNot { it.first.kind == VKind.Str && it.first.s == "save_version" }
                            d.clear()
                            d.addAll(kept)
                        }
                    }
                    // ⚠ 无论 encryption_id 是否相同都用【账号名】重写一遍
                    Gdec.writeEncryptedFile(savePath, Gdec.saveKey(name), Envelope.toRawStream(env))
                }
            }

            val note = if (plan.needsConversion)
                "\n\n（已做电脑版兼容处理：" + plan.conversions.joinToString("；") + "）" else ""
            WfResult(true, "导入成功", "账号【$name】的存档已恢复。$note")
        } catch (e: Exception) {
            WfResult(false, "导入失败", "解压出错：\n${e.message}")
        } finally {
            tmp?.let { try { File(it).deleteRecursively() } catch (_: Exception) { } }
        }
    }
}
