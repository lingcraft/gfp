package com.yierpai.savetool.core

import java.io.File
import java.util.Calendar
import java.util.Locale
import java.util.TimeZone

enum class Disp { Ymd, YmdHm, YmdHms }

data class Dt(val y: Int, val mo: Int, val d: Int, val h: Int, val mi: Int, val s: Int) {
    fun render(disp: Disp): String = when (disp) {
        Disp.Ymd -> String.format(Locale.US, "%04d-%02d-%02d", y, mo, d)
        Disp.YmdHm -> String.format(Locale.US, "%04d-%02d-%02d %02d:%02d", y, mo, d, h, mi)
        Disp.YmdHms -> String.format(Locale.US, "%04d-%02d-%02d %02d:%02d:%02d", y, mo, d, h, mi, s)
    }

    val valid: Boolean get() = y >= 1000 && mo in 1..12 && d in 1..31

    companion object {
        val MIN = Dt(0, 0, 0, 0, 0, 0)
    }
}

class BackupEntry {
    var ver: String = ""
    var t: Dt? = null
    var path: String = ""
    var note: String = ""
    var disp: Disp = Disp.Ymd
}

private data class TimeParts(val h: Int, val mi: Int, val s: Int)

data class BackupName(val ver: String, val t: Dt?, val note: String, val disp: Disp)

object Backup {
    fun dir(account: String) = "${Save.backupsDir}/$account"

    /** 中国时区 UTC+8，无夏令时 */
    fun nowStamp(): String {
        val c = Calendar.getInstance(TimeZone.getTimeZone("GMT+8"))
        return String.format(
            Locale.US, "%04d%02d%02d_%02d%02d%02d",
            c.get(Calendar.YEAR), c.get(Calendar.MONTH) + 1, c.get(Calendar.DAY_OF_MONTH),
            c.get(Calendar.HOUR_OF_DAY), c.get(Calendar.MINUTE), c.get(Calendar.SECOND)
        )
    }

    fun dtFromStamp(s: String): Dt? {
        if (s.length < 15 || s[8] != '_') return null
        fun n(i: Int, len: Int): Int = s.substring(i, i + len).toIntOrNull() ?: -1
        val d = Dt(n(0, 4), n(4, 2), n(6, 2), n(9, 2), n(11, 2), n(13, 2))
        return if (d.valid && d.h < 24 && d.mi < 60 && d.s < 60) d else null
    }

    /** 版本号去 V 后按 . 拆整数；非纯数字回退 (0) */
    private fun versionKey(ver: String): LongArray {
        val s = ver.trimStart('V', 'v')
        if (s.isEmpty()) return longArrayOf(0)
        val parts = s.split('.')
        val r = LongArray(parts.size)
        for (i in parts.indices) r[i] = parts[i].toLongOrNull() ?: return longArrayOf(0)
        return r
    }

    private fun cmpDt(a: Dt, b: Dt): Int {
        if (a.y != b.y) return a.y.compareTo(b.y)
        if (a.mo != b.mo) return a.mo.compareTo(b.mo)
        if (a.d != b.d) return a.d.compareTo(b.d)
        if (a.h != b.h) return a.h.compareTo(b.h)
        if (a.mi != b.mi) return a.mi.compareTo(b.mi)
        return a.s.compareTo(b.s)
    }

    private fun cmpKey(a: LongArray, b: LongArray): Int {
        val n = minOf(a.size, b.size)
        for (i in 0 until n) if (a[i] != b[i]) return if (a[i] < b[i]) -1 else 1
        return a.size.compareTo(b.size)
    }

    fun list(account: String): MutableList<BackupEntry> {
        val list = mutableListOf<BackupEntry>()
        val d = File(dir(account))
        if (!d.isDirectory) return list
        d.listFiles()?.forEach { f ->
            if (!f.isFile || !f.name.endsWith(".zip", ignoreCase = true)) return@forEach
            val p = parseName(f.nameWithoutExtension)
            list.add(BackupEntry().also {
                it.ver = p.ver; it.t = p.t; it.path = f.path; it.note = p.note; it.disp = p.disp
            })
        }
        list.sortWith { a, b ->
            val c = cmpKey(versionKey(b.ver), versionKey(a.ver)) // 版本号降序
            if (c != 0) c else cmpDt(b.t ?: Dt.MIN, a.t ?: Dt.MIN) // 时间降序
        }
        return list
    }

    fun fmt(e: BackupEntry): String {
        val t = e.t
            ?: return if (e.note.isEmpty()) File(e.path).nameWithoutExtension else e.note
        // ⚠ 没有版本号（手机版存档无 save_version）时不要留多余前导空格
        val b = if (e.ver.isEmpty()) t.render(e.disp) else "${e.ver} ${t.render(e.disp)}"
        return if (e.note.isEmpty()) b else "$b ${e.note}"
    }

