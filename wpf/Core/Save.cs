namespace Gfp.Core;

public sealed class Profile
{
    public string Name = "";
    public string Dir = "";
    public string SaveFile => Path.Combine(Dir, "save.dat");
    public string ProfileCfg => Path.Combine(Dir, "profile.cfg");

    /// profile.cfg 的 [Profile] encryption_id，空则回退账号名
    public string EncryptionId()
    {
        var v = Cfg.Read(ProfileCfg, "Profile", "encryption_id");
        return string.IsNullOrEmpty(v) ? Name : v;
    }

    public byte[] SaveKey() => Gdec.SaveKey(EncryptionId());
}

public static class Cfg
{
    /// Godot ConfigFile（INI）：逐行 Trim，[section]，行内按第一个 = 分割，值去首尾引号
    public static string? Read(string path, string section, string key)
    {
        string text;
        try { text = File.ReadAllText(path); } catch { return null; }
        string cur = "";
        foreach (var rawLine in text.Split('\n'))
        {
            var line = rawLine.Trim();
            if (line.Length == 0 || line.StartsWith(";") || line.StartsWith("#")) continue;
            if (line.StartsWith("[") && line.EndsWith("]"))
            {
                cur = line[1..^1].Trim();
                continue;
            }
            if (cur != section) continue;
            int eq = line.IndexOf('=');
            if (eq < 0) continue;
            if (line[..eq].Trim() != key) continue;
            var v = line[(eq + 1)..].Trim();
            if (v.Length >= 2 && ((v[0] == '"' && v[^1] == '"') || (v[0] == '\'' && v[^1] == '\'')))
                v = v[1..^1];
            return v;
        }
        return null;
    }
}

public static class Save
{
    /// 存档根目录覆盖点。桌面版保持 null（走 %APPDATA%）；Android 侧在启动时设为
    /// /storage/emulated/0/Documents/YierPai（游戏侧 SAVE_ROOT 的父目录，见 local_save_manager.gd）。
    public static string? DataDirOverride;

    public static string DataDir => DataDirOverride ?? Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "Godot", "app_userdata", "YierPai");
    public static string SavesDir => Path.Combine(DataDir, "saves");
    public static string BackupsDir => Path.Combine(DataDir, "backups");

    public static List<Profile> ListProfiles()
    {
        var list = new List<Profile>();
        try
        {
            if (!Directory.Exists(SavesDir)) return list;
            foreach (var d in Directory.GetDirectories(SavesDir))
            {
                var name = Path.GetFileName(d);

                // ⚠ 跳过"名字已损坏"的目录。
                //   Linux 文件名是原始字节，若含非法 UTF-8 序列，.NET 解码时会得到替换字符
                //   U+FFFD（形如 "�"），在 ComboBox 里就渲染成一个空白项。
                //   实测来源：Godot 在 Android 上创建账号目录时，把「桃」的 3 字节 UTF-8
                //   (e6 a1 8a) 截断成了 2 字节 (e6 a1) ⇒ 目录名成了一串不可显示字符。
                //   这类目录里可能装着完整存档，所以只从列表里排除 + 打日志，绝不删除。
                if (!IsDisplayableName(name))
                {
                    Console.WriteLine($"[GFP] 跳过名称损坏的存档目录（不会被删除）：{d}");
                    continue;
                }

                // 跳过没有 save.dat 的目录（多为建到一半被中断的残留）
                if (!File.Exists(Path.Combine(d, "save.dat"))) continue;

                list.Add(new Profile { Name = name, Dir = d });
            }
        }
        catch { return list; }
        list.Sort((a, b) => string.CompareOrdinal(a.Name, b.Name));
        return list;
    }

    /// <summary>
    /// 名字是否可正常显示：既不含 UTF-8 解码失败的替换字符，也不含控制字符。
    /// 正常的账号名（含中文）不会命中这里。
    /// </summary>
    private static bool IsDisplayableName(string name)
    {
        if (name.Length == 0) return false;
        foreach (var ch in name)
            if (ch == '\uFFFD' || char.IsControl(ch)) return false;
        return true;
    }

    public static string? ActiveProfileName()
        => Cfg.Read(Path.Combine(DataDir, "login_credentials.cfg"), "Login", "profile_name");

    public static Profile? Find(string name)
        => ListProfiles().FirstOrDefault(p => p.Name == name);

    /// 返回 (payload, version)
    public static (Variant payload, string version) LoadPayload(Profile p)
    {
        var raw = Gdec.ReadEncryptedFile(p.SaveFile, p.SaveKey());
        var env = Envelope.FromRawStream(raw);
        var payload = env.Get("payload") ?? Variant.Nil();
        var ver = payload.Get("save_version")?.Get("last_client_version")?.AsString() ?? "V0.0.0";
        return (payload, ver);
    }

    public static void SavePayload(Profile p, Variant payload)
    {
        var d = Variant.OfDict();
        d.Set("magic", Variant.OfStr(Gdec.SaveMagic));
        d.Set("container_version", Variant.OfInt(Gdec.ContainerVersion));
        d.Set("payload", payload);
        var raw = Envelope.ToRawStream(d);
        Gdec.WriteEncryptedFile(p.SaveFile, p.SaveKey(), raw);
    }
}
