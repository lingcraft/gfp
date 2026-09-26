#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py — Godot 存档解密 / 加密回写工具（纯 Python，不再依赖 godot.exe）。

完全复刻 Godot 4 引擎的三个关键环节：
  1. FileAccessEncrypted 加密容器格式（core/io/file_access_encrypted.cpp）
      磁盘布局： [magic "GDEC"][md5 16B][length 8B][IV 16B][AES-256-CFB128 加密数据(补齐到16)]
  2. Variant 二进制序列化（core/io/marshalls.cpp 的 encode_variant / decode_variant）
     存储流：  [uint32 长度][编码后的 Variant 字节]
  3. 密钥派生与容器字典壳（复刻游戏 source/save.gd LocalSaveManagerNode）
     key = sha256( "pepper|应用名|档案id" )，容器 = { "magic", "container_version", "payload" }

依赖：pycryptodome（已在 project(pyproject.toml) 声明）。

用法：
    python main.py list                        # 列出 saves/ 下的所有账号
    python main.py decrypt [账号名|序号]        # 解密该账号的 save.dat → <账号名>.json
    python main.py encrypt [账号名|序号]        # 用编辑后的 <账号名>.json 加密回写该账号存档
    python main.py                              # 交互菜单（选账号 → 解密/回写/返回上一级/退出，操作后不退出）

