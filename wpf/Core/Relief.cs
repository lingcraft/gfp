using System.Reflection;
using System.Text.Json;

namespace Gfp.Core;

public sealed record CharInfo(int Idx, string Name, string RoleId, long Level);

/// 开荒减负：给等级小于等于 10 的角色补齐鲲鹏之征服者套装（6 护甲 + 1 武器）
public static class Relief
{
    public const string ArmorPrefix = "鲲鹏之征服者";
    public const string WeaponPrefix = "鲲鹏之";
    public const string ArmorDesc = "集鲲鹏之力具有强大属性，可直接使用至45级，成为超灵侠士可升至更高级";

    private static readonly string[] AllDbs =
    {
        "伊尔装备图标数据.json", "派派装备图标数据.json", "大竹装备图标数据.json", "敖天装备图标数据.json",
    };

    private static readonly Dictionary<string, string[]> RoleDbs = new()
    {
        ["伊尔"] = new[] { "伊尔装备图标数据.json" },
        ["派派"] = new[] { "派派装备图标数据.json" },
        ["大竹"] = new[] { "大竹装备图标数据.json" },
        ["敖天"] = new[] { "敖天装备图标数据.json" },
    };

    private static string? ReadEmbedded(string name)
    {
        var asm = Assembly.GetExecutingAssembly();
        using var s = asm.GetManifestResourceStream(name);
        if (s is null) return null;
        using var r = new StreamReader(s);
        return r.ReadToEnd();
    }

    private static long AsLong(Variant? v) => v?.Kind switch
    {
        VKind.Int => v.I,
        VKind.Float => (long)v.D,
        _ => 0,
    };

    /// 7 件鲲鹏装备 id（去重保序）
    public static List<long> KunpengIds(string roleId)
    {
        var files = RoleDbs.TryGetValue(roleId, out var f) ? f : AllDbs;
        var seen = new HashSet<long>();
        var ids = new List<long>();
        foreach (var file in files)
        {
            var text = ReadEmbedded(file);
            if (text is null) continue;
            JsonDocument doc;
            try { doc = JsonDocument.Parse(text); } catch { continue; }
            using (doc)
            {
                if (doc.RootElement.ValueKind != JsonValueKind.Object) continue;
                foreach (var prop in doc.RootElement.EnumerateObject())
                {
                    var e = prop.Value;
                    if (e.ValueKind != JsonValueKind.Object) continue;
                    string name = e.TryGetProperty("名称", out var n) ? n.GetString() ?? "" : "";
                    string desc = e.TryGetProperty("描述", out var d) ? d.GetString() ?? "" : "";
                    if (!e.TryGetProperty("id", out var idEl)) continue;
                    long id = idEl.ValueKind == JsonValueKind.Number ? (long)idEl.GetDouble() : 0;
                    bool isArmor = name.StartsWith(ArmorPrefix, StringComparison.Ordinal);
                    bool isWeapon = name.StartsWith(WeaponPrefix, StringComparison.Ordinal) && desc == ArmorDesc;
                    if ((isArmor || isWeapon) && seen.Add(id)) ids.Add(id);
                }
            }
        }
        return ids;
    }

    public static List<CharInfo> Chars(Variant payload)
    {
        var list = new List<CharInfo>();
        var arr = payload.Get("characters")?.AsArray() ?? new();
        for (int i = 0; i < arr.Count; i++)
        {
            var ch = arr[i];
            // ⚠ 跳过空角色槽位：存档的 characters 数组会预留固定数量的槽（未使用的槽是 NIL），
            //    必须与 PySide6 版的 `if not isinstance(c, dict): continue` 对齐，
            //    否则空槽会被渲染成「角色{i}（）Lv.0」这种幽灵条目。
            //    注意保留原始下标 i 作为 Idx（不能改成过滤后的序号），否则写回会错角色。
            if (ch.Kind != VKind.Dict) continue;
            var ident = ch.Get("identity");
            string name = ident?.Get("name")?.AsString() ?? $"角色{i}";
            string role = ident?.Get("role_id")?.AsString() ?? "";
            long lv = ch.Get("progression")?.Get("level")?.Kind switch
            {
                VKind.Int => ch.Get("progression")!.Get("level")!.I,
                VKind.Float => (long)ch.Get("progression")!.Get("level")!.D,
                _ => 0,
            };
            list.Add(new CharInfo(i, name, role, lv));
        }
        return list;
    }

    public static string Display(CharInfo c) => $"{c.Name}（{c.RoleId}）Lv.{c.Level}";

    /// 物品可能是 {"id":..} 字典，存档里 id 多为 Float；与 Python 的 int(v["id"]) 对齐
    private static long ItemId(Variant? v) => v?.Kind == VKind.Dict ? AsLong(v.Get("id")) : 0;

    /// 身上 + 库存 + 账号共仓 里已有的鲲鹏 id（存档中 id 通常为 Float）
    public static HashSet<long> OwnedKunpengIds(Variant payload, int idx)
    {
        var set = new HashSet<long>();
        var arr = payload.Get("characters")?.AsArray() ?? new();
        if (idx < 0 || idx >= arr.Count) return set;
        var ch = arr[idx];

        // 身上穿戴：equipment 是 槽位 -> 物品(dict) 的字典，需取物品里的 id
        var worn = ch.Get("equipment");
        if (worn?.Dic is not null)
            foreach (var kv in worn.Dic)
                set.Add(ItemId(kv.Value));

        foreach (var it in ch.Get("inventory")?.Get("equipment")?.AsArray() ?? new())
            set.Add(ItemId(it));

        foreach (var e in payload.Get("account_storehouse")?.Get("entries")?.AsArray() ?? new())
        {
            set.Add(ItemId(e));
            foreach (var sub in e.Get("equipment")?.AsArray() ?? new())
                set.Add(ItemId(sub));
        }
        return set;
    }

    private static readonly Random Rng = new();

    private static long NextLong(long min, long max)
    {
        // net48 的 Random 无 NextInt64，自行实现
        var buf = new byte[8];
        Rng.NextBytes(buf);
        var u = (ulong)BitConverter.ToInt64(buf, 0);
        return min + (long)(u % (ulong)(max - min));
    }

    public static string GenUid()
    {
        long a = NextLong(1_000_000_000L, 10_000_000_000L);
        long b = NextLong(1_000_000_000L, 10_000_000_000L);
        return $"{a}_{b}";
    }

    /// 把缺失的装备追加到 characters[idx].inventory.equipment
    public static void AddToInventory(Variant payload, int idx, List<long> ids)
    {
        var chars = payload.Get("characters")?.AsArray() ?? throw new Exception("存档缺少 characters 列表。");
        if (idx < 0 || idx >= chars.Count) throw new Exception("角色下标越界。");
        var ch = chars[idx];
        if (ch.Kind != VKind.Dict) throw new Exception("角色数据不是字典。");

        var inv = ch.Get("inventory");
        if (inv is null || inv.Kind != VKind.Dict)
        {
            inv = Variant.OfDict();
            ch.Set("inventory", inv);
        }
        var eq = inv.Get("equipment");
        if (eq is null || eq.Kind != VKind.Array)
        {
            eq = Variant.OfArray(new());
            inv.Set("equipment", eq);
        }
        foreach (var id in ids)
        {
            var item = Variant.OfDict();
            item.Set("id", Variant.OfFloat(id));
            item.Set("uid", Variant.OfStr(GenUid()));
            eq.Arr!.Add(item);
        }
    }
}
