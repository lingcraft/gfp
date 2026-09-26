using System.Security.Cryptography;
using System.Text;

namespace Gfp.Core;

/// Godot FileAccessEncrypted 容器（GDEC）读写 + 密钥派生
public static class Gdec
{
    public const string Pepper = "d8830e54d5a743a9815967d2a7a9bc48f89de2c145ef40c3b69607f948cf413e";
    public const string AppName = "YierPai";
    public const string SaveMagic = "YIERPAI_ENCRYPTED_SAVE";
    public const long ContainerVersion = 1;

    /// key = SHA256("pepper|YierPai|encryption_id")
    public static byte[] SaveKey(string encryptionId)
    {
        using var h = SHA256.Create();
        return h.ComputeHash(Encoding.UTF8.GetBytes($"{Pepper}|{AppName}|{encryptionId}"));
    }

    public static byte[] ReadEncryptedFile(string path, byte[] key)
    {
        var blob = File.ReadAllBytes(path);
        if (blob.Length < 44) throw new Exception("文件过小，不是合法的加密存档。");
        if (blob[0] != (byte)'G' || blob[1] != (byte)'D' || blob[2] != (byte)'E' || blob[3] != (byte)'C')
            throw new Exception("magic 不匹配，不是 Godot open_encrypted 生成的存档。");

        var md5Expected = Cut(blob, 4, 20);
        long length = (long)BitConverter.ToUInt64(blob, 20);
        var iv = Cut(blob, 28, 44);
        int padded = (int)((length + 15) / 16 * 16);
        var ct = CutToEnd(blob, 44);
        if (ct.Length < padded) throw new Exception("加密数据不完整。");

        var plain = Cut(AesCfb(Cut(ct, 0, padded), key, iv, false), 0, (int)length);
        if (!BytesEqual(MD5.Create().ComputeHash(plain), md5Expected))
            throw new Exception("MD5 校验失败：解密密钥可能已变化（例如档案 encryption_id 改变）或文件损坏。");
        return plain;
    }

    public static void WriteEncryptedFile(string path, byte[] key, byte[] raw)
    {
        var iv = new byte[16];
        using (var rng = RandomNumberGenerator.Create()) rng.GetBytes(iv);
        int padded = (raw.Length + 15) / 16 * 16;
        var data = new byte[padded];
        Array.Copy(raw, data, raw.Length);
        var ct = AesCfb(data, key, iv, true);
        var digest = MD5.Create().ComputeHash(raw);

        var outb = new byte[44 + ct.Length];
        Encoding.ASCII.GetBytes("GDEC").CopyTo(outb, 0);
        digest.CopyTo(outb, 4);
        BitConverter.GetBytes((ulong)raw.Length).CopyTo(outb, 20);
        iv.CopyTo(outb, 28);
        ct.CopyTo(outb, 44);
        File.WriteAllBytes(path, outb);
    }

    /// AES-256-CFB，段长 128 位（整块反馈）。
    /// 注意：.NET Framework 的 Aes CFB 仅支持 8 位反馈，设 FeedbackSize=128 会抛异常；
    /// 故用 ECB 基元手动实现 CFB128，保证在 net48 / net10 上行为一致，且与 Godot 的 segment_size=128 对齐。
    private static byte[] AesCfb(byte[] data, byte[] key, byte[] iv, bool encrypt)
    {
        using var aes = Aes.Create();
        aes.KeySize = 256;
        aes.Mode = CipherMode.ECB;
        aes.Padding = PaddingMode.None;
        aes.Key = key;
        using var e = aes.CreateEncryptor();

        const int bs = 16;
        var reg = new byte[bs];
        Array.Copy(iv, 0, reg, 0, bs);
        var ks = new byte[bs];
        var outb = new byte[data.Length];
        for (int i = 0; i < data.Length; i += bs)
        {
            e.TransformBlock(reg, 0, bs, ks, 0);
            int len = Math.Min(bs, data.Length - i);
            for (int j = 0; j < len; j++)
            {
                byte ct = (byte)(data[i + j] ^ ks[j]);
                outb[i + j] = ct;
                // CFB 反馈：寄存器以密文回填（加密时密文=outb，解密时密文=输入 data）
                reg[j] = encrypt ? ct : data[i + j];
            }
        }
        return outb;
    }

    private static byte[] Cut(byte[] s, int start, int end)
    {
        var r = new byte[end - start];
        Array.Copy(s, start, r, 0, end - start);
        return r;
    }
    private static byte[] CutToEnd(byte[] s, int start) => Cut(s, start, s.Length);
    private static bool BytesEqual(byte[] a, byte[] b)
    {
        if (a.Length != b.Length) return false;
        for (int i = 0; i < a.Length; i++) if (a[i] != b[i]) return false;
        return true;
    }
}