账号自动发现：saves/ 下的每个子目录 = 一个账号；当前登录账号取自
login_credentials.cfg 的 profile_name，密钥派生用各账号自己的 encryption_id。
"""

import os
import sys
import json
import struct
import hashlib
import configparser
from pathlib import Path
from typing import Any

# Windows 控制台默认是 GBK，无法打印 emoji/部分字符；强制 UTF-8 输出避免崩溃。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

# ==================== 核心配置与目录自动发现（对齐游戏 save.gd） ====================
SAVE_ENCRYPTION_PEPPER = "d8830e54d5a743a9815967d2a7a9bc48f89de2c145ef40c3b69607f948cf413e"
APPLICATION_NAME = "YierPai"            # 游戏的 application/config/name，用于密钥派生
USER_DATA_DIR_NAME = "YierPai"          # Godot 用户数据目录名（通常 == 应用名）
SAVE_CONTAINER_MAGIC = "YIERPAI_ENCRYPTED_SAVE"
SAVE_CONTAINER_VERSION = 1

ENCRYPTED_HEADER_MAGIC = b"GDEC"        # 0x43454447 的小端字节序

# 关键目录（全部基于 pathlib）

APPDATA = Path(os.environ["appdata"])
APP_USERDATA = APPDATA / "Godot" / "app_userdata" / USER_DATA_DIR_NAME
SAVES_DIR = APP_USERDATA / "saves"          # 每个子目录 = 一个账号的存档数据
LOGIN_CFG_PATH = APP_USERDATA / "login_credentials.cfg"  # 当前登录的账号信息


# ==================== 账号（存档档案）模型与自动发现 ====================
class SaveProfile:
    """saves/ 下的一个账号子目录：含 save.dat 与 profile.cfg。"""

    def __init__(self, name, directory):
        self.name = name
        self.dir = Path(directory)
        self.profile_cfg = self.dir / "profile.cfg"
        self.save_file = self.dir / "save.dat"
        self.output_json = Path.cwd() / f"{name}.json"

    def __repr__(self):
        return f"<SaveProfile {self.name!r}>"

    @property
    def encryption_id(self):
        """该账号用于密钥派生的 id（profile.cfg 的 encryption_id，缺省则用档案名）。"""
        return read_cfg_value(self.profile_cfg, "Profile", "encryption_id") or self.name

    def save_key(self):
        """复刻 save.gd get_save_key：sha256(pepper|应用名|档案id)。"""
        raw = f"{SAVE_ENCRYPTION_PEPPER}|{APPLICATION_NAME}|{self.encryption_id}".encode("utf-8")
        return hashlib.sha256(raw).digest()


def read_cfg_value(cfg_path, section, key):
    """从 Godot ConfigFile（INI 风格）读取 [section] 里的 key=value（去掉引号），读不到返回 None。"""
    parser = configparser.ConfigParser(allow_no_value=True)
    try:
        parser.read(Path(cfg_path), encoding="utf-8")
    except (OSError, configparser.Error):
        return None
    value = parser.get(section, key, fallback=None)
    if value is None:
        return None
    return value.strip().strip('"').strip("'")


def list_profiles():
    """自动枚举 saves/ 下所有账号子目录（按名字排序）。"""
    if not SAVES_DIR.is_dir():
        return []
    return sorted(
        (SaveProfile(p.name, p) for p in SAVES_DIR.iterdir() if p.is_dir()),
        key=lambda x: x.name,
    )


def active_profile_name():
    """登录凭证里当前选中的账号名（login_credentials.cfg 的 profile_name）。"""
    return read_cfg_value(LOGIN_CFG_PATH, "Login", "profile_name")



# ==================== AES-256-CFB128（使用 pycryptodome 库） ====================
try:
    from Crypto.Cipher import AES
except ImportError:  # pragma: no cover
    AES = None


def require_aes():
    if AES is None:
        sys.exit(
            "[-] 缺少 pycryptodome 库。请先安装（项目已在 pyproject.toml 声明此依赖）：\n"
            "    pip install pycryptodome"
        )


def dir_encrypt(key, iv, data):
    """AES-256-CFB128 加密。"""
    require_aes()
    return AES.new(key, AES.MODE_CFB, iv=iv, segment_size=128).encrypt(data)


def dir_decrypt(key, iv, data):
    """AES-256-CFB128 解密。"""
    require_aes()
    return AES.new(key, AES.MODE_CFB, iv=iv, segment_size=128).decrypt(data)


# ==================== 加密容器文件的读写 (file_access_encrypted.cpp) ====================
def read_encrypted_file(path, key):
    """解出并返回原始存储流（即 store_var 的产物：[uint32 len][Variant 字节]）。"""
    with open(path, "rb") as f:
        blob = f.read()

    if len(blob) < 44:
        raise ValueError("文件过小，不是合法的加密存档。")
    if blob[0:4] != ENCRYPTED_HEADER_MAGIC:
        raise ValueError("magic 不匹配，不是 Godot open_encrypted 生成的存档。")
    md5_expected = blob[4:20]
    length = struct.unpack_from("<Q", blob, 20)[0]
    iv = blob[28:44]
    ct = blob[44:]

    padded = (length + 15) // 16 * 16
    if len(ct) < padded:
        raise ValueError("加密数据不完整。")
    ct = ct[:padded]

    plaintext = dir_decrypt(key, iv, ct)[:length]

    if hashlib.md5(plaintext).digest() != md5_expected:
        # 说明密钥不对（或文件损坏 / 档案 id 有变）
        raise ValueError("MD5 校验失败：解密密钥可能已变化（例如档案 encryption_id 改变）或文件损坏。")
    return plaintext


def write_encrypted_file(path, key, raw_stream):
    """把 store_var 的原始存储流包成加密容器写盘。"""
    iv = os.urandom(16)
    length = len(raw_stream)
    padded = (length + 15) // 16 * 16
    padded_data = raw_stream + b"\x00" * (padded - length)
    ct = dir_encrypt(key, iv, padded_data)
    digest = hashlib.md5(raw_stream).digest()
    with open(path, "wb") as f:
        f.write(ENCRYPTED_HEADER_MAGIC)
        f.write(digest)
        f.write(struct.pack("<Q", length))
        f.write(iv)
        f.write(ct)


# ==================== Variant 二进制编解码 (marshalls.cpp) ====================
# Variant::Type 枚举（core/variant/variant.h）
NIL, BOOL, INT, FLOAT, STRING, VECTOR2, VECTOR2I, RECT2, RECT2I, VECTOR3, VECTOR3I, \
    TRANSFORM2D, VECTOR4, VECTOR4I, PLANE, QUATERNION, AABB, BASIS, TRANSFORM3D, \
    PROJECTION, COLOR, STRING_NAME, NODE_PATH, RID, OBJECT, CALLABLE, SIGNAL, \
    DICTIONARY, ARRAY, PACKED_BYTE_ARRAY, PACKED_INT32_ARRAY, PACKED_INT64_ARRAY, \
    PACKED_FLOAT32_ARRAY, PACKED_FLOAT64_ARRAY, PACKED_STRING_ARRAY, PACKED_VECTOR2_ARRAY, \
    PACKED_VECTOR3_ARRAY, PACKED_COLOR_ARRAY, PACKED_VECTOR4_ARRAY = range(39)

INTERNAL_MAX = 2**31 - 1
INTERNAL_MIN = -2**31
HEADER_64 = 1 << 16           # 64 位 / 浮点用双精度标记
OBJECT_AS_ID = 1 << 16
CONTAINER_TYPE_KIND_MASK = 0b11
TYPED_DICT_KEY_SHIFT = 16
TYPED_DICT_VALUE_SHIFT = 18
TYPED_ARRAY_SHIFT = 16
MAX_RECURSION = 1024


class Reader:
    __slots__ = ("data", "pos")

    def __init__(self, data):
        self.data = data
        self.pos = 0

    def need(self, n):
        if self.pos + n > len(self.data):
            raise ValueError("Variant 流不完整（数据被截断）。")

    def u32(self):
        self.need(4)
        v = struct.unpack_from("<I", self.data, self.pos)[0]
        self.pos += 4
        return v

    def u64(self):
        self.need(8)
        v = struct.unpack_from("<Q", self.data, self.pos)[0]
        self.pos += 8
        return v

    def i64(self):
        self.need(8)
        v = struct.unpack_from("<q", self.data, self.pos)[0]
        self.pos += 8
        return v

    def f32(self):
        self.need(4)
        v = struct.unpack_from("<f", self.data, self.pos)[0]
        self.pos += 4
        return v

    def f64(self):
        self.need(8)
        v = struct.unpack_from("<d", self.data, self.pos)[0]
        self.pos += 8
        return v

    def read(self, n):
        self.need(n)
        v = self.data[self.pos:self.pos + n]
        self.pos += n
        return v

    def godot_string(self):
        """decode_string：uint32 长度 + UTF-8 字节 + 补齐到 4 字节对齐。"""
        n = self.u32()
        pad = (4 - n % 4) % 4
        b = self.read(n)
        self.read(pad)
        return b.decode("utf-8")


def decode_variant(r, depth=0) -> Any:
    """解出一个 Variant。返回类型不定（None/bool/int/float/str/list/dict/...），故用 Any。"""
    if depth > MAX_RECURSION:
        raise RecursionError("Variant 嵌套过深。")

    header = r.u32()
    vtype = header & 0xFF
    is64 = bool(header & HEADER_64)

    if vtype == NIL:
        return None
    if vtype == BOOL:
        return bool(r.u32())
    if vtype == INT:
        if is64:
            raw = r.u64()
            return raw - 2**64 if raw >= 2**63 else raw
        return struct.unpack("<i", r.read(4))[0]
    if vtype == FLOAT:
        return r.f64() if is64 else r.f32()
    if vtype in (STRING, STRING_NAME):
        return r.godot_string()

    # 数学类型：返回元组 / 若干字段
    if vtype == VECTOR2:
        return ((r.f64(), r.f64()) if is64 else (r.f32(), r.f32()))
    if vtype == VECTOR2I:
        return (struct.unpack("<i", r.read(4))[0], struct.unpack("<i", r.read(4))[0])
    if vtype == VECTOR3:
        return ((r.f64(), r.f64(), r.f64()) if is64 else (r.f32(), r.f32(), r.f32()))
    if vtype == VECTOR3I:
        return (struct.unpack("<i", r.read(4))[0], struct.unpack("<i", r.read(4))[0], struct.unpack("<i", r.read(4))[0])
    if vtype == VECTOR4:
        return ((r.f64(), r.f64(), r.f64(), r.f64()) if is64 else (r.f32(), r.f32(), r.f32(), r.f32()))
    if vtype == VECTOR4I:
        return tuple(struct.unpack("<i", r.read(4))[0] for _ in range(4))
    if vtype == PLANE:
        return ((r.f64(), r.f64(), r.f64(), r.f64()) if is64 else (r.f32(), r.f32(), r.f32(), r.f32()))
    if vtype == QUATERNION:
        return ((r.f64(), r.f64(), r.f64(), r.f64()) if is64 else (r.f32(), r.f32(), r.f32(), r.f32()))
    if vtype == COLOR:
        return (r.f32(), r.f32(), r.f32(), r.f32())
    if vtype == RECT2:
        sub = (r.f64, r.f64, r.f64, r.f64) if is64 else (r.f32, r.f32, r.f32, r.f32)
        return tuple(fn() for fn in sub)
    if vtype == RECT2I:
        data = [struct.unpack("<i", r.read(4))[0] for _ in range(4)]
        return ((data[0], data[1]), (data[2], data[3]))
    if vtype == AABB:
        sub = (r.f64,) * 6 if is64 else (r.f32,) * 6
        return tuple(fn() for fn in sub)
    if vtype == BASIS:
        sub = (r.f64,) * 9 if is64 else (r.f32,) * 9
        return tuple(fn() for fn in sub)
    if vtype == TRANSFORM2D:
        sub = (r.f64,) * 6 if is64 else (r.f32,) * 6
        return tuple(fn() for fn in sub)
    if vtype == TRANSFORM3D:
        sub = (r.f64,) * 12 if is64 else (r.f32,) * 12
        return tuple(fn() for fn in sub)
    if vtype == PROJECTION:
        sub = (r.f64,) * 16 if is64 else (r.f32,) * 16
        return tuple(fn() for fn in sub)
    if vtype == RID:
        return r.u64()

    if vtype == NODE_PATH:
        n = r.u32()
        if not (n & 0x80000000):
            raise ValueError("旧版 NodePath 编码不支持。")
        namecount = n & 0x7FFFFFFF
        subnamecount = r.u32()
        np_flags = r.u32()
        if np_flags & 2:
            subnamecount += 1
        parts = [r.godot_string() for _ in range(namecount + subnamecount)]
        return {"name": parts[:namecount], "subname": parts[namecount:], "absolute": bool(np_flags & 1)}

    if vtype == OBJECT:
        if header & OBJECT_AS_ID:
            obj_id = r.u64()
            return None if obj_id == 0 else {"__object_id": obj_id}
        raise ValueError("完整对象编码在不允许对象的环境中不受支持。")

    if vtype == CALLABLE:
        return None
    if vtype == SIGNAL:
        name = r.godot_string()
        obj_id = r.u64()
        return {"__signal": name, "__object_id": obj_id}

    if vtype == DICTIONARY:
        decode_container_type(r, (header >> TYPED_DICT_KEY_SHIFT) & CONTAINER_TYPE_KIND_MASK)
        decode_container_type(r, (header >> TYPED_DICT_VALUE_SHIFT) & CONTAINER_TYPE_KIND_MASK)
        count = r.u32() & 0x7FFFFFFF
        d: dict[Any, Any] = {}
        for _ in range(count):
            k = decode_variant(r, depth + 1)
            v = decode_variant(r, depth + 1)
            try:
                d[k] = v
            except TypeError:
                # Godot 的键理论上可以是任意 Variant；万一解出 Python 不可哈希的
                # （如 Array / Dictionary），退化成字符串键，避免整个存档解码失败。
                d[repr(k)] = v
        return d

    if vtype == ARRAY:
        decode_container_type(r, (header >> TYPED_ARRAY_SHIFT) & CONTAINER_TYPE_KIND_MASK)
        count = r.u32() & 0x7FFFFFFF
        return [decode_variant(r, depth + 1) for _ in range(count)]

    if vtype == PACKED_BYTE_ARRAY:
        count = r.u32()
        data = r.read(count)
        r.read((4 - count % 4) % 4)
        return data
    if vtype == PACKED_INT32_ARRAY:
        count = r.u32()
        return [struct.unpack("<i", r.read(4))[0] for _ in range(count)]
    if vtype == PACKED_INT64_ARRAY:
        count = r.u32()
        return [struct.unpack("<q", r.read(8))[0] for _ in range(count)]
    if vtype == PACKED_FLOAT32_ARRAY:
        count = r.u32()
        return [r.f32() for _ in range(count)]
    if vtype == PACKED_FLOAT64_ARRAY:
        count = r.u32()
        return [r.f64() for _ in range(count)]
    if vtype == PACKED_STRING_ARRAY:
        count = r.u32()
        return [r.godot_string() for _ in range(count)]
    if vtype == PACKED_VECTOR2_ARRAY:
        count = r.u32()
        f = r.f64 if is64 else r.f32
        return [(f(), f()) for _ in range(count)]
    if vtype == PACKED_VECTOR3_ARRAY:
        count = r.u32()
        f = r.f64 if is64 else r.f32
        return [(f(), f(), f()) for _ in range(count)]
    if vtype == PACKED_VECTOR4_ARRAY:
        count = r.u32()
        f = r.f64 if is64 else r.f32
        return [(f(), f(), f(), f()) for _ in range(count)]
    if vtype == PACKED_COLOR_ARRAY:
        count = r.u32()
        return [(r.f32(), r.f32(), r.f32(), r.f32()) for _ in range(count)]

    raise ValueError(f"未知 Variant 类型 {vtype}")


def decode_container_type(r, kind):
    """消费容器类型的字节（类型信息本身，不影响 JSON 值）。"""
    if kind == 0b00:          # CONTAINER_TYPE_KIND_NONE
        return
    if kind == 0b01:          # BUILTIN：一个 uint32 内建类型索引
        r.u32()
    elif kind in (0b10, 0b11):  # CLASS_NAME / SCRIPT：一个字符串
        r.godot_string()
    else:
        raise ValueError("非法的容器类型。")


# ==================== Variant 编码（marshalls.cpp encode_variant，纯 JSON 类型） ====================
class Writer:
    __slots__ = ("buf",)

    def __init__(self):
        self.buf = bytearray()

    def u32(self, v):
        self.buf += struct.pack("<I", v & 0xFFFFFFFF)

    def u64(self, v):
        self.buf += struct.pack("<Q", v & 0xFFFFFFFFFFFFFFFF)

    def f32(self, v):
        self.buf += struct.pack("<f", v)

    def f64(self, v):
        self.buf += struct.pack("<d", v)

    def raw(self, b):
        self.buf += b

    def value(self):
        return bytes(self.buf)


def encode_string(s):
    b = s.encode("utf-8")
    return struct.pack("<I", len(b)) + b + b"\x00" * ((4 - len(b) % 4) % 4)


def encode_variant(obj):
    """把纯 JSON 结构（None/bool/int/float/str/list/dict）编码为 Godot Variant 字节流。"""
    w = Writer()

    if obj is None:
        w.u32(NIL)
    elif isinstance(obj, bool):
        w.u32(BOOL)
        w.u32(1 if obj else 0)
    elif isinstance(obj, int):
        header = INT
        if not (INTERNAL_MIN <= obj <= INTERNAL_MAX):
            header |= HEADER_64
        w.u32(header)
        if header & HEADER_64:
            w.u64(obj)
        else:
            w.u32(obj)
    elif isinstance(obj, float):
        header = FLOAT
        try:
            f32 = struct.unpack("<f", struct.pack("<f", obj))[0]
        except OverflowError:
            f32 = float("inf")
        if float(f32) != obj:
            header |= HEADER_64
        w.u32(header)
        if header & HEADER_64:
            w.f64(obj)
        else:
            w.f32(f32)
    elif isinstance(obj, str):
        w.u32(STRING)
        w.raw(encode_string(obj))
    elif isinstance(obj, (list, tuple)):
        w.u32(ARRAY)
        w.u32(len(obj))
        for e in obj:
            w.raw(encode_variant(e))
    elif isinstance(obj, dict):
        w.u32(DICTIONARY)
        w.u32(len(obj))
        for k, v in obj.items():
            w.raw(encode_variant(k))
            w.raw(encode_variant(v))
    else:
        raise TypeError(f"无法编码的 Variant 类型：{type(obj).__name__}")

    return w.value()


# ==================== 解码结果 → 纯 JSON 结构 ====================
def json_key(k):
    if isinstance(k, str):
        return k
    if isinstance(k, bool):
        return "true" if k else "false"
    return str(k)


def to_json_safe(obj):
    """把解码出的 Variant（可能含字节串 / 元组）转成 JSON 可安全序列化的结构。"""
    if isinstance(obj, bytes):
        return list(obj)
    if isinstance(obj, tuple):
        return [to_json_safe(x) for x in obj]
    if isinstance(obj, dict):
        return {json_key(k): to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_json_safe(x) for x in obj]
    return obj


# ==================== 高层：解密 / 加密 ====================
def raw_stream_to_envelope(raw_stream):
    r = Reader(raw_stream)
    length = r.u32()
    variant_bytes = r.read(length)
    if len(variant_bytes) != length:
        raise ValueError("存储流中的 Variant 长度与声明不符。")
    return decode_variant(Reader(variant_bytes))


def envelope_to_raw_stream(envelope):
    var_bytes = encode_variant(envelope)
    return struct.pack("<I", len(var_bytes)) + var_bytes


def decrypt_save(profile):
    if not profile.save_file.exists():
        raise FileNotFoundError(f"找不到加密存档：\n    {profile.save_file}")
    raw_stream = read_encrypted_file(profile.save_file, profile.save_key())
    envelope = raw_stream_to_envelope(raw_stream)

    if not isinstance(envelope, dict) or "payload" not in envelope:
        raise ValueError("解密后不是预期的容器字典（缺少 payload 字段）。")

    magic = str(envelope.get("magic", ""))
    if magic != SAVE_CONTAINER_MAGIC:
        print(f"[-] 提示：容器 magic 为 {magic!r}，与预期 {SAVE_CONTAINER_MAGIC!r} 不同。")

    payload = to_json_safe(envelope["payload"])
    with open(profile.output_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent="\t", sort_keys=True, allow_nan=False)

    print("-" * 50)
    print(f"[🎉] 成功：解密提取完成！（账号：{profile.name}）")
    print(f"[📂] 明文 JSON 存档已保存在：\n    {profile.output_json}")
    print(f"[🔑] 密钥：sha256(pepper|{APPLICATION_NAME}|{profile.encryption_id})，AES-256-CFB")


def encrypt_save(profile):
    if not profile.output_json.exists():
        raise FileNotFoundError(f"当前目录找不到待写回的明文 JSON：\n    {profile.output_json}")

    with open(profile.output_json, "r", encoding="utf-8") as f:
        payload = json.load(f)

    container = {
        "magic": SAVE_CONTAINER_MAGIC,
        "container_version": SAVE_CONTAINER_VERSION,
        "payload": payload,
    }
    write_encrypted_file(profile.save_file, profile.save_key(), envelope_to_raw_stream(container))

    print("-" * 50)
    print(f"[🔥] 成功：修改同步完成！（账号：{profile.name}）")
    print(f"[🎮] 修改后的 {profile.name}.json 已重新打包并写回：\n    {profile.save_file}")


def print_profiles_list():
    profiles = list_profiles()
    if not profiles:
        print("没有发现任何账号（saves/ 目录为空）。")
        return
    active = active_profile_name()
    print("账号列表：")
    for p in profiles:
        mark = "   <- 当前登录" if p.name == active else ""
        print(f"  {p.name}{mark}")


def select_profile():
    """交互式列出所有账号，返回用户选中的 SaveProfile（默认当前登录账号）。

    返回：
        SaveProfile —— 用户选中了账号
        ""          —— 用户选择退出程序
        None        —— 没有可用账号
    """
    profiles = list_profiles()
    if not profiles:
        print("[×] 没有发现任何账号：saves/ 目录为空。")
        return None
    active = active_profile_name()
    while True:
        print(f"\n共发现 {len(profiles)} 个账号：")
        default_idx = 1
        for i, p in enumerate(profiles, 1):
            tag = "   <- 当前登录" if p.name == active else ""
            if p.name == active:
                default_idx = i
            print(f"  {i}. {p.name}{tag}")
        print("  0. 退出程序")
        choice = input(f"请选择账号序号（回车默认 {default_idx}）：").strip().lower()
        if choice in ("0", "q", "quit", "exit"):
            print("[*] 已退出。")
            return ""
        idx = int(choice) if choice.isdigit() else default_idx
        if not (1 <= idx <= len(profiles)):
            print("[-] 序号无效，请重新输入。")
            continue
        return profiles[idx - 1]


def profile_menu(profile):
    """单个账号的操作菜单：一键解密 / 一键回写 / 返回上一级 / 退出。

    执行完解密或回写后停留在当前菜单，不退出程序。
    返回 True 表示返回上一级（重新选择账号），False 表示退出程序。
    """
    while True:
        print()
        print(f"当前账号：{profile.name}")
        print(f"存档文件：{profile.save_file}")
        print("1. [一键解密] 导出明文 JSON")
        print("2. [一键回写] 编辑后加密覆盖回存档")
        print("3. 返回上一级（重新选择账号）")
        print("0. 退出程序")
        choice = input("请输入功能编号：").strip().lower()

        if choice == "1":
            run_decrypt(profile)
        elif choice == "2":
            confirm = input(
                f"⚠️ 确认用 {profile.name}.json 覆盖账号【{profile.name}】当前存档？(y/n): "
            ).strip().lower()
            if confirm == "y":
                run_encrypt(profile)
            else:
                print("[*] 操作已取消。")
        elif choice == "3":
            return True
        elif choice in ("0", "q", "quit", "exit"):
            return False
        else:
            print("[-] 无效选项，请重新输入。")


def resolve_profile(arg):
    """按命令行参数（账号名或序号）或当前登录账号选定 SaveProfile。"""
    profiles = list_profiles()
    if not profiles:
        print("[-] 没有发现任何账号：saves/ 目录为空。")
        return None
    if arg:
        for i, p in enumerate(profiles, 1):
            if p.name == arg or str(i) == arg:
                return p
        print(f"[-] 找不到账号 {arg!r}。可用账号：{', '.join(p.name for p in profiles)}")
        return None
    active = active_profile_name()
    for p in profiles:
        if p.name == active:
            return p
    return profiles[0]


def run_decrypt(profile):
    try:
        decrypt_save(profile)
        return 0
    except FileNotFoundError as e:
        print(f"[-] 错误：{e}")
    except ValueError as e:
        print(f"[-] 错误：{e}")
    except RecursionError as e:
        print(f"[-] 错误：{e}")
    except Exception as e:
        print(f"[-] 未知错误：{e}")
    return 1


def run_encrypt(profile):
    try:
        encrypt_save(profile)
        return 0
    except FileNotFoundError as e:
        print(f"[-] 错误：{e}")
    except (ValueError, TypeError) as e:
        print(f"[-] 错误：{e}")
    except Exception as e:
        print(f"[-] 未知错误：{e}")
    return 1


if __name__ == "__main__":
    args = sys.argv[1:]
    cmd = next((a.lower() for a in args if a.lower() in ("list", "decrypt", "encrypt")), None)
    profile_arg = next((a for a in args if a.lower() not in ("list", "decrypt", "encrypt")), None)

    if cmd == "list":
        print_profiles_list()
        sys.exit(0)

    if cmd in ("decrypt", "encrypt"):
        profile = resolve_profile(profile_arg)
        if profile is None:
            sys.exit(1)
        if cmd == "encrypt":
            confirm = input(
                f"⚠️ 回写加密会用 {profile.name}.json 覆盖账号【{profile.name}】当前存档，确认？(y/n): "
            ).strip().lower()
            if confirm != "y":
                print("[*] 操作已取消。")
                sys.exit(0)
        sys.exit(run_encrypt(profile) if cmd == "encrypt" else run_decrypt(profile))

    # 交互菜单：账号选择 → 账号操作（可返回上一级）
    print("====== Godot 4 存档一键助手（纯 Python 版 / 无需 godot.exe）======")
    print(f"存档根目录：{SAVES_DIR}")
    while True:
        profile = select_profile()
        if profile is None:  # 没有可用账号
            sys.exit(1)
        if not isinstance(profile, SaveProfile):  # "" = 用户在账号菜单选择了退出
            sys.exit(0)
        print(f"\n已选择账号：{profile.name}")
        if not profile_menu(profile):  # True=返回上一级重新选账号，False=退出
            sys.exit(0)
