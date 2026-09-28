package com.yierpai.savetool.core

import java.io.File

class Profile {
    var name: String = ""
    var dir: String = ""
    val saveFile: String get() = "$dir/save.dat"
    val profileCfg: String get() = "$dir/profile.cfg"

    /** profile.cfg 的 [Profile] encryption_id，空则回退账号名 */
    fun encryptionId(): String {
        val v = Cfg.read(profileCfg, "Profile", "encryption_id")
        return if (v.isNullOrEmpty()) name else v
    }

    fun saveKey(): ByteArray = Gdec.saveKey(encryptionId())
}

/** Godot ConfigFile（INI）读取：逐行 Trim、[section]、行内按第一个 = 分割、值去首尾引号 */
object Cfg {
    fun read(path: String, section: String, key: String): String? {
        val text = try {
            File(path).readText()
        } catch (_: Exception) {
            return null
        }
        var cur = ""
        for (rawLine in text.split('\n')) {
            val line = rawLine.trim()
            if (line.isEmpty() || line.startsWith(";") || line.startsWith("#")) continue
            if (line.startsWith("[") && line.endsWith("]")) {
                cur = line.substring(1, line.length - 1).trim()
                continue
            }
            if (cur != section) continue
            val eq = line.indexOf('=')
            if (eq < 0) continue
            if (line.substring(0, eq).trim() != key) continue
            var v = line.substring(eq + 1).trim()
            if (v.length >= 2 &&
                ((v.first() == '"' && v.last() == '"') || (v.first() == '\'' && v.last() == '\''))
            ) v = v.substring(1, v.length - 1)
            return v
        }
        return null
    }
}

object Save {
    /**
     * 存档根目录。Android 侧在 MainActivity 启动时设为 `/storage/emulated/0/YierPai`
     * （= 游戏 SAVE_ROOT 的父目录）。
     * ⚠ 存档目录名就是密钥的一部分，工具绝不能重命名存档目录。
     */
    var dataDirOverride: String? = null

    val dataDir: String get() = dataDirOverride ?: "/storage/emulated/0/YierPai"
    val savesDir: String get() = "$dataDir/saves"
    val backupsDir: String get() = "$dataDir/backups"

    fun listProfiles(): MutableList<Profile> {
        val list = mutableListOf<Profile>()
        try {
            val dir = File(savesDir)
            if (!dir.isDirectory) return list
            dir.listFiles()?.forEach { d ->
                if (!d.isDirectory) return@forEach
                val name = d.name
                // ⚠ 跳过"名字已损坏"的目录（Linux 原始字节被截断 → 解码出 U+FFFD 替换字符）。
                //   里面可能装着完整存档，所以只从列表里排除 + 打日志，绝不删除。
                if (!isDisplayableName(name)) {
                    println("[GFP] 跳过名称损坏的存档目录（不会被删除）：${d.path}")
                    return@forEach
                }
                // 跳过没有 save.dat 的目录（多为建到一半被中断的残留）
                if (!File(d, "save.dat").exists()) return@forEach
                list.add(Profile().also { it.name = name; it.dir = d.path })
            }
        } catch (_: Exception) {
            return list
        }
        list.sortWith(compareBy { it.name }) // 序数排序，与 C# string.CompareOrdinal 等价
        return list
    }

    /** 既不含 UTF-8 解码失败的替换字符，也不含控制字符 */
    private fun isDisplayableName(name: String): Boolean {
        if (name.isEmpty()) return false
        for (ch in name) if (ch == '\uFFFD' || Character.isISOControl(ch)) return false
        return true
    }

    /** 当前游戏账号（读 login_credentials.cfg），用于把它提到列表第一位 */
    fun activeProfileName(): String? =
        Cfg.read("$dataDir/login_credentials.cfg", "Login", "profile_name")

    fun find(name: String): Profile? = listProfiles().firstOrNull { it.name == name }

    fun loadPayload(p: Profile): Variant {
        val raw = Gdec.readEncryptedFile(p.saveFile, p.saveKey())
        val env = Envelope.fromRawStream(raw)
        return env.get("payload") ?: Variant.nil()
    }

    fun savePayload(p: Profile, payload: Variant) {
        val d = Variant.ofDict()
        d.set("magic", Variant.ofStr(Gdec.SAVE_MAGIC))
        d.set("container_version", Variant.ofInt(Gdec.CONTAINER_VERSION))
        d.set("payload", payload)
        val raw = Envelope.toRawStream(d)
        Gdec.writeEncryptedFile(p.saveFile, p.saveKey(), raw)
    }
}
