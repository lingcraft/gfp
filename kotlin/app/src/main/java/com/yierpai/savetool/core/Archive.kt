package com.yierpai.savetool.core

import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipFile
import java.util.zip.ZipOutputStream

enum class Kind { Zip, SevenZ, Rar }

/**
 * 压缩包操作。移动端只支持 zip（走 java.util.zip）；
 * 7z / rar 明确提示"请先在电脑上转成 zip"（原 Avalonia 版的 SevenZipStub 也是这个行为）。
 */
object Archive {
    fun kindOf(path: String): Kind? = when (path.substringAfterLast('.', "").lowercase()) {
        "zip" -> Kind.Zip
        "7z" -> Kind.SevenZ
        "rar" -> Kind.Rar
        else -> null
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
                if (dst.canonicalPath != tCanon && !dst.canonicalPath.startsWith(tCanon + File.separator)) return@forEach
                if (e.isDirectory) {
                    dst.mkdirs()
                    return@forEach
                }
                dst.parentFile?.mkdirs()
                zf.getInputStream(e).use { ins -> dst.outputStream().use { outs -> ins.copyTo(outs) } }
            }
        }
    }

    /** 解压到临时目录，返回路径（调用方负责删除） */
    fun extractAllToTemp(src: String, kind: Kind): String {
        val base = uniqueTemp()
        File(base).mkdirs()
        try {
            when (kind) {
                Kind.Zip -> zipExtractAll(src, base)
                else -> error("移动端只支持 zip 格式，7z / rar 请先在电脑上转成 zip。")
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

    /** 按「包内顺序」列出压缩包内文件相对路径（导入前推导账号名/前缀用） */
    fun listNames(src: String): MutableList<String> {
        if (kindOf(src) != Kind.Zip) error("移动端只支持 zip 格式，7z / rar 请先在电脑上转成 zip。")
        val zipped = mutableListOf<String>()
        ZipFile(src).use { zf ->
            zf.entries().asSequence().forEach {
                val k = normKey(it.name)
                if (k.isNotEmpty()) zipped.add(k)
            }
        }
        return zipped
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
