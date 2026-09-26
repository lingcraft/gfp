#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用 7-Zip 的 `7z.dll` 解压 7z / rar(RAR4+RAR5) / zip / tar / gz 等全部格式。

纯标准库（ctypes）：不需要 py7zr / rarfile / unrar，也不需要外部 7z.exe。
通过 7z.dll 导出的 `CreateObject` 拿到 `IInArchive` COM 接口，在进程内解压。

对外只有两个函数（见 __all__）：
    list_names(archive)          包内文件相对路径列表（'/' 分隔，不含目录项）
    extract_all(archive, target) 整包解压，返回写入的文件数

接口与常量均取自 7-Zip 官方源码 https://github.com/ip7z/7zip ：
  CPP/7zip/Guid.txt                     接口 IID 与 handler CLSID 的编码规则
  CPP/7zip/Archive/IArchive.h           IInArchive 方法顺序 / NHandlerPropID 枚举
  CPP/7zip/Archive/ArchiveExports.cpp   CreateObject / GetHandlerProperty2 / GetIsArc
"""

import ctypes
import os
from ctypes import (POINTER, WINFUNCTYPE, Structure, byref, c_int, c_int64,
                    c_long, c_size_t, c_ubyte, c_uint, c_ulonglong, c_ushort,
                    c_void_p, cast, sizeof)
from pathlib import Path

__all__ = ["list_names", "extract_all"]

# ============================ 常量 ============================

# 属性 ID（CPP/7zip/PropID.h）
KPID_PATH = 3
KPID_IS_DIR = 6

# NArchive::NHandlerPropID（CPP/7zip/Archive/IArchive.h）
K_CLASS_ID = 1      # binary GUID in VT_BSTR
K_EXTENSION = 2
K_ADD_EXTENSION = 3

# 接口 IID（CPP/7zip/Guid.txt：{23170F69-40C1-278A-0000-00yy00xx0000}，yy=组号，xx=接口号）
# IArchive.h 组 = 06，IInArchive = 0x60。CreateObject 只认 IInArchive 与 IOutArchive(0xA0)，
# 其余（含 IID_IUnknown）一律返回 E_NOINTERFACE。解压只用 IInArchive
# —— 不能用 IOutArchive 凑数：它槽 3 是 UpdateItems，被当成 Open 调用会"假成功"。
IID_IIN_ARCHIVE = "23170F69-40C1-278A-0000-000600600000"

# IArchive.h：numItems = 0xFFFFFFFF 表示"全部文件"；NExtract::NAskMode::kExtract = 0
ALL_ITEMS = 0xFFFFFFFF
EXTRACT_MODE = 0

HRESULT = c_long
S_OK = 0
E_FAIL = 0x80004005
E_NOINTERFACE = 0x80004002
VT_BOOL = 11
VT_BSTR = 8


class SevenZipError(Exception):
    pass


# ============================ 结构体 ============================


class Guid(Structure):
    _fields_ = [("Data1", c_uint), ("Data2", c_ushort), ("Data3", c_ushort),
                ("Data4", c_ubyte * 8)]

    @classmethod
    def parse(cls, text):
        a, b, c_, d, e = text.strip().strip("{}").split("-")
        g = cls()
        g.Data1 = int(a, 16)
        g.Data2 = int(b, 16)
        g.Data3 = int(c_, 16)
        raw = bytes.fromhex(d + e)
        for i in range(8):
            g.Data4[i] = raw[i]
        return g

    @classmethod
    def from_bytes_le(cls, data):
        """从 7-Zip 返回的 16 字节内存布局还原 GUID。"""
        g = cls()
        g.Data1 = int.from_bytes(data[0:4], "little")
        g.Data2 = int.from_bytes(data[4:6], "little")
        g.Data3 = int.from_bytes(data[6:8], "little")
        for i in range(8):
            g.Data4[i] = data[8 + i]
        return g


class PropVariant(Structure):
    """只取用到的部分：vt + union（BSTR 指针 / 整数）。64 位下共 24 字节。"""
    _fields_ = [("vt", c_ushort), ("wReserved1", c_ushort), ("wReserved2", c_ushort),
                ("wReserved3", c_ushort), ("val", c_ulonglong), ("pad", c_ulonglong)]


oleaut32 = ctypes.WinDLL("oleaut32")
ole32 = ctypes.WinDLL("ole32")
sys_string_byte_len = oleaut32.SysStringByteLen
sys_string_byte_len.argtypes = [c_void_p]
sys_string_byte_len.restype = c_uint
propvariant_clear = ole32.PropVariantClear        # 注意：在 ole32，不在 oleaut32
propvariant_clear.argtypes = [POINTER(PropVariant)]
propvariant_clear.restype = c_long

# 函数原型。COM 方法第一个参数是 C++ 的 this 指针，返回 HRESULT。
QI = WINFUNCTYPE(HRESULT, c_void_p, c_void_p, POINTER(c_void_p))
ADDREF = WINFUNCTYPE(c_long, c_void_p)
RELEASE = WINFUNCTYPE(c_long, c_void_p)

# IInArchive（vtable 槽 3..7）
OPEN = WINFUNCTYPE(HRESULT, c_void_p, c_void_p, POINTER(c_ulonglong), c_void_p)
CLOSE = WINFUNCTYPE(HRESULT, c_void_p)
GET_NUM_ITEMS = WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_uint))
GET_PROPERTY = WINFUNCTYPE(HRESULT, c_void_p, c_uint, c_uint, POINTER(PropVariant))
EXTRACT = WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_uint), c_uint, c_int, c_void_p)

# IInStream：Read(3) Seek(4)；ISequentialOutStream：Write(3)
READ = WINFUNCTYPE(HRESULT, c_void_p, c_void_p, c_uint, POINTER(c_uint))
SEEK = WINFUNCTYPE(HRESULT, c_void_p, c_int64, c_uint, POINTER(c_ulonglong))
WRITE = WINFUNCTYPE(HRESULT, c_void_p, c_void_p, c_uint, POINTER(c_uint))

# IArchiveOpenCallback：SetTotal(3) SetCompleted(4)
OC_SET_TOTAL = WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_ulonglong), POINTER(c_ulonglong))
OC_SET_COMPLETED = WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_ulonglong), POINTER(c_ulonglong))

# IArchiveExtractCallback（继承 IProgress）：SetTotal(3) SetCompleted(4)
# GetStream(5) PrepareOperation(6) SetOperationResult(7)
EC_SET_TOTAL = WINFUNCTYPE(HRESULT, c_void_p, c_ulonglong)
EC_SET_COMPLETED = WINFUNCTYPE(HRESULT, c_void_p, c_ulonglong)
EC_GET_STREAM = WINFUNCTYPE(HRESULT, c_void_p, c_uint, POINTER(c_void_p), c_int)
EC_PREPARE = WINFUNCTYPE(HRESULT, c_void_p, c_int)
EC_SET_RESULT = WINFUNCTYPE(HRESULT, c_void_p, c_int)

# Func_IsArc(const Byte *p, size_t size)：由 GetIsArc 取回的函数指针
IS_ARC_FUNC = WINFUNCTYPE(c_uint, c_void_p, c_size_t)

def ok(*args):
    """无副作用的回调（进度通知等）一律返回 S_OK。"""
    return S_OK


# ============================ 基础工具 ============================


def vcall(obj_ptr, index, proto):
    """取 COM 对象 vtable 第 index 个函数指针，包装成 proto 可调用对象。"""
    vt = cast(c_void_p(obj_ptr), POINTER(c_void_p))[0]
    if not vt:
        raise SevenZipError("COM 对象 vtable 为空")
    fn = cast(c_void_p(vt + index * sizeof(c_void_p)), POINTER(c_void_p))[0]
    return proto(fn)


def release(obj_ptr):
    try:
        vcall(obj_ptr, 2, RELEASE)(c_void_p(obj_ptr))
    except Exception:
        pass


def check(hr, what):
    if hr != S_OK:
        raise SevenZipError("%s 失败 (0x%08X)" % (what, hr & 0xFFFFFFFF))


def prop_str(pv):
    if pv.vt == VT_BSTR and pv.val:
        try:
            return ctypes.wstring_at(c_void_p(pv.val)) or None
        except Exception:
            return None
    return None


def prop_bool(pv):
    return (pv.val & 0xFFFF) != 0 if pv.vt == VT_BOOL else False


def prop_guid(pv):
    """kClassID 是挂在 BSTR 上的 16 字节二进制 GUID（源码注释：binary GUID in VT_BSTR）。"""
    if not pv.val or pv.vt != VT_BSTR:
        return None
    ptr = c_void_p(pv.val)
    try:
        if sys_string_byte_len(ptr) == 16:
            return Guid.from_bytes_le(ctypes.string_at(ptr, 16))
    except Exception:
        pass
    return None


def norm_key(name):
    """包内路径 -> 安全相对路径（'/' 分隔）；空或非法返回 None。"""
    if not name:
        return None
    p = name.replace("\\", "/")
    if len(p) >= 2 and p[1] == ":":
        p = p[2:]
    parts = []
    for seg in p.lstrip("/").split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    return "/".join(parts) or None


# ============================ DLL 与格式探测 ============================

cached_dll = None


def dll_candidates():
    """7z.dll 候选位置：模块目录 > 解释器目录 > 主脚本目录。"""
    import sys
    paths = [Path(__file__).resolve().parent / "7z.dll"]
    try:
        paths.append(Path(sys.executable).resolve().parent / "7z.dll")
    except Exception:
        pass
    try:
        paths.append(Path(sys.argv[0]).resolve().parent / "7z.dll")
    except Exception:
        pass
    return paths


def load_dll():
    global cached_dll
    if cached_dll is not None:
        return cached_dll
    dll = None
    for path in dll_candidates():
        if path.is_file():
            dll = ctypes.WinDLL(str(path), winmode=0x8)
            break
    if dll is None:
        raise SevenZipError("找不到 7z.dll，已尝试：%s"
                            % "、".join(str(p) for p in dll_candidates()))
    dll.CreateObject.argtypes = [POINTER(Guid), POINTER(Guid), POINTER(c_void_p)]
    dll.CreateObject.restype = HRESULT
    dll.GetNumberOfFormats.argtypes = [POINTER(c_uint)]
    dll.GetNumberOfFormats.restype = HRESULT
    dll.GetHandlerProperty2.argtypes = [c_uint, c_uint, POINTER(PropVariant)]
    dll.GetHandlerProperty2.restype = HRESULT
    dll.GetIsArc.argtypes = [c_uint, POINTER(c_void_p)]
    dll.GetIsArc.restype = HRESULT
    cached_dll = dll
    return dll


def handler_prop(index, prop_id, read):
    """读取 handler 属性，按 read 转换取值，并负责清理 PROPVARIANT。"""
    pv = PropVariant()
    try:
        if load_dll().GetHandlerProperty2(index, prop_id, byref(pv)) != S_OK:
            return None
        return read(pv)
    finally:
        propvariant_clear(byref(pv))


def handler_is_arc(index, head):
    """用 7z.dll 的 GetIsArc 按文件头判断该 handler 是否认得这份数据（0 = 不认）。"""
    fp = c_void_p()
    if load_dll().GetIsArc(index, byref(fp)) != S_OK or not fp.value:
        return False
    try:
        return IS_ARC_FUNC(fp.value)(ctypes.create_string_buffer(head), len(head)) != 0
    except Exception:
        return False


def handler_indices(path, ext):
    """按优先级返回 handler 索引：文件头签名命中 > 扩展名命中。

    只看扩展名会被"改名包"（如 .rar 实际是 zip）骗过，故先用签名探测。
    """
    try:
        with open(path, "rb") as f:
            head = f.read(1 << 20)
    except OSError:
        head = b""

    n = c_uint(0)
    load_dll().GetNumberOfFormats(byref(n))
    by_sig, by_ext = [], []
    for i in range(n.value):
        if head and handler_is_arc(i, head):
            by_sig.append(i)
        exts = " ".join(t for t in (handler_prop(i, K_EXTENSION, prop_str),
                                    handler_prop(i, K_ADD_EXTENSION, prop_str)) if t).lower().split()
        if ext in exts:
            by_ext.append(i)
    return by_sig + [i for i in by_ext if i not in by_sig]


# ============================ 回调 COM 对象 ============================


class ComObject:
    """手工构造的 COM 对象（vtable + 引用计数）。

    Release 不做真正销毁：生命周期由 Python 侧持有，避免 7z.dll 释放后回调被触发而崩溃。
    """

    def __init__(self, methods):
        self.keep = []
        self.vt = (c_void_p * (3 + len(methods)))()
        for slot, (proto, fn) in enumerate((
                (QI, lambda this, iid, out: E_NOINTERFACE),
                (ADDREF, lambda this: 1),
                (RELEASE, lambda this: 1))):
            cb = proto(fn)
            self.vt[slot] = cast(cb, c_void_p).value
            self.keep.append(cb)
        for i, (proto, fn) in enumerate(methods):
            cb = proto(fn)
            self.vt[3 + i] = cast(cb, c_void_p).value
            self.keep.append(cb)
        self.obj = (c_void_p * 2)()
        self.obj[0] = ctypes.addressof(self.vt)
        self.obj[1] = 1
        self.ptr = ctypes.addressof(self.obj)


class InStream(ComObject):
    """IInStream：把本地文件交给 7z.dll 读。"""

    def __init__(self, path):
        self.f = open(path, "rb")
        super().__init__([(READ, self.read), (SEEK, self.seek)])

    def read(self, this, data, size, processed):
        try:
            buf = self.f.read(size)
        except Exception:
            return E_FAIL
        if buf:
            ctypes.memmove(data, buf, len(buf))
        if processed:
            processed[0] = len(buf)
        return S_OK

    def seek(self, this, offset, origin, newpos):
        try:
            self.f.seek(offset, (0, 1, 2)[origin])
        except Exception:
            return E_FAIL
        if newpos:
            newpos[0] = self.f.tell()
        return S_OK

    def close(self):
        try:
            self.f.close()
        except Exception:
            pass


class OutFileStream(ComObject):
    """ISequentialOutStream：把解压数据写进目标文件。"""

    def __init__(self, path):
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.f = open(path, "wb")
        super().__init__([(WRITE, self.write)])

    def write(self, this, data, size, processed):
        try:
            self.f.write(ctypes.string_at(data, size))
        except Exception:
            return E_FAIL
        if processed:
            processed[0] = size
        return S_OK

    def close(self):
        try:
            self.f.close()
        except Exception:
            pass


class OpenCallback(ComObject):
    """IArchiveOpenCallback：打开进度回调（rar 等格式会用到，不能省）。"""

    def __init__(self):
        super().__init__([(OC_SET_TOTAL, ok), (OC_SET_COMPLETED, ok)])


class ExtractCallback(ComObject):
    """IArchiveExtractCallback：按 index 提供输出流，把条目解到 target 目录。

    GetStream 返回空流即"跳过该项"（源码约定：目录 / 链接就是这么处理的）。
    """

    def __init__(self, items, target):
        self.items = items
        self.target = target
        self.streams = []
        self.errors = 0
        self.written = 0
        super().__init__([(EC_SET_TOTAL, ok), (EC_SET_COMPLETED, ok),
                          (EC_GET_STREAM, self.get_stream),
                          (EC_PREPARE, ok), (EC_SET_RESULT, self.set_result)])

    def get_stream(self, this, index, out, mode):
        if out:
            out[0] = None
        if mode != EXTRACT_MODE or index >= len(self.items):
            return S_OK
        name, is_dir = self.items[index]
        dest = os.path.join(self.target, name.replace("/", os.sep))
        if is_dir:
            os.makedirs(dest, exist_ok=True)
            return S_OK
        try:
            self.streams.append(OutFileStream(dest))
        except OSError as e:
            self.errors += 1
            print("[7z] 无法写入 %s：%s" % (dest, e))
            return S_OK
        self.written += 1
        if out:
            out[0] = self.streams[-1].ptr
        return S_OK

    def set_result(self, this, result):
        # 返回 S_OK：个别条目失败不中断整包，错误累计到 self.errors
        if result != S_OK:
            self.errors += 1
        return S_OK

    def close(self):
        for s in self.streams:
            s.close()
        self.streams = []


# ============================ 压缩包 ============================


class ArchiveReader:
    """用 7z.dll 打开的压缩包（7z / rar / zip / tar / gz …）。"""

    def __init__(self, path):
        self.path = str(path)
        self.arc = None
        self.stream = None
        ext = os.path.splitext(self.path)[1].lower().lstrip(".")
        order = handler_indices(self.path, ext)
        # 兜底：签名与扩展名都没命中时（扩展名被改错的包），遍历全部 handler
        n = c_uint(0)
        load_dll().GetNumberOfFormats(byref(n))
        order += [i for i in range(n.value) if i not in order]

        last = None
        for idx in order:
            clsid = handler_prop(idx, K_CLASS_ID, prop_guid)
            if clsid is None:
                continue
            arc = c_void_p()
            hr = load_dll().CreateObject(byref(clsid), byref(Guid.parse(IID_IIN_ARCHIVE)),
                                         byref(arc))
            if hr != S_OK or not arc.value:
                last = SevenZipError("CreateObject 失败 (0x%08X)" % (hr & 0xFFFFFFFF))
                continue
            stream = InStream(self.path)
            # 回调对象在 Open 期间必须保持存活（7z.dll 会回调它）
            open_cb = OpenCallback()
            try:
                hr = vcall(arc.value, 3, OPEN)(arc, c_void_p(stream.ptr), None,
                                               c_void_p(open_cb.ptr))
                if hr == S_OK:
                    self.arc, self.stream = arc.value, stream
                    return
                last = SevenZipError("Open 失败 (0x%08X)" % (hr & 0xFFFFFFFF))
            except Exception as e:
                last = e
            release(arc.value)
            stream.close()
        raise last or SevenZipError("不支持的压缩包格式：%s" % self.path)

    def prop(self, index, prop_id, read):
        pv = PropVariant()
        try:
            vcall(self.arc, 6, GET_PROPERTY)(c_void_p(self.arc), index, prop_id, byref(pv))
            return read(pv)
        finally:
            propvariant_clear(byref(pv))

    def items(self):
        """[(相对路径, 是否目录)]，顺序与包内一致。"""
        n = c_uint(0)
        check(vcall(self.arc, 5, GET_NUM_ITEMS)(c_void_p(self.arc), byref(n)),
              "GetNumberOfItems")
        out = []
        for i in range(n.value):
            key = norm_key(self.prop(i, KPID_PATH, prop_str))
            if key:
                out.append((key, self.prop(i, KPID_IS_DIR, prop_bool)))
        return out

    def extract(self, target):
        """整包解压到 target，返回 (写入文件数, 失败数)。"""
        os.makedirs(target, exist_ok=True)
        cb = ExtractCallback(self.items(), target)
        try:
            # numItems = ALL_ITEMS 表示"全部文件"，省掉构造索引数组
            hr = vcall(self.arc, 7, EXTRACT)(c_void_p(self.arc), None, ALL_ITEMS, 0,
                                             c_void_p(cb.ptr))
        finally:
            cb.close()
        check(hr, "Extract")
        return cb.written, cb.errors

    def close(self):
        if self.arc:
            try:
                vcall(self.arc, 4, CLOSE)(c_void_p(self.arc))
            except Exception:
                pass
            release(self.arc)
            self.arc = None
        if self.stream:
            self.stream.close()
            self.stream = None


# ============================ 对外接口 ============================


def list_names(archive):
    """列出包内文件相对路径（'/' 分隔，不含目录项）。"""
    arc = ArchiveReader(archive)
    try:
        return [name for name, is_dir in arc.items() if not is_dir]
    finally:
        arc.close()


def extract_all(archive, target_dir):
    """整包解压到 target_dir，返回写入的文件数。"""
    arc = ArchiveReader(archive)
    try:
        written, errors = arc.extract(target_dir)
    finally:
        arc.close()
    if written == 0 and errors:
        raise SevenZipError("压缩包内没有任何文件解压成功")
    return written