    /**
     * 备份文件名解析，两种格式都认（分隔符为 `_` 或空格）：
     *   ① 版本{sep}日期[{sep}时间][{sep}注释]  —— 电脑版（存档有 save_version）
     *   ② 日期[{sep}时间][{sep}注释]           —— 手机版（无版本前缀）
     */
    fun parseName(stem: String): BackupName {
        fun asNote(s: String) = s.replace('_', ' ').trim()

        // ★ 优先试新格式（无版本号）：整个 stem 以 yyyyMMdd 开头
        val (usedHead, dtHead) = matchDate(stem)
        if (dtHead != null && usedHead == 8) {
            val rest0 = stem.substring(usedHead).trimStart('_', ' ')
            val (usedT0, time0) = matchTime(rest0)
            if (time0 == null) return BackupName("", dtHead, asNote(rest0), Disp.Ymd)

            val d0 = dtHead.copy(h = time0.h, mi = time0.mi, s = time0.s)
            val note0 = rest0.substring(usedT0).trimStart('_', ' ')
            return BackupName(
                "", d0, asNote(note0),
                if (time0.s == 0 && usedT0 <= 5) Disp.YmdHm else Disp.YmdHms
            )
        }

        // 旧格式：先切出版本号
        var i = 0
        while (i < stem.length && stem[i] != '_' && !stem[i].isWhitespace()) i++
        val ver = stem.substring(0, i)
        var rest = if (i < stem.length) stem.substring(i + 1) else ""
        rest = rest.trimStart('_', ' ')

        val (used, dt) = matchDate(rest)
        if (dt == null) return BackupName("", null, asNote(stem), Disp.Ymd)
        rest = rest.substring(used).trimStart('_', ' ')

        val (usedT, time) = matchTime(rest)
        if (time == null) return BackupName(ver, dt, asNote(rest), Disp.Ymd)
        rest = rest.substring(usedT).trimStart('_', ' ')
        val d = dt.copy(h = time.h, mi = time.mi, s = time.s)
        return BackupName(
            ver, d, asNote(rest),
            if (time.s == 0 && usedT <= 5) Disp.YmdHm else Disp.YmdHms
        )
    }

    private fun matchDate(s: String): Pair<Int, Dt?> {
        if (s.length >= 8 && s.substring(0, 8).all { it.isDigit() }) {
            val d = Dt(s.substring(0, 4).toInt(), s.substring(4, 6).toInt(), s.substring(6, 8).toInt(), 0, 0, 0)
            return 8 to (if (d.valid) d else null)
        }
        for (sep in charArrayOf('-', '/', '.')) {
            if (s.length < 10 || s[4] != sep || s[7] != sep) continue
            val ok = s.substring(0, 4).all { it.isDigit() } &&
                s.substring(5, 7).all { it.isDigit() } &&
                s.substring(8, 10).all { it.isDigit() }
            if (!ok) continue
            val d = Dt(s.substring(0, 4).toInt(), s.substring(5, 7).toInt(), s.substring(8, 10).toInt(), 0, 0, 0)
            if (d.valid) return 10 to d
        }
        return 0 to null
    }

    private fun matchTime(s: String): Pair<Int, TimeParts?> {
        fun dig(x: String) = x.isNotEmpty() && x.all { it.isDigit() }
        fun valid(t: TimeParts) = t.h < 24 && t.mi < 60 && t.s < 60

        if (s.length >= 8 && s[2] == ':' && s[5] == ':' &&
            dig(s.substring(0, 2)) && dig(s.substring(3, 5)) && dig(s.substring(6, 8))
        ) {
            val t = TimeParts(s.substring(0, 2).toInt(), s.substring(3, 5).toInt(), s.substring(6, 8).toInt())
            return if (valid(t)) 8 to t else 8 to null
        }
        if (s.length >= 6 && dig(s.substring(0, 6))) {
            val t = TimeParts(s.substring(0, 2).toInt(), s.substring(2, 4).toInt(), s.substring(4, 6).toInt())
            if (valid(t)) return 6 to t
        }
        if (s.length >= 5 && s[2] == ':' && dig(s.substring(0, 2)) && dig(s.substring(3, 5))) {
            val t = TimeParts(s.substring(0, 2).toInt(), s.substring(3, 5).toInt(), 0)
            if (valid(t)) return 5 to t
        }
        if (s.length >= 4 && dig(s.substring(0, 4))) {
            val t = TimeParts(s.substring(0, 2).toInt(), s.substring(2, 4).toInt(), 0)
            if (valid(t)) return 4 to t
        }
        return 0 to null
    }
}
