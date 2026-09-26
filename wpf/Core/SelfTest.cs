using System.Text;

namespace Gfp.Core;

// 移植自检：Variant 编解码往返 + 真实存档解密/回写一致性
public static class SelfTest
{
    public static void Run()
    {
        var outp = new StringBuilder();
        try
        {
            // 1) Variant 往返
            var inner = Variant.OfDict();
            inner.Set("id", Variant.OfFloat(100249.0));
            inner.Set("uid", Variant.OfStr("13581436926_2385082135"));
            var root = Variant.OfDict();
            root.Set("magic", Variant.OfStr(Gdec.SaveMagic));
            root.Set("container_version", Variant.OfInt(1));
            root.Set("flag", Variant.OfBool(true));
            root.Set("big", Variant.OfInt(9_000_000_000));
            root.Set("pi", Variant.OfFloat(3.14159));
            root.Set("list", Variant.OfArray(new() { Variant.OfInt(1), Variant.Nil(), Variant.OfStr("中文") }));
            root.Set("equipment", Variant.OfArray(new() { inner }));
            var back = Envelope.FromRawStream(Envelope.ToRawStream(root));
            outp.AppendLine($"Variant 往返: {(back.Dic!.Count == root.Dic!.Count ? "OK" : "不一致")}");
            outp.AppendLine($"  big/int: {back.Get("big")!.I}, 字符串: {back.Get("list")!.Arr![2].S}");

            // 1.5) GDEC 加解密往返（不依赖真实存档，验证 AES-CFB128 在各框架一致）
            var gkey = Gdec.SaveKey("__selftest__");
            var grows = Envelope.ToRawStream(root);
            var gtmp = Path.Combine(Path.GetTempPath(), "gfp_cs_gdec.dat");
            Gdec.WriteEncryptedFile(gtmp, gkey, grows);
            var gplain = Gdec.ReadEncryptedFile(gtmp, gkey);
            File.Delete(gtmp);
            var gback = Envelope.FromRawStream(gplain);
            outp.AppendLine($"GDEC 往返: {(gback.Dic!.Count == root.Dic!.Count ? "OK" : "不一致")}");

            // 2) 真实存档
            var p = Save.ListProfiles().FirstOrDefault(x => File.Exists(x.SaveFile));
            if (p is null)
            {
                outp.AppendLine("未发现真实存档，跳过。");
            }
            else
            {
                var raw = Gdec.ReadEncryptedFile(p.SaveFile, p.SaveKey());
                var env = Envelope.FromRawStream(raw);
                var payload = env.Get("payload")!;
                var ver = payload.Get("save_version")?.Get("last_client_version")?.AsString() ?? "";
                int chars = payload.Get("characters")?.AsArray().Count ?? 0;
                outp.AppendLine($"账号={p.Name} 版本={ver} 角色数={chars} 原始流={raw.Length}B");

                // 回写临时文件再读回，验证一致性（不动真实存档）
                var tmp = Path.Combine(Path.GetTempPath(), "gfp_cs_roundtrip.dat");
                Gdec.WriteEncryptedFile(tmp, p.SaveKey(), Envelope.ToRawStream(env));
                var env2 = Envelope.FromRawStream(Gdec.ReadEncryptedFile(tmp, p.SaveKey()));
                File.Delete(tmp);
                outp.AppendLine($"回写往返: {(env2.Get("payload")!.Dic!.Count == payload.Dic!.Count ? "OK" : "不一致")}");
            }

            // 3) WPF 版本的 Fusion 风格通过界面人工目视核对（无需离屏渲染）
            outp.AppendLine("离屏渲染: 已省略（WPF 版本请在界面人工核对 Fusion 风格）");
        }
        catch (Exception e)
        {
            outp.AppendLine("异常: " + e.Message);
        }
        File.WriteAllText(Path.Combine(Path.GetTempPath(), "gfp_cs_selftest.txt"), outp.ToString(), Encoding.UTF8);
    }
}
