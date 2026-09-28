package com.yierpai.savetool.core

import com.github.junrar.Junrar
import org.apache.commons.compress.archivers.sevenz.SevenZArchiveEntry
import org.apache.commons.compress.archivers.sevenz.SevenZFile
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipFile
import java.util.zip.ZipOutputStream

enum class Kind { Zip, SevenZ, Rar }

/**
 * 压缩包操作。三种格式都支持**读取**（导入用）：
 * - `zip` → JDK 自带 `java.util.zip`（**唯一支持写出**的格式：备份/导出只产出 zip）；
 * - `7z`  → Apache Commons Compress 的 `SevenZFile`（LZMA/LZMA2 由 `org.tukaani:xz` 提供）；
 * - `rar` → junrar（纯 JVM，RAR4/RAR5 都支持，`FileHeader.isRar5Container()` 可判）。
 * ⚠ 三者都会用到 `java.nio.file` ⇒ 模块 `minSdk` 必须是 **26**（Android 8.0）。
 * ⚠ 解压一律带 **zip-slip 防护**（落盘路径必须落在目标目录内）。
 * ⚠ 带密码的包：三种都不支持（会以"解压失败"报出）。
 */
object Archive {
    /**
     * 判断压缩格式：**先按文件头字节嗅探**（文件被改名、或没有扩展名时也能认对），
     * 认不出来再退回扩展名。返回 null = 三种都不像。
     */
    fun kindOf(path: String): Kind? {
        sniff(path)?.let { return it }
        return when (path.substringAfterLast('.', "").lowercase()) {
            "zip" -> Kind.Zip
            "7z" -> Kind.SevenZ
            "rar" -> Kind.Rar
            else -> null
        }
    }

    /** 读前 8 字节判类型：zip = `PK\x03\x04`（空包 `PK\x05\x06`）、7z = `37 7A BC AF 27 1C`、rar = `Rar!…` */
    private fun sniff(path: String): Kind? = try {
        val b = ByteArray(8)
        val n = File(path).inputStream().use { it.read(b) }
        val u = { i: Int -> b[i].toInt() and 0xFF }
        when {
            n >= 4 && u(0) == 0x50 && u(1) == 0x4B && (u(2) == 0x03 || u(2) == 0x05 || u(2) == 0x07) -> Kind.Zip
            n >= 6 && u(0) == 0x37 && u(1) == 0x7A && u(2) == 0xBC && u(3) == 0xAF && u(4) == 0x27 && u(5) == 0x1C -> Kind.SevenZ
            n >= 7 && u(0) == 0x52 && u(1) == 0x61 && u(2) == 0x72 && u(3) == 0x21 && u(4) == 0x1A && u(5) == 0x07 -> Kind.Rar
            else -> null
        }
    } catch (_: Exception) {
        null
    }

    fun hasDat(dir: String): Boolean {
        val d = File(dir)
        if (!d.isDirectory) return false
        return d.listFiles()?.any { it.isFile && it.name.endsWith(".dat", ignoreCase = true) } ?: false
    }

    /** 备份：只打包目录下的一层文件 */
    fun zipDir(dir: String, outPath: String) {
        val f = File(outPath)
        if (f.exists()) f.delete()
        ZipOutputStream(f.outputStream().buffered()).use { zos ->
            File(dir).listFiles()?.sortedBy { it.name }?.forEach { file ->
                if (!file.isFile) return@forEach
                zos.putNextEntry(ZipEntry(file.name))
                file.inputStream().use { it.copyTo(zos) }
                zos.closeEntry()
            }
        }
    }

    /** 落盘路径必须在目标目录内（防 zip-slip） */
    private fun inside(dirCanon: String, f: File): Boolean {
        val p = f.canonicalPath
        return p == dirCanon || p.startsWith(dirCanon + File.separator)
    }

    /** 覆盖式全解压到 target（先清空目录） */
    fun zipExtractAll(zipPath: String, target: String) {
        val t = File(target)
        t.mkdirs()
        t.listFiles()?.forEach { it.deleteRecursively() }
        val tCanon = t.canonicalPath
        ZipFile(zipPath).use { zf ->
            zf.entries().asSequence().forEach { e ->
                val dst = File(t, e.name)
                // 防 zip-slip：解压路径必须落在目标目录内
                if (!inside(tCanon, dst)) return@forEach
                if (e.isDirectory) {
                    dst.mkdirs()
                    return@forEach
                }
                dst.parentFile?.mkdirs()
                zf.getInputStream(e).use { ins -> dst.outputStream().use { outs -> ins.copyTo(outs) } }
            }
        }
    }

