#!/usr/bin/env python3
"""一键修改 YierPai.apk 的存档路径（SAVE_ROOT → /sdcard/YierPai/saves）并重打包签名（可选安装）。

完整链路（2026-09-26 双会话实测走通；关键点/坑点见 .codebuddy/memory/MEMORY.md 与 2026-09-26.md）：

  1. 从 APK 抽出 `assets/assets.sparsepck`（Godot 资源包）
     ⚠ 不能把 APK 直接喂给 gdre_tools --recover（会卡在 Opening file、零产出）
  2. **现场从 pck 恢复【原版】`globals/local_save_manager.gd`**，然后只做最小改动一处：
     `const SAVE_ROOT: = "user://saves"` → `const SAVE_ROOT: = "/storage/emulated/0/YierPai/saves"`
     ——直改初值字面量（全脚本 SAVE_ROOT 只有 1 处读取、0 处赋值，且本包只发 Android，
       所以**保留 const、不加 `_ready()` 分支**，改动量 1 处）；不再维护任何"改好的 gd 副本"，
     其余代码（含游戏原生 rename 存档事务）一字不动
     （--gd 只在需要指定外部脚本时使用）
     ⚠ 存档事务**保持游戏原生 rename 逻辑，勿改成 copy+remove**：未授权时 Godot Java 层走
       MediaStore 通道，copy+remove 会留 save.dat.tmp 残留并触发"未覆盖原文件"报错；
       授权后走直接文件 IO，rename 正常（授权引导见步骤 4.5 的 Java 层注入）
  3. `gdre_tools --compile --bytecode=4.5.0-stable` 编译回 `.gdc`
     ⚠ 字节码版本必须是原包字节码版本 4.5.0-stable（ebc36a7），≠ 引擎版本
  4. `gdre_tools --pck-patch` 把新 `.gdc` 打回 pck
  5. AXML 二进制 patch 给 Manifest 补 3 个存储权限（MANAGE/READ/WRITE）
     ⚠ **动态解析字符串池索引**（硬编码索引换包必错）；HyperOS 上声明 READ/WRITE
       （未授权）即免授权可写 Android/media；零声明走 MediaStore 通道报"错误码 1"
  5.5. **dex 注入**：`GodotActivity.onCreate` 开头插"所有文件访问"权限检查 → 启动即秒弹
     系统授权页（在引擎加载 3.6G pck **之前**，比 GDScript `_ready` 快 6 倍以上）
  6. **纯 Python `zipfile`** 一次替换 sparsepck + Manifest + dex 三个条目（2026-09-28 由 Java 改造）
     ⚠ **STORED 条目必须 `force_zip64=True`**：否则 Python 写完才发现 >2GB、无法回填 header →
       `RuntimeError: File size too large, try using force_zip64`，或产出 LFH size=0xFFFFFFFF
       的坏包（曾被 apksig 判 `LFH data ... overlaps with Central Directory` 而拒签 ——
       旧版因此改用 Java `ZipOutputStream`，其实 Python 也行**而且更快**：实测重打包 3652MB
       的 APK **Python 5.2s vs Java 8.1s**，两者产物均通过 Java `ZipFile` 校验）
     ⚠ sparsepck 必须 STORED（DEFLATED → Godot 无法 mmap → 卡死 splash 假死）；
     ⚠ 必须剔除 META-INF/*.MF|.SF|.RSA（旧签名，新签名由 uber-apk-signer 生成）；
     ⚠ 条目顺序 / 压缩方式 / 时间戳 / 属性沿用原 APK
  7. uber-apk-signer 签名 + 外置 zipalign 对齐（内置 32 位打不开 >2GB）
  8. 可选 --install：adb push + `pm install`（>2GB 禁用 adb install 流式/增量）
     ⚠ 免授权形态安装后**不要用 `adb shell rm` 删 Android/media 下的存档文件**
       （会留 MediaStore 孤儿记录，之后游戏报"未覆盖原文件：save.dat.tmp"）；
       要清存档请整体 `pm uninstall` 或让游戏自己管理

用法：
    python build_game.py                                  # 默认原始包 → temp 输出（结束自动清理工作目录）
    python build_game.py --install                        # 构建后装到手机
    python build_game.py --install --grant                # 装好并授予 MANAGE（appops allow）
    python build_game.py --keep-work                      # 保留工作目录（默认会清理）
    python build_game.py --gd x.gd                        # 指定外部 gd（高级用法）
"""

import argparse
import hashlib
import os
import re
import shutil
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

