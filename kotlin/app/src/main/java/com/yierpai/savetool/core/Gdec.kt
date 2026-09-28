package com.yierpai.savetool.core

import java.io.File
import java.security.MessageDigest
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.spec.SecretKeySpec

/**
 * Godot `FileAccess.open_encrypted` 容器（GDEC）读写 + 密钥派生。
 *
 * 字节布局（照抄 C# `wpf/Core/Gdec.cs`，已与 Java 侧双向对拍通过）：
 * ```
 * 偏移  长度  内容
 * 0     4     "GDEC"
 * 4     16    MD5(【未补齐】的明文)
 * 20    8     明文长度，u64 小端
 * 28    16    IV（加密时随机生成）
 * 44    N     AES-256-CFB128 密文（明文先补齐到 16 的倍数）
 * ```
 */
object Gdec {
    const val PEPPER = "d8830e54d5a743a9815967d2a7a9bc48f89de2c145ef40c3b69607f948cf413e"
    const val APP_NAME = "YierPai"
    const val SAVE_MAGIC = "YIERPAI_ENCRYPTED_SAVE"
    const val CONTAINER_VERSION = 1L

    private const val BLOCK = 16

    /** key = SHA256("pepper|YierPai|encryption_id")（UTF-8 拼接，`|` 分隔） */
    fun saveKey(encryptionId: String): ByteArray =
        MessageDigest.getInstance("SHA-256")
            .digest((PEPPER + "|" + APP_NAME + "|" + encryptionId).toByteArray(Charsets.UTF_8))

    fun readEncryptedFile(path: String, key: ByteArray): ByteArray {
        val blob = File(path).readBytes()
        if (blob.size < 44) error("文件过小，不是合法的加密存档。")
        if (blob[0] != 'G'.code.toByte() || blob[1] != 'D'.code.toByte() ||
            blob[2] != 'E'.code.toByte() || blob[3] != 'C'.code.toByte()
        ) error("magic 不匹配，不是 Godot open_encrypted 生成的存档。")

        val md5Expected = blob.copyOfRange(4, 20)
        var length = 0L
        for (i in 7 downTo 0) length = (length shl 8) or (blob[20 + i].toLong() and 0xFF)
        val iv = blob.copyOfRange(28, 44)
        val ct = blob.copyOfRange(44, blob.size)
        val padded = ((length + 15) / 16 * 16).toInt()
        if (ct.size < padded) error("加密数据不完整。")

        val plain = aesCfb(ct.copyOfRange(0, padded), key, iv, false).copyOfRange(0, length.toInt())
        if (!MessageDigest.getInstance("MD5").digest(plain).contentEquals(md5Expected)) {
            error("MD5 校验失败：解密密钥可能已变化（例如档案 encryption_id 改变）或文件损坏。")
        }
        return plain
    }

    fun writeEncryptedFile(path: String, key: ByteArray, raw: ByteArray) {
        val iv = ByteArray(BLOCK).also { SecureRandom().nextBytes(it) }
        val padded = (raw.size + 15) / 16 * 16
        val data = ByteArray(padded)
        System.arraycopy(raw, 0, data, 0, raw.size)
        val ct = aesCfb(data, key, iv, true)
        val digest = MessageDigest.getInstance("MD5").digest(raw)

        val out = ByteArray(44 + ct.size)
        System.arraycopy("GDEC".toByteArray(Charsets.US_ASCII), 0, out, 0, 4)
        System.arraycopy(digest, 0, out, 4, 16)
        for (i in 0 until 8) out[20 + i] = ((raw.size.toLong() ushr (8 * i)) and 0xFF).toByte()
        System.arraycopy(iv, 0, out, 28, 16)
        System.arraycopy(ct, 0, out, 44, ct.size)
        File(path).writeBytes(out)
    }

    /**
     * AES-256-CFB，段长 128 位（整块反馈）。
     *
     * ⚠ 用手写实现（ECB 基元 + 反馈寄存器）而不是 `Cipher.getInstance("AES/CFB/NoPadding")`：
     *   后者在 JDK17/SunJCE 上实测就是 CFB128，但 Android 跑的是 Conscrypt/BoringSSL，
     *   未在真机实测过。手写版与 C# `AesCfb` 逐字节一致（已在 JVM 对拍验证），且不依赖 provider 行为。
     */
    private fun aesCfb(data: ByteArray, key: ByteArray, iv: ByteArray, encrypt: Boolean): ByteArray {
        val ecb = Cipher.getInstance("AES/ECB/NoPadding")
        ecb.init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"))
        val reg = iv.copyOf(BLOCK)
        val out = ByteArray(data.size)
        var i = 0
        while (i < data.size) {
            val ks = ecb.doFinal(reg)
            val len = minOf(BLOCK, data.size - i)
            for (j in 0 until len) {
                val ct = (data[i + j].toInt() xor ks[j].toInt()).toByte()
                out[i + j] = ct
                // CFB 反馈：寄存器以密文回填（加密时密文=输出，解密时密文=输入）
                reg[j] = if (encrypt) ct else data[i + j]
            }
            i += BLOCK
        }
        return out
    }
}
