package com.yierpai.savetool.core

import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Locale
import kotlin.math.abs
import kotlin.math.floor

enum class VKind { Nil, Bool, Int, Float, Str, Array, Dict }

/**
 * Godot Variant。
 *
 * ⚠ 字典**必须保序**（对应 Godot 的 indexmap）⇒ 用 `MutableList<Pair<Variant, Variant>>`，
 *   删条目要按 key 过滤重排，绝不能用无序 Map。
 */
class Variant {
    var kind: VKind = VKind.Nil
    var b: Boolean = false
    var i: Long = 0L
    var d: Double = 0.0
    var s: String = ""
    var arr: MutableList<Variant>? = null
    var dic: MutableList<Pair<Variant, Variant>>? = null

    fun get(key: String): Variant? {
        if (kind != VKind.Dict) return null
        dic?.forEach { (k, v) -> if (k.kind == VKind.Str && k.s == key) return v }
        return null
    }

    fun set(key: String, v: Variant) {
        if (kind != VKind.Dict) { kind = VKind.Dict; dic = mutableListOf() }
        val d = dic!!
        for (idx in d.indices) {
            val k = d[idx].first
            if (k.kind == VKind.Str && k.s == key) { d[idx] = Variant.ofStr(key) to v; return }
        }
        d.add(Variant.ofStr(key) to v)
    }

    fun asArray(): MutableList<Variant> =
        if (kind == VKind.Array && arr != null) arr!! else mutableListOf()

    fun asString(): String = when (kind) {
        VKind.Nil -> "null"
        VKind.Bool -> if (b) "true" else "false"
        VKind.Int -> i.toString()
        VKind.Float -> fmt(d)
        VKind.Str -> s
        else -> ""
    }

    companion object {
        fun nil() = Variant()
        fun ofBool(v: Boolean) = Variant().also { it.kind = VKind.Bool; it.b = v }
        fun ofInt(v: Long) = Variant().also { it.kind = VKind.Int; it.i = v }
        fun ofFloat(v: Double) = Variant().also { it.kind = VKind.Float; it.d = v }
        fun ofStr(v: String) = Variant().also { it.kind = VKind.Str; it.s = v }
        fun ofArray(v: MutableList<Variant>) = Variant().also { it.kind = VKind.Array; it.arr = v }
        fun ofDict() = Variant().also { it.kind = VKind.Dict; it.dic = mutableListOf() }

        /** 与 Python 版对齐：整数值且不太大时补一位小数 */
        fun fmt(f: Double): String =
            if (!f.isNaN() && !f.isInfinite() && f == floor(f) && abs(f) < 1e16)
                String.format(Locale.US, "%.1f", f)
            else f.toString()
    }
}

/** Variant 二进制读取器（全小端）。 */
class VReader(private val b: ByteArray) {
    private var p = 0

    fun take(n: Int): ByteArray {
        if (n < 0 || p + n > b.size) error("Variant 流不完整（数据被截断）。")
        val r = b.copyOfRange(p, p + n)
        p += n
        return r
    }

    private fun leInt(): Int = ByteBuffer.wrap(take(4)).order(ByteOrder.LITTLE_ENDIAN).int
    private fun leLong(): Long = ByteBuffer.wrap(take(8)).order(ByteOrder.LITTLE_ENDIAN).long

    fun u32(): Long = leInt().toLong() and 0xFFFFFFFFL
    fun i32(): Int = leInt()
    fun i64(): Long = leLong()
    fun f32(): Float = ByteBuffer.wrap(take(4)).order(ByteOrder.LITTLE_ENDIAN).float
    fun f64(): Double = ByteBuffer.wrap(take(8)).order(ByteOrder.LITTLE_ENDIAN).double

    fun str(): String {
        val n = u32().toInt()
        val s = String(take(n), Charsets.UTF_8)
        val pad = (4 - n % 4) % 4
        if (pad > 0) take(pad)
        return s
    }

    private fun containerType(kind: Long) {
        when (kind) {
            1L -> u32()
            2L, 3L -> str()
            0L -> {}
            else -> error("非法的容器类型。")
        }
    }