# ⚠ **Android 的 zipalign / libziparchive 不支持 ZIP64**（2026-09-28 实测）：
#    3.4GB 的 sparsepck 若按 ZIP64 写（LFH size=0xFFFFFFFF + ZIP64 extra），
#    zipalign 报 `Unable to open ... for verification`、apksig 也会读不出条目。
#    Python 默认 `zipfile.ZIP64_LIMIT` 只有 2GB，超过就切 ZIP64 ⇒ 这里提高到 ZIP32 的
#    上限 4GB-1，使 <4GB 的条目写成普通 32 位 size 字段（与 Java ZipOutputStream 行为一致，
#    实测 zipalign / apksig 均接受）。⚠ 单个条目 >4GB 时仍会自动走 ZIP64。
zipfile.ZIP64_LIMIT = 0xFFFFFFFF

# ===================== 工具路径（用户约定位置） =====================
GDRE_DIR = Path(r"D:\Personal Files\Reverse\Godot提取")       # gdre_tools.exe + gdre_tools.pck 同目录
GDRE_EXE = GDRE_DIR / "gdre_tools.exe"                    # cwd 指向 GDRE_DIR 以加载同目录 gdre_tools.pck
JAVA = Path(r"D:\Software\JDK\17\bin\java.exe")
UBER_APK_SIGNER = Path(r"D:\Personal Files\Reverse\APK签名\uber-apk-signer.jar")
KEYSTORE = Path(r"D:\Personal Files\Reverse\APK签名\lingcraft.jks")
KEYSTORE_ALIAS = "lingcraft"
KS_PASS = "123456"                                       # 密钥库密码（用户提供，写死到脚本）
ZIPALIGN = Path(r"D:\Personal Files\Reverse\APK签名\zipalign.exe")   # build-tools 版（ZIP64 支持 >2GB）
ADB = Path(r"D:\Software\Android\platform-tools\adb.exe")
SCRIPT_DIR = Path(__file__).resolve().parent              # gfp 项目根
DEFAULT_ORIG = Path(r"D:\Downloads\temp\GDRE\YierPai.apk")

# ===================== 游戏/打包参数 =====================
PKG_NAME = "com.yierpai.mobiletest"
PCK_ENTRY = "assets/assets.sparsepck"  # APK 内的 pck 条目名
SAVE_SCRIPT_REL = "globals/local_save_manager"  # pck 内脚本相对路径（无扩展名）
PERMISSIONS = [  # 追加到 Manifest 的存储权限
    "android.permission.READ_EXTERNAL_STORAGE",
    "android.permission.WRITE_EXTERNAL_STORAGE",
    "android.permission.MANAGE_EXTERNAL_STORAGE",
]
BYTECODE_VERSION = "4.5.0-stable"  # 原包字节码版本（commit ebc36a7）
SAVE_ROOT = "/storage/emulated/0/YierPai/saves"  # = /sdcard/YierPai/saves
REMOTE_TMP = "/data/local/tmp/build_game_install.apk"


def run(cmd, cwd=None):
    print("[$]", subprocess.list2cmdline(cmd), flush=True)
    kwargs = {"check": True}
    if cwd is not None:
        kwargs["cwd"] = str(cwd)
    subprocess.run(cmd, **kwargs)


def rmtree_safe(path, label: str = ""):
    """直接删除目录（rmtree）。带一层容错：万一删除被沙箱/IDE 的保护机制拦截，
    只提示、不抛出——否则清理阶段的异常会让整个构建看起来像失败。"""
    p = Path(path)
    if not p.exists():
        return
    try:
        shutil.rmtree(p)
    except Exception as e:
        print(f"[i] 清理 {label or p} 未完成（{type(e).__name__}）——"
              f"目录已保留，可手动删除或用 --keep-work 跳过清理")