    /** 7z 全解压（commons-compress；LZMA/LZMA2 走 xz） */
    private fun sevenZExtractAll(src: String, target: String) {
        val t = File(target)
        t.mkdirs()
        val tCanon = t.canonicalPath
        // ⚠ 用 Builder（1.26+ 的推荐入口；旧构造器已标记废弃）
        SevenZFile.builder().setFile(File(src)).get().use { sz ->
            while (true) {
                val e: SevenZArchiveEntry = sz.nextEntry ?: break
                val dst = File(t, e.name)
                if (!inside(tCanon, dst)) continue          // 防 zip-slip
                if (e.isDirectory) {
                    dst.mkdirs()
                    continue
                }
                dst.parentFile?.mkdirs()
                sz.getInputStream(e).use { ins -> dst.outputStream().use { outs -> ins.copyTo(outs) } }
            }
        }
    }

    /**
     * rar 全解压（junrar）。
     * ⚠ junrar 是整包解压 API（`Junrar.extract` 返回落盘的文件列表）——
     *   所以路径防护只能**事后校验**：一旦发现落到了目标目录外，立刻删掉整个临时目录并报错。
     */
    private fun rarExtractAll(src: String, target: String) {
        val t = File(target)
        t.mkdirs()
        val tCanon = t.canonicalPath
        val written = Junrar.extract(File(src), t)
        val escaped = written.firstOrNull { !inside(tCanon, it) }
        if (escaped != null) {
            try { t.deleteRecursively() } catch (_: Exception) { }
            error("压缩包内含非法路径（${escaped.name}），已中止")
        }
    }

    /** 解压到临时目录，返回路径（调用方负责删除） */
    fun extractAllToTemp(src: String, kind: Kind): String {
        val base = uniqueTemp()
        File(base).mkdirs()
        try {
            when (kind) {
                Kind.Zip -> zipExtractAll(src, base)
                Kind.SevenZ -> sevenZExtractAll(src, base)
                Kind.Rar -> rarExtractAll(src, base)
            }
            return base
        } catch (e: Exception) {
            try { File(base).deleteRecursively() } catch (_: Exception) { }
            throw IllegalStateException("解压失败：${e.message}")
        }
    }

    /** 规范化 entry.Key（统一 '/'、去首 '/'；目录项返回 ""） */
    private fun normKey(key: String?): String {
        val rel = (key ?: "").replace('\\', '/').trimStart('/')
        return if (rel.endsWith("/")) "" else rel
    }

    /** 按「包内顺序」列出压缩包内文件相对路径（导入前推导账号名/前缀用）；zip / 7z / rar 都支持 */
    fun listNames(src: String): MutableList<String> {
        val kind = kindOf(src) ?: error("不支持的压缩格式：${File(src).name}（仅支持 zip / 7z / rar）")
        val names = mutableListOf<String>()
        fun add(raw: String?) {
            val k = normKey(raw)
            if (k.isNotEmpty()) names.add(k)
        }
        when (kind) {
            Kind.Zip -> ZipFile(src).use { zf -> zf.entries().asSequence().forEach { add(it.name) } }
            Kind.SevenZ -> SevenZFile.builder().setFile(File(src)).get().use { sz ->
                while (true) {
                    val e = sz.nextEntry ?: break
                    add(e.name)
                }
            }
            Kind.Rar -> Junrar.getContentsDescription(File(src)).forEach { add(it.path) }
        }
        return names
    }

    fun collectFiles(root: String): MutableList<String> {
        val list = mutableListOf<String>()
        File(root).walkTopDown().filter { it.isFile }.forEach { list.add(relPath(root, it.path)) }
        return list
    }

    /** 找首个 .dat：在根目录→账号名取压缩包名；在子目录→取该目录名，且只解压该目录内容 */
    fun archiveTarget(names: List<String>, arcStem: String): Pair<String?, String> {
        val dat = names.firstOrNull { it.endsWith(".dat", ignoreCase = true) } ?: return null to ""
        val slash = dat.lastIndexOf('/')
        if (slash < 0) return arcStem to ""
        val dir = dat.substring(0, slash)
        val name = if (dir.contains("/")) dir.substring(dir.lastIndexOf('/') + 1) else dir
        return name to "$dir/"
    }

    fun copyPrefix(tmp: String, target: String, prefix: String) {
        for (rel in collectFiles(tmp)) {
            if (prefix.isNotEmpty() && !rel.startsWith(prefix)) continue
            val rel2 = if (prefix.isNotEmpty()) rel.substring(prefix.length) else rel
            if (rel2.isEmpty()) continue
            val dst = File(target, rel2)
            dst.parentFile?.mkdirs()
            File(tmp, rel).copyTo(dst, overwrite = true)
        }
    }

    /** 相对路径（以 / 分隔） */
    private fun relPath(root: String, path: String): String {
        val r = root.trimEnd('/', '\\')
        val rel = if (path.startsWith(r, ignoreCase = true)) path.substring(r.length).trimStart('/', '\\') else path
        return rel.replace('\\', '/')
    }

    private fun uniqueTemp(): String {
        val base = AppCtx.cacheDir.ifEmpty { System.getProperty("java.io.tmpdir") ?: "/data/local/tmp" }
        return "$base/gfp_${System.nanoTime()}"
    }
}