    fun value(depth: Int): Variant {
        if (depth > 1024) error("Variant 嵌套过深。")
        val h = u32()
        val t = (h and 0xFF).toInt()
        val is64 = (h and (1L shl 16)) != 0L
        return when (t) {
            0 -> Variant.nil()
            1 -> Variant.ofBool(u32() != 0L)
            2 -> Variant.ofInt(if (is64) i64() else i32().toLong())
            3 -> Variant.ofFloat(if (is64) f64() else f32().toDouble())
            4, 21 -> Variant.ofStr(str())
            27 -> {
                containerType((h shr 16) and 3L)
                containerType((h shr 18) and 3L)
                val n = (u32() and 0x7FFFFFFFL).toInt()
                val d = Variant.ofDict()
                repeat(n) { d.dic!!.add(value(depth + 1) to value(depth + 1)) }
                d
            }
            28 -> {
                containerType((h shr 16) and 3L)
                val n = (u32() and 0x7FFFFFFFL).toInt()
                val a = ArrayList<Variant>(n)
                repeat(n) { a.add(value(depth + 1)) }
                Variant.ofArray(a)
            }
            29 -> {
                val n = u32().toInt()
                val a = ArrayList<Variant>(n)
                take(n).forEach { a.add(Variant.ofInt(it.toLong() and 0xFF)) }
                val pad = (4 - n % 4) % 4
                if (pad > 0) take(pad)
                Variant.ofArray(a)
            }
            30 -> {
                val n = u32().toInt()
                val a = ArrayList<Variant>(n)
                repeat(n) { a.add(Variant.ofInt(i32().toLong())) }
                Variant.ofArray(a)
            }
            31 -> {
                val n = u32().toInt()
                val a = ArrayList<Variant>(n)
                repeat(n) { a.add(Variant.ofInt(i64())) }
                Variant.ofArray(a)
            }
            32, 33 -> {
                val d64 = t == 33
                val n = u32().toInt()
                val a = ArrayList<Variant>(n)
                repeat(n) { a.add(Variant.ofFloat(if (d64) f64() else f32().toDouble())) }
                Variant.ofArray(a)
            }
            34 -> {
                val n = u32().toInt()
                val a = ArrayList<Variant>(n)
                repeat(n) { a.add(Variant.ofStr(str())) }
                Variant.ofArray(a)
            }
            23 -> Variant.ofInt(i64())
            24 -> {
                if ((h and (1L shl 16)) != 0L) {
                    val id = i64()
                    if (id == 0L) Variant.nil()
                    else Variant.ofDict().also { it.set("__object_id", Variant.ofInt(id)) }
                } else error("完整对象编码在不允许对象的环境中不受支持。")
            }
            25 -> Variant.nil() // 与原实现一致：不消费字节
            26 -> {
                val name = str()
                val id = i64()
                Variant.ofDict().also {
                    it.set("__signal", Variant.ofStr(name))
                    it.set("__object_id", Variant.ofInt(id))
                }
            }
            else -> {
                // 数学类型（向量/矩形/矩阵/颜色等）：按分量个数读 float（COLOR 固定 f32）
                val comp = when (t) {
                    5, 6, 35 -> 2
                    9, 10, 36 -> 3
                    7, 8, 12, 13, 14, 15, 20, 37, 38 -> 4
                    11, 16 -> 6
                    17 -> 9
                    18 -> 12
                    19 -> 16
                    else -> 0
                }
                if (comp == 0) error("不支持的 Variant 类型：$t")
                val d64 = (t != 20 && t != 37) && is64
                val a = ArrayList<Variant>(comp)
                repeat(comp) { a.add(Variant.ofFloat(if (d64) f64() else f32().toDouble())) }
                Variant.ofArray(a)
            }
        }
    }
}

/** Variant 二进制写入器（全小端）。 */
class VWriter {
    private val out = ByteArrayOutputStream()

    fun bytes(): ByteArray = out.toByteArray()

    private fun le32(v: Int) {
        out.write(v and 0xFF)
        out.write((v ushr 8) and 0xFF)
        out.write((v ushr 16) and 0xFF)
        out.write((v ushr 24) and 0xFF)
    }

    private fun le64(v: Long) {
        for (i in 0 until 8) out.write(((v ushr (8 * i)) and 0xFF).toInt())
    }

    fun u32(v: Int) = le32(v)
    fun u64(v: Long) = le64(v)
    fun f32(v: Float) = le32(java.lang.Float.floatToIntBits(v))
    fun f64(v: Double) = le64(java.lang.Double.doubleToLongBits(v))

    fun str(s: String) {
        val b = s.toByteArray(Charsets.UTF_8)
        u32(b.size)
        out.write(b)
        val pad = (4 - b.size % 4) % 4
        repeat(pad) { out.write(0) }
    }

    fun value(v: Variant) {
        when (v.kind) {
            VKind.Nil -> u32(0)
            VKind.Bool -> { u32(1); u32(if (v.b) 1 else 0) }
            VKind.Int -> {
                val big = v.i < Int.MIN_VALUE || v.i > Int.MAX_VALUE
                u32(2 or (if (big) 1 shl 16 else 0))
                if (big) le64(v.i) else le32(v.i.toInt())
            }
            VKind.Float -> {
                val f = v.d.toFloat()
                val big = f.toDouble() != v.d
                u32(3 or (if (big) 1 shl 16 else 0))
                if (big) f64(v.d) else f32(f)
            }
            VKind.Str -> { u32(4); str(v.s) }
            VKind.Array -> {
                val a = v.arr ?: mutableListOf()
                u32(28); u32(a.size)
                a.forEach { value(it) }
            }
            VKind.Dict -> {
                val d = v.dic ?: mutableListOf()
                u32(27); u32(d.size)
                d.forEach { (k, vv) -> u32(4); str(k.s); value(vv) }
            }
        }
    }
}

/** 存档存储流 = `[u32 长度][Variant 字节]` */
object Envelope {
    fun toRawStream(v: Variant): ByteArray {
        val w = VWriter()
        w.value(v)
        val body = w.bytes()
        val out = ByteArray(4 + body.size)
        for (i in 0 until 4) out[i] = ((body.size ushr (8 * i)) and 0xFF).toByte()
        System.arraycopy(body, 0, out, 4, body.size)
        return out
    }

    fun fromRawStream(raw: ByteArray): Variant {
        val r = VReader(raw)
        val n = r.u32().toInt()
        val body = r.take(n)
        return VReader(body).value(0)
    }
}