def md5_of(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ===================== 步骤 1：抽 pck =====================
def extract_pck(apk_path: Path, out_pck: Path):
    print("[i] 从 APK 抽出 pck …")
    with zipfile.ZipFile(apk_path) as z:
        names = z.namelist()
        entry = PCK_ENTRY
        if entry not in names:
            cands = [n for n in names if n.endswith((".sparsepck", ".pck"))]
            if not cands:
                raise SystemExit("APK 内找不到 pck 条目（找过 *.sparsepck/*.pck）")
            entry = cands[0]
            print(f"[i] 自动识别 pck 条目：{entry}")
        with z.open(entry) as src, open(out_pck, "wb") as dst:
            shutil.copyfileobj(src, dst, length=8 * 1024 * 1024)
    print(f"[v] 已抽出：{out_pck}（{out_pck.stat().st_size / 2**30:.2f} GB）")


# ===================== 步骤 2：现场恢复原版脚本（默认路径） =====================
def recover_scripts(pck: Path, out_dir: Path):
    print("[i] gdre_tools 恢复脚本源码（--scripts-only）…")
    run([str(GDRE_EXE), "--headless", f"--recover={pck}", "--scripts-only",
         f"--output={out_dir}"], cwd=GDRE_DIR)
    return out_dir


def patch_save_root(gd_path: Path, save_root: str) -> int:
    """在【原版脚本】上做最小改动 —— **只替换 SAVE_ROOT 的初值字面量，共 1 处**：
       `const SAVE_ROOT: = "user://saves"` → `const SAVE_ROOT: = "<save_root>"`

    为什么可以直改字面量（2026-09-27 核实 + 用户确认本包只发 Android）：
      - 全脚本 `SAVE_ROOT` **只有 1 处读取**（`_get_profile_file_path` 里 `"%s/%s" % [...]`）、
        **0 处赋值** ⇒ 不需要 `var`，`const` 可以保留；
      - 本包只在 Android 跑，不需要 `OS.has_feature("android")` 条件分支（那是为了
        同一份源码还能在 PC/编辑器里跑）；
      - 编译是从**源码**重新编译，`const` 的新值会被内联到所有使用点，改声明处即全生效。
    ⇒ 改动量从 2 处（const→var + _ready 插 3 行）降到 **1 处**，diff 更干净。

    其余一字不动 —— 特别是存档事务必须保持游戏原生 `dir.rename`
    （授权后 Godot 走直接文件 IO，rename 正常；改成 copy+remove 反而会在
    未授权时留 .tmp 残留，见 MEMORY.md）。返回改动条数（用于自检）。
    """
    # 按【字节】读写：保持原文件行尾（文本模式会把 LF 转成系统 CRLF，导致 diff 全文件飘红）
    raw = gd_path.read_bytes()
    text = raw.decode("utf-8")

    # 匹配 `const SAVE_ROOT: = "..."` / `const SAVE_ROOT: String = "..."` /
    #      `var SAVE_ROOT: String = "..."`（兼容历史改法），捕获到 `=` 为止的前缀
    pat = re.compile(r'((?:const|var)\s+SAVE_ROOT(?::[^\r\n=]*)?\s*=\s*)"[^"]*"')
    m = pat.search(text)
    if not m:
        raise SystemExit('找不到 SAVE_ROOT 声明行，脚本结构不识别：' + str(gd_path))

    if m.group(0).endswith('"%s"' % save_root):
        print(f"[i] SAVE_ROOT 已是 {save_root}，无需修改")
        return 0

    new_text = text[:m.start()] + m.group(1) + f'"{save_root}"' + text[m.end():]
    gd_path.write_bytes(new_text.encode("utf-8"))
    print(f"[v] 已最小改动 1 处：SAVE_ROOT 初值 → {save_root}（保留 const，无 _ready 分支）")
    return 1


# ===================== 步骤 3：编译 =====================
def compile_gdc(gd_path: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[i] 编译 .gdc（bytecode={BYTECODE_VERSION}）…")
    run([str(GDRE_EXE), "--headless", f"--compile={gd_path}", f"--bytecode={BYTECODE_VERSION}",
         f"--output={out_dir}"], cwd=GDRE_DIR)
    gdc = out_dir / (gd_path.stem + ".gdc")
    if not gdc.exists():
        raise SystemExit(f"编译后没找到：{gdc}")
    return gdc


# ===================== 步骤 4：打回 pck =====================
def patch_pck(pck: Path, patches, out_pck: Path):
    """patches: list of (gdc_path, res_path)。--patch-file 可重复。"""
    cmd = [str(GDRE_EXE), "--headless", f"--pck-patch={pck}"]
    for gdc, res in patches:
        cmd.append(f"--patch-file={gdc}={res}")
    cmd.append(f"--output={out_pck}")
    print("[i] 打回 pck …")
    run(cmd, cwd=GDRE_DIR)
    if not out_pck.exists():
        raise SystemExit(f"pck 补丁失败，没生成：{out_pck}")


# ===================== 步骤 5：AXML Manifest 补权限（动态索引版） =====================
def patch_manifest_bytes(data: bytes, perms) -> bytes:
    """往二进制 AndroidManifest.xml(AXML) 追加 uses-permission 节点。

    ⚠ 动态解析字符串池索引（硬编码索引换包必错）；已声明的权限自动跳过（可重复运行）；
    resource map 保持原样（本包 map 条目数与字符串数不符属非标结构，属性值是 STRING
    类型不查 map，运行时按索引宽容）；仅支持 UTF-16 字符串池（本游戏如此）。
    """
    def u16(b, o): return struct.unpack_from("<H", b, o)[0]
    def u32(b, o): return struct.unpack_from("<I", b, o)[0]
    def pad4(n): return (n + 3) & ~3

    assert u16(data, 0) == 0x0003, "不是 AXML"
    sp = u16(data, 2)
    sp_type, sp_hdr, sp_size, count, style_count, flags, strings_start, styles_start = \
        struct.unpack_from("<HHIIIIII", data, sp)
    assert sp_type == 0x0001 and style_count == 0
    is_utf8 = bool(flags & 0x100)
    assert not is_utf8, "UTF-8 字符串池未实现（本游戏为 UTF-16 池）"
    assert sp_hdr == 28
    base = sp + strings_start
    offsets = [u32(data, sp + sp_hdr + 4 * i) for i in range(count)]

    def read_str(off):
        p = base + off
        l = u16(data, p); p += 2
        if l & 0x8000:
            l = ((l & 0x7FFF) << 16) | u16(data, p); p += 2
        return data[p:p + l * 2].decode("utf-16-le")

    strs = [read_str(o) for o in offsets]

    def find(s):
        for i, x in enumerate(strs):
            if x == s:
                return i
        return -1

    idx_uses_perm = find("uses-permission")
    idx_ns = find("http://schemas.android.com/apk/res/android")
    idx_name = find("name")
    assert idx_uses_perm >= 0 and idx_ns >= 0 and idx_name >= 0, "Manifest 缺少前提字符串"

    to_add = [p for p in perms if find(p) < 0]
    out = bytearray(data)

    if to_add:
        # 旧数据区实际末尾（最后一个字符串结束处，非 chunk 末尾——尾部可能有 padding）
        last_end = 0
        for o in offsets:
            p = base + o
            l = u16(data, p); q = p + 2
            if l & 0x8000:
                l = ((l & 0x7FFF) << 16) | u16(data, q); q += 2
            last_end = max(last_end, q - base + l * 2 + 2)
        # 追加权限字符串
        blocks = []
        running = last_end
        for s in to_add:
            blk = struct.pack("<H", len(s)) + s.encode("utf-16-le") + b"\x00\x00"
            new_offsets = offsets + [running]
            offsets = new_offsets
            running += len(blk)
            blocks.append(blk)
        # 重建 string pool chunk（旧数据原样 + 新字符串，offsets 含新条目）
        tail = data[base:base + last_end] + b"".join(blocks)
        tail += b"\x00" * (pad4(len(tail)) - len(tail))
        new_count = count + len(to_add)
        new_strings_start = pad4(sp_hdr + 4 * new_count)
        new_sp_size = new_strings_start + len(tail)
        chunk = struct.pack("<HHIIIIII", 0x0001, sp_hdr, new_sp_size, new_count,
                            style_count, flags, new_strings_start, styles_start)
        chunk += b"".join(struct.pack("<I", o) for o in offsets)
        chunk += tail
        out[sp:sp + sp_size] = chunk          # bytearray 切片赋值自动伸缩
        print(f"[v] Manifest 字符串池追加 {len(to_add)} 个权限：{', '.join(to_add)}")
    else:
        to_add = []
        print("[i] 权限均已声明，跳过字符串追加")

    # ---- resource map：保持原样（非标结构，不动最安全） ----
    pos = sp + (u32(data, sp + 4) if not to_add else struct.unpack_from("<I", out, sp + 4)[0])
    if u16(out, pos) == 0x0180:
        rm_size = u32(out, pos + 4)
        pos += rm_size

    # ---- 节点流：找最后一个 uses-permission 的 END_ELEMENT ----
    insert_at = None
    scan = pos
    while scan < len(out):
        t = u16(out, scan); sz = u32(out, scan + 4)
        if t == 0x0103 and u32(out, scan + 20) == idx_uses_perm:
            insert_at = scan + sz
        scan += sz
    assert insert_at is not None, "未找到 uses-permission 节点"

    def make_perm(perm_idx):
        start = struct.pack("<HHI", 0x0102, 16, 56)
        start += struct.pack("<II", 0, 0xFFFFFFFF)          # lineNumber / comment
        start += struct.pack("<iI", -1, idx_uses_perm)      # attrExt: ns / name
        start += struct.pack("<HHHHHH", 20, 20, 1, 0, 0, 0)  # attributeStart/Size/Count/id/class/style
        start += struct.pack("<iIi", idx_ns, idx_name, perm_idx)  # attribute: ns/name/rawValue
        start += struct.pack("<HBBI", 8, 0, 0x03, perm_idx)  # typedValue: size/res0/STRING/data
        end = struct.pack("<HHI", 0x0103, 16, 24)
        end += struct.pack("<II", 0, 0xFFFFFFFF)
        end += struct.pack("<iI", -1, idx_uses_perm)
        return start + end

    # 新权限字符串索引 = 原 count 起依次排（追加在池尾）
    insert_nodes = b"".join(make_perm(count + i) for i in range(len(to_add)))
    out = out[:insert_at] + insert_nodes + out[insert_at:]
    struct.pack_into("<I", out, 4, len(out))
    print(f"[v] Manifest 节点插入完成（+{len(to_add)} uses-permission），总大小 {len(out)}B")
    return out


# ===================== 步骤 6：Java 重打包 =====================
SMALI_DIR = Path(r"D:\Personal Files\Reverse\APK修改")   # baksmali/smali + 依赖 jar
# 2.5.2 的依赖（2026-09-28 实测确认）：
#   baksmali.jar  → dexlib2 / util / guava / jcommander（22 个类引用 jcommander）
#   smali.jar     → 同上 + antlr-runtime（140 个类引用，smali 语法解析）
#   ⚠ args4j **不需要**：smali 1.x/早期 2.x 用它解析命令行，2.5.2 已改用 jcommander
#     （两个 jar 里引用 org/kohsuke/args4j 的类数 = 0；去掉后反编译+回编译实测均正常）
SMALI_LIBS = ["dexlib2-2.5.2.jar", "util-2.5.2.jar", "guava.jar", "jcommander-1.82.jar"]
BAKSMALI_CP = ";".join(str(SMALI_DIR / j) for j in ["baksmali.jar"] + SMALI_LIBS)
SMALI_CP = ";".join(str(SMALI_DIR / j) for j in ["smali.jar"] + SMALI_LIBS + ["antlr-runtime-3.5.3.jar"])

# 注入到 GodotActivity.onCreate 开头：引擎加载 3.6G pck 之前就检查权限并跳授权页，
# 避免 GDScript 层 _ready() 申请时"游戏加载半天才弹"。
PERM_SMALI = """    # === GFP INJECT START: 启动即引导"所有文件访问"授权 ===
    sget v0, Landroid/os/Build$VERSION;->SDK_INT:I
    const/16 v1, 0x1e
    if-lt v0, v1, :gfp_perm_done

    invoke-static {}, Landroid/os/Environment;->isExternalStorageManager()Z
    move-result v0
    if-nez v0, :gfp_perm_done

    const-string v0, "GFP_PERM"
    const-string v1, "no All-Files-Access, opening settings"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I

    new-instance v0, Landroid/content/Intent;
    const-string v1, "android.settings.MANAGE_APP_ALL_FILES_ACCESS_PERMISSION"
    invoke-direct {v0, v1}, Landroid/content/Intent;-><init>(Ljava/lang/String;)V

    new-instance v1, Ljava/lang/StringBuilder;
    invoke-direct {v1}, Ljava/lang/StringBuilder;-><init>()V
    const-string v2, "package:"
    invoke-virtual {v1, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {p0}, Landroid/content/Context;->getPackageName()Ljava/lang/String;
    move-result-object v2
    invoke-virtual {v1, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v1}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v1
    invoke-static {v1}, Landroid/net/Uri;->parse(Ljava/lang/String;)Landroid/net/Uri;
    move-result-object v1
    invoke-virtual {v0, v1}, Landroid/content/Intent;->setData(Landroid/net/Uri;)Landroid/content/Intent;

    invoke-virtual {p0, v0}, Landroid/app/Activity;->startActivity(Landroid/content/Intent;)V

    :gfp_perm_done
    # === GFP INJECT END ===

"""


def patch_dex_permission(apk: Path, work: Path):
    """往 GodotActivity.onCreate 注入权限引导；返回 (dex 条目名, 新 dex 路径) 或 None。

    ⚠ 需要 `D:\\Personal Files\\Reverse\\APK修改\\` 下的 jar（baksmali/smali 2.5.2 + 依赖，
       Maven Central 下载；2026-09-28 从 gfp/tools/smali/ 移到此处以集中管理工具链）。
       GodotActivity 实现在哪个 dex 由内容自动判定（>50KB 且含类描述符），
       不能写死 dex 序号——重打包/换包都可能变。
    """
    if not SMALI_DIR.exists():
        print(f"[!] 未找到 {SMALI_DIR}，跳过 dex 权限引导注入")
        return None

    with zipfile.ZipFile(apk) as z:
        dexes = [n for n in z.namelist()
                 if n.startswith("classes") and n.endswith(".dex")]
        target, data = None, None
        for n in dexes:
            d = z.read(n)
            if b"org/godotengine/godot/GodotActivity" in d and len(d) > 50000:
                target, data = n, d
                break
    if target is None:
        print("[!] 没找到含 GodotActivity 实现的 dex，跳过注入")
        return None

    dex_in = work / ("in_" + target.replace("/", "_"))
    dex_in.write_bytes(data)
    smali_out = work / "smali_dex"
    n = 1
    while smali_out.exists():          # 不复用旧目录：删除会触发环境的批量删除保护
        smali_out = work / f"smali_dex_{n}"
        n += 1
    run([str(JAVA), "-cp", BAKSMALI_CP, "org.jf.baksmali.Main",
         "d", str(dex_in), "-o", str(smali_out)], cwd=work)

    ga = smali_out / "org" / "godotengine" / "godot" / "GodotActivity.smali"
    if not ga.exists():
        print(f"[!] {ga} 不存在，跳过注入")
        return None

    text = ga.read_text(encoding="utf-8")
    if "GFP INJECT START" in text:
        print("[i] dex 已注入过权限引导")
    else:
        m = re.search(r"\.method protected onCreate\(Landroid/os/Bundle;\)V\n", text)
        if not m:
            print("[!] 找不到 onCreate(Bundle)，跳过注入")
            return None
        rest, head = text[m.end():], m.end()
        lm = re.search(r"\n(?:    \.param [^\n]*\n)*    \.line ", rest)
        if not lm:
            print("[!] 找不到 onCreate 内的 .line 定位点，跳过注入")
            return None
        pos = head + lm.start() + 1
        ga.write_text(text[:pos] + PERM_SMALI + text[pos:], encoding="utf-8")
        print(f"[v] 已注入权限引导到 {target} 的 GodotActivity.onCreate")

    dex_out = work / ("patched_" + target.replace("/", "_"))
    run([str(JAVA), "-cp", SMALI_CP, "org.jf.smali.Main",
         "a", str(smali_out), "-o", str(dex_out)], cwd=work)
    return (target, dex_out)


def repack_apk(apk: Path, replacements, out_apk: Path, work: Path):
    """纯 Python 重打包：逐条复制 + 替换指定条目 + 剔除 META-INF 旧签名。

    ⚠ **STORED 条目必须 `force_zip64=True`**（`zout.open(zi, "w", force_zip64=True)`）：
       否则 Python 写完才发现 >2GB、无法回填 header → `RuntimeError: File size too large`，
       或产出 LFH size=0xFFFFFFFF 的坏包（曾被 apksig 判
       `LFH data ... overlaps with Central Directory` 而拒签）。
    ⚠ sparsepck 必须保持 STORED：DEFLATED 会让 Godot 无法 mmap → 卡死 splash 假死。
    条目顺序 / 压缩方式 / 时间戳 / 属性均沿用原 APK。

    2026-09-28 实测：本实现重打包 3652MB 的 APK 仅 **5.2s**（Java ZipOutputStream 版 8.1s），
    且省掉 javac 依赖；产物经 Java `ZipFile` 校验合法（size/magic 正确）。
    """
    ZIP64_LIMIT = zipfile.ZIP64_LIMIT    # 模块级已提到 4GB（ZIP32 上限），见文件头说明
    replace = {name: Path(path) for name, path in replacements}
    missing = [n for n in replace if not replace[n].exists()]
    if missing:
        raise SystemExit(f"待替换文件不存在：{missing}")
    if out_apk.exists():
        out_apk.unlink()

    n_keep = n_drop = n_rep = 0
    with zipfile.ZipFile(apk) as zin, \
            zipfile.ZipFile(out_apk, "w", zipfile.ZIP_STORED, allowZip64=True) as zout:
        for info in zin.infolist():
            name = info.filename
            if name.startswith("META-INF/") and name.upper().endswith(
                    (".MF", ".SF", ".RSA", ".DSA", ".EC")):
                n_drop += 1                      # 旧签名必须剔除
                continue

            method = info.compress_type
            if name in replace:
                src_path = replace[name]
                plain_size = src_path.stat().st_size
                src = open(src_path, "rb")
                if plain_size > (100 << 20):
                    method = zipfile.ZIP_STORED  # 大文件强制 STORED（Godot 靠 mmap 直读）
                n_rep += 1
            else:
                plain_size = info.file_size
                src = zin.open(info)
                n_keep += 1

            try:
                zi = zipfile.ZipInfo(name, date_time=info.date_time)
                zi.compress_type = method
                zi.external_attr = info.external_attr
                zi.internal_attr = info.internal_attr
                zi.create_system = info.create_system
                # ⚠ **只对确实需要 ZIP64 的条目**传 force_zip64：
                #    若给所有条目都加（LFH size 写成 0xFFFFFFFF + ZIP64 extra），
                #    apksig 会读不出 AndroidManifest.xml（报 "Failed to read
                #    AndroidManifest.xml"，2026-09-28 实测踩到）。
                #    需要 ZIP64 的条件：未压缩大小 或 当前写入偏移 ≥ 2^31-1。
                need_zip64 = plain_size > ZIP64_LIMIT or zout.fp.tell() > ZIP64_LIMIT
                with zout.open(zi, "w", force_zip64=need_zip64) as dst:
                    shutil.copyfileobj(src, dst, 1 << 22)
            finally:
                src.close()

    if not out_apk.exists():
        raise SystemExit(f"重打包失败，没生成：{out_apk}")
    print(f"[v] Python 重打包完成：保留 {n_keep} / 替换 {n_rep} / 剔除旧签名 {n_drop}")


# ===================== 步骤 7：校验 =====================
def verify_packed(apk: Path):
    z = zipfile.ZipFile(apk)
    info = z.getinfo(PCK_ENTRY)
    if info.compress_type != zipfile.ZIP_STORED:
        raise SystemExit(f"✗ {PCK_ENTRY} 被压缩成 DEFLATED（Godot mmap 会失效，游戏卡死 splash）")
    if z.testzip() is not None:
        raise SystemExit("✗ ZIP 完整性校验失败")
    manifest = z.read("AndroidManifest.xml")
    txt = manifest.decode("utf-16-le", errors="ignore")
    missing = [p for p in PERMISSIONS if p not in txt]
    if missing:
        raise SystemExit(f"✗ Manifest 缺权限声明：{missing}")
    print(f"[v] 校验通过：{PCK_ENTRY} STORED + zip 完整 + {len(PERMISSIONS)} 权限声明")


# ===================== 步骤 8：签名 =====================
def sign(apk: Path, out_dir: Path, ks_pass: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    print("[i] 签名 + zipalign（uber-apk-signer + 外置 zipalign）…")
    run([str(JAVA), "-jar", str(UBER_APK_SIGNER), "-a", str(apk), "-o", str(out_dir),
         "--ks", str(KEYSTORE), "--ksAlias", KEYSTORE_ALIAS,
         "--ksPass", ks_pass, "--ksKeyPass", ks_pass,
         "--allowResign", "--zipAlignPath", str(ZIPALIGN)])
    signed = out_dir / (apk.stem + "-aligned-signed.apk")
    if not signed.exists():
        raise SystemExit(f"签名后没找到：{signed}")
    if signed.stat().st_size < 1 << 30:   # < 1GB 视为不完整（正常约 3.4GB）
        raise SystemExit(f"签名产物异常偏小（{signed.stat().st_size / 2**20:.1f} MB），签名可能失败")
    return signed


# ===================== 步骤 9：安装（>2GB 必须 push + pm install） =====================
def install_apk(apk: Path, serial: str, grant: bool):
    print("[i] 安装到手机（push + pm install，禁用 adb install 流式/增量）…")
    base = [str(ADB)] + (["-s", serial] if serial else [])
    run(base + ["push", str(apk), REMOTE_TMP])
    local_md5 = md5_of(apk)
    out = subprocess.run(base + ["shell", "md5sum", REMOTE_TMP],
                         capture_output=True, text=True).stdout
    remote_md5 = out.split()[0] if out.split() else ""
    if local_md5 != remote_md5:
        raise SystemExit(f"✗ push 后 md5 不一致：local={local_md5} remote={remote_md5}")
    print(f"[v] md5 一致：{local_md5}")
    run(base + ["shell", "pm", "install", "-r", "-t", REMOTE_TMP])
    if grant:
        run(base + ["shell", "appops", "set", PKG_NAME, "MANAGE_EXTERNAL_STORAGE", "allow"])
        run(base + ["shell", "appops", "set", "--uid", "10435",
                    "MANAGE_EXTERNAL_STORAGE", "allow"])
        print("[v] 已授予 MANAGE_EXTERNAL_STORAGE（appops allow）")
    else:
        st = subprocess.run(base + ["shell", "appops", "get", PKG_NAME,
                                    "MANAGE_EXTERNAL_STORAGE"],
                            capture_output=True, text=True).stdout.strip()
        print(f"[i] MANAGE 授权状态（免授权形态保持 default 即可）：{st.splitlines()[-1] if st else st}")
    run(base + ["shell", "rm", "-f", REMOTE_TMP])
    print("[v] 安装完成")


# ===================== main =====================
def main():
    ap = argparse.ArgumentParser(description="一键修改 YierPai.apk 存档路径并重打包签名（可安装）")
    ap.add_argument("--orig", default=str(DEFAULT_ORIG), help="原始游戏 APK 路径（可含空格）")
    ap.add_argument("--dir", default=r"D:\Downloads\temp", help="输出目录")
    ap.add_argument("--file", default="YierPai_game-signed.apk", help="最终输出文件名")
    ap.add_argument("--work", default=r"D:\Downloads\temp\bg_work",
                    help="工作目录（必须无空格；gdre_tools 会截断含空格路径）")
    ap.add_argument("--gd", default=None,
                    help="可选：外部 local_save_manager.gd（默认从原包现场恢复原版再最小改动）")
    ap.add_argument("--save-root", default=SAVE_ROOT, help="SAVE_ROOT 覆盖路径")
    ap.add_argument("--ks-pass", default=KS_PASS, help="lingcraft.jks 密钥库密码")
    ap.add_argument("--skip-sign", action="store_true", help="只重打包不签名")
    ap.add_argument("--install", action="store_true", help="构建后自动装到手机")
    ap.add_argument("--serial", default="92cbcbdb", help="adb 设备 serial")
    ap.add_argument("--grant", action="store_true", help="安装后授予 MANAGE（默认免授权形态）")
    ap.add_argument("--clean-work", default=True, action="store_true",
                    help="结束后清理工作目录（默认开启；用 --keep-work 保留中间产物）")
    ap.add_argument("--keep-work", action="store_true", help="保留工作目录（默认会清理）")
    args = ap.parse_args()

    apk = Path(args.orig).resolve()
    if not apk.exists():
        raise SystemExit(f"APK 不存在：{apk}")
    if " " in str(Path(args.work).resolve()):
        raise SystemExit("工作目录路径不能含空格（gdre_tools 会截断路径）")

    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    pck = work / "original.sparsepck"
    patched_pck = work / "patched.sparsepck"
    repacked = work / "repacked.apk"

    try:
        # 1) 抽 pck
        extract_pck(apk, pck)

        # 2) 取【原版】脚本源码：默认现场从 pck 恢复（保证改动最小、零死代码）；
        #    --gd 仅在需要指定外部脚本时使用（高级用法）
        if args.gd:
            gd = work / (SAVE_SCRIPT_REL.split("/")[-1] + ".gd")
            shutil.copy2(Path(args.gd), gd)
            print(f"[i] 使用外部 gd：{args.gd}")
        else:
            rec = recover_scripts(pck, work / "recovered")
            gd = rec / (SAVE_SCRIPT_REL + ".gd")
            if not gd.exists():
                raise SystemExit(f"恢复后没找到脚本：{gd}")
        patch_save_root(gd, args.save_root)

        # 3) 编译 → 打回 pck
        save_gdc = compile_gdc(gd, work / "compiled")
        patch_pck(pck, [(save_gdc, "res://" + SAVE_SCRIPT_REL.replace("\\", "/") + ".gdc")],
                  patched_pck)

        # 4) Manifest 补权限（从原始 APK 读 AXML）
        with zipfile.ZipFile(apk) as z:
            manifest_orig = z.read("AndroidManifest.xml")
        manifest_new = patch_manifest_bytes(manifest_orig, PERMISSIONS)
        manifest_bin = work / "patched_manifest.bin"
        manifest_bin.write_bytes(manifest_new)

        # 4.5) dex 注入：GodotActivity.onCreate 启动即引导"所有文件访问"授权（秒弹）
        dex_pair = patch_dex_permission(apk, work)

        # 5) 重打包（一次替换 pck + manifest [+ dex] 条目）
        replacements = [(PCK_ENTRY, patched_pck),
                        ("AndroidManifest.xml", manifest_bin)]
        if dex_pair:
            replacements.append(dex_pair)
        repack_apk(apk, replacements, repacked, work)

        # 6) 校验
        verify_packed(repacked)

        # 7) 签名 + 输出
        if args.skip_sign:
            final = repacked
        else:
            final = sign(repacked, work / "signed", args.ks_pass or KS_PASS)
        out = Path(args.dir) / args.file
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(final, out)
        print(f"[v] 完成：{out}（{out.stat().st_size / 2**30:.2f} GB）")

        # 8) 可选安装
        if args.install:
            install_apk(out, args.serial, args.grant)
    finally:
        # 默认清理工作目录（中间产物含 2 份 3.6G sparsepck，留着很占空间）；
        # 用 --keep-work 可保留以便排查。rmtree 带容错：万一删除被沙箱拦截，
        # 只提示不影响已经产出的 APK。
        if args.clean_work and not args.keep_work:
            rmtree_safe(work, "工作目录")
            print("[i] 已清理工作目录")
        else:
            print(f"[i] 工作目录保留：{work}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"[x] 失败：{e}", file=sys.stderr)
        sys.exit(1)
