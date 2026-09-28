package com.yierpai.savetool.core

import org.json.JSONObject

data class CharInfo(val idx: Int, val name: String, val roleId: String, val level: Long)

/** 开荒减负：给等级 ≤ 10 的角色补齐鲲鹏之征服者套装（6 护甲 + 1 武器） */
object Relief {
    const val ARMOR_PREFIX = "鲲鹏之征服者"
    const val WEAPON_PREFIX = "鲲鹏之"
    const val ARMOR_DESC = "集鲲鹏之力具有强大属性，可直接使用至45级，成为超灵侠士可升至更高级"

    private val ALL_DBS = listOf(
        "伊尔装备图标数据.json", "派派装备图标数据.json", "大竹装备图标数据.json", "敖天装备图标数据.json"
    )

    private val ROLE_DBS = mapOf(
        "伊尔" to listOf("伊尔装备图标数据.json"),
        "派派" to listOf("派派装备图标数据.json"),
        "大竹" to listOf("大竹装备图标数据.json"),
        "敖天" to listOf("敖天装备图标数据.json"),
    )

    private fun readEmbedded(name: String): String? = try {
        AppCtx.assets.open(name).bufferedReader(Charsets.UTF_8).use { it.readText() }
    } catch (_: Exception) {
        null
    }

    /** 7 件鲲鹏装备 id（去重保序） */
    fun kunpengIds(roleId: String): MutableList<Long> {
        val files = ROLE_DBS[roleId] ?: ALL_DBS
        val seen = HashSet<Long>()
        val ids = mutableListOf<Long>()
        for (file in files) {
            val text = readEmbedded(file) ?: continue
            val root = try { JSONObject(text) } catch (_: Exception) { continue }
            val keys = root.keys()
            while (keys.hasNext()) {
                val key = keys.next()
                val e = root.optJSONObject(key) ?: continue
                val name = e.optString("名称", "")
                val desc = e.optString("描述", "")
                if (!e.has("id")) continue
                val id = e.optDouble("id", 0.0).toLong()
                val isArmor = name.startsWith(ARMOR_PREFIX)
                val isWeapon = name.startsWith(WEAPON_PREFIX) && desc == ARMOR_DESC
                if ((isArmor || isWeapon) && seen.add(id)) ids.add(id)
            }
        }
        return ids
    }

    fun chars(payload: Variant): MutableList<CharInfo> {
        val list = mutableListOf<CharInfo>()
        val arr = payload.get("characters")?.asArray() ?: mutableListOf()
        for (i in arr.indices) {
            val ch = arr[i]
            // ⚠ 跳过空角色槽位：characters 数组预留固定数量槽（未使用的是 NIL），
            //   必须对齐 PySide6 的 `if not isinstance(c, dict): continue`，
            //   否则空槽会渲染成「角色{i}（）Lv.0」幽灵条目。
            //   注意保留原始下标 i 作为 idx（不能改成过滤后的序号），否则写回会错角色。
            if (ch.kind != VKind.Dict) continue
            val ident = ch.get("identity")
            val name = ident?.get("name")?.asString() ?: "角色$i"
            val role = ident?.get("role_id")?.asString() ?: ""
            val lv = when (val l = ch.get("progression")?.get("level")) {
                null -> 0L
                else -> when (l.kind) {
                    VKind.Int -> l.i
                    VKind.Float -> l.d.toLong()
                    else -> 0L
                }
            }
            list.add(CharInfo(i, name, role, lv))
        }
        return list
    }

    fun display(c: CharInfo): String = "${c.name}（${c.roleId}）Lv.${c.level}"

    private fun asLong(v: Variant?): Long = when (v?.kind) {
        VKind.Int -> v.i
        VKind.Float -> v.d.toLong()
        else -> 0L
    }

    /** 物品可能是 {"id":..} 字典，存档里 id 多为 Float */
    private fun itemId(v: Variant?): Long = if (v?.kind == VKind.Dict) asLong(v.get("id")) else 0L

    /** 身上 + 库存 + 账号共仓 里已有的鲲鹏 id */
    fun ownedKunpengIds(payload: Variant, idx: Int): HashSet<Long> {
        val set = HashSet<Long>()
        val arr = payload.get("characters")?.asArray() ?: mutableListOf()
        if (idx < 0 || idx >= arr.size) return set
        val ch = arr[idx]

        // 身上穿戴：equipment 是 槽位 -> 物品(dict) 的字典，需取物品里的 id
        ch.get("equipment")?.dic?.forEach { set.add(itemId(it.second)) }
        ch.get("inventory")?.get("equipment")?.asArray()?.forEach { set.add(itemId(it)) }
        payload.get("account_storehouse")?.get("entries")?.asArray()?.forEach { e ->
            set.add(itemId(e))
            e.get("equipment")?.asArray()?.forEach { set.add(itemId(it)) }
        }
        return set
    }

    private val rng = java.util.Random()

    private fun nextLong(min: Long, max: Long): Long {
        val buf = ByteArray(8)
        rng.nextBytes(buf)
        var u = 0L
        for (i in 7 downTo 0) u = (u shl 8) or (buf[i].toLong() and 0xFF)
        return min + (u % (max - min))
    }

    fun genUid(): String {
        val a = nextLong(1_000_000_000L, 10_000_000_000L)
        val b = nextLong(1_000_000_000L, 10_000_000_000L)
        return "${a}_${b}"
    }

    /** 把缺失的装备追加到 characters[idx].inventory.equipment */
    fun addToInventory(payload: Variant, idx: Int, ids: List<Long>) {
        val chars = payload.get("characters")?.asArray() ?: error("存档缺少 characters 列表。")
        if (idx < 0 || idx >= chars.size) error("角色下标越界。")
        val ch = chars[idx]
        if (ch.kind != VKind.Dict) error("角色数据不是字典。")

        var inv = ch.get("inventory")
        if (inv == null || inv.kind != VKind.Dict) {
            inv = Variant.ofDict()
            ch.set("inventory", inv)
        }
        var eq = inv.get("equipment")
        if (eq == null || eq.kind != VKind.Array) {
            eq = Variant.ofArray(mutableListOf())
            inv.set("equipment", eq)
        }
        val target = eq.arr!!
        for (id in ids) {
            val item = Variant.ofDict()
            item.set("id", Variant.ofFloat(id.toDouble()))
            item.set("uid", Variant.ofStr(genUid()))
            target.add(item)
        }
    }
}
