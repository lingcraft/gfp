#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功夫派.exe (Godot 4.6.1) PCK 解密抽取器 + GDRE 反编译（三阶段一体）
阶段一 抽取: 用 KEY(AES-256-CFB128) 解出 PCK 全部文件 -> OUT(临时提取目录)
阶段二 反编译: 调用 GDRE 对 OUT 做资源转换 / .gdc 反编译 -> RECOVERED(最终目录)
阶段三 清理: 反编译成功后直接删除整个 OUT 临时目录（整体 rmtree，比逐文件删快得多）
  (GDRE 2.7 无法直接解 exe 内加密 PCK——AES 模式不匹配；故必须加载已解密目录，且目录模式
   下 res://** 通配符不生效，所以 --recover 不带 key / 不带过滤，全量恢复)

用法:
    python extract.py                 # 抽取 + 反编译 + 删除临时提取目录
    python extract.py 5000            # 只抽前 5000 个文件做测试，仍会反编译+清理
    python extract.py --skip-decompile # 仅抽取，不跑 GDRE（也不删 OUT）
    python extract.py -s              # 同上
    python extract.py --keep-raw      # 反编译后保留 OUT 临时目录（不删除）
    python extract.py -k              # 同上
"""
import sys, struct, os, hashlib, zlib, subprocess, shutil
from Crypto.Cipher import AES

KEY = bytes.fromhex("D9073F3209116603A0024DEA3FC369B6EDFBAC458C262E7B43A94A7EA36F7759")
GDRE = r"D:\Personal Files\ISA\Godot提取\gdre_tools.exe"
EXE = r"D:\Personal Files\Desktop\怀旧服.exe"
OUT = r"D:\Downloads\temp\GDRE\GFP_raw"
RECOVERED = r"D:\Downloads\temp\GDRE\GFP"

def find_pck_start(f):
    # 扫描文件找 "GDPC", version==3 的候选 (嵌入 PCK 通常在 PE 之后, 取最后一个)
    idxs = []
    CH = 64 * 1024 * 1024
    base = 0
    while True:
        chunk = f.read(CH)
        if not chunk:
            break
        s = 0
        while True:
            i = chunk.find(b"GDPC", s)
            if i < 0:
                break
            idxs.append(base + i)
            s = i + 1
        base += len(chunk)
    for i in reversed(idxs):
        try:
            f.seek(i + 4)
            ver = struct.unpack("<I", f.read(4))[0]
            if ver == 3:
                return i
        except Exception:
            pass
    return idxs[-1] if idxs else None

def read_fae(f, abs_off):
    """读取 FileAccessEncrypted 块: [md5 16][len 8][iv 16][ct len], 返回 (data, blklen, md5, iv)"""
    f.seek(abs_off)
    hdr = f.read(40)
    if len(hdr) < 40:
        return None
    md5 = hdr[0:16]
    blklen = struct.unpack("<Q", hdr[16:24])[0]
    iv = hdr[24:40]
    pad = (16 - (blklen % 16)) % 16
    f.seek(abs_off + 40)
    ct = f.read(blklen + pad)
    if len(ct) < blklen:
        return None
    pt = AES.new(KEY, AES.MODE_CFB, iv, segment_size=128).decrypt(ct)[:blklen]
    return (pt, blklen, md5, iv)

def maybe_decompress(data):
    # Godot 压缩资源: "RSCC" + [4字节?] + 压缩数据
    if data[:4] == b"RSCC":
        for start in (4, 8):
            for wbits in (15, -15, 47):
                try:
                    return zlib.decompress(data[start:], wbits)
                except Exception:
                    pass
    return None

def run_gdre_recover():
    """第二阶段：调用 GDRE 对已解密的 OUT 目录做资源转换 + .gdc 反编译。

    关键：GDRE 2.7 解 exe 内加密 PCK 必失败（AES 模式错），必须加载已解密目录；
    且目录模式下 res://** 通配符不生效，故不带 key / 不带 include 过滤，全量恢复。
    返回 True 表示反编译成功（退出码 0）。
    """
    if not os.path.isfile(GDRE):
        print(f"[-] 找不到 GDRE 工具：{GDRE}，跳过反编译。")
        return False
    if not os.path.isdir(OUT):
        print(f"[-] 提取目录不存在：{OUT}，跳过反编译。")
        return False
    os.makedirs(RECOVERED, exist_ok=True)
    print("=" * 60)
    print(f"[*] 第二阶段：GDRE 反编译 {OUT} -> {RECOVERED}")
    cmd = [GDRE, "--headless", f"--recover={OUT}", f"--output={RECOVERED}"]
    try:
        # 实时转发 GDRE 输出（含进度条）到控制台
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"[-] GDRE 反编译失败，退出码 {e.returncode}（详见 {RECOVERED}\\gdre_export.log）")
        return False
    print("[🎉] GDRE 反编译完成（脚本 .gdc->.gd、资源 .res/.scn->.tres/.tscn、贴图 .ctex->.png）。")
    return True


def cleanup_temp_out():
    """第三阶段：反编译成功后直接删除整个 OUT 临时提取目录（整体 rmtree，速度快）。"""
    if not os.path.isdir(OUT):
        return
    try:
        shutil.rmtree(OUT)
        print(f"[🧹] 已删除临时提取目录 {OUT}")
    except OSError as e:
        print(f"[-] 删除临时提取目录失败：{e}")


def main(limit=0, skip_decompile=False, keep_raw=False):
    with open(EXE, "rb") as f:
        pck = find_pck_start(f)
        if pck is None:
            print("找不到 GDPC"); return
        print("pck_start", hex(pck))
        # 头: file_base @24 (8B), dir_offset @32 (8B)
        f.seek(pck + 24)
        file_base, dir_off = struct.unpack("<2Q", f.read(16))
        print("file_base", hex(file_base), "dir_offset", hex(dir_off))
        dir_abs = pck + dir_off
        # 目录: [file_count 4][FAE 块]
        f.seek(dir_abs)
        fc = struct.unpack("<I", f.read(4))[0]
        print("file_count", fc)
        dent = read_fae(f, dir_abs + 4)
        if dent is None:
            print("目录 FAE 读取失败"); return
        entries_pt, _, dmd5, _ = dent
        # 解析目录条目
        entries = []
        off = 0
        for _ in range(fc):
            if off + 4 > len(entries_pt):
                break
            sl = struct.unpack("<I", entries_pt[off:off+4])[0]; off += 4
            if off + sl > len(entries_pt):
                break
            raw = entries_pt[off:off+sl].rstrip(b"\x00"); off += sl
            path = raw.decode("utf-8", "replace")
            o = struct.unpack("<Q", entries_pt[off:off+8])[0]; off += 8
            sz = struct.unpack("<Q", entries_pt[off:off+8])[0]; off += 8
            emd5 = entries_pt[off:off+16].hex(); off += 16
            fl = struct.unpack("<I", entries_pt[off:off+4])[0]; off += 4
            entries.append((path, o, sz, emd5, fl))
        print("解析条目数", len(entries))
        os.makedirs(OUT, exist_ok=True)
        n = 0
        bad = 0
        for (path, o, sz, emd5, fl) in entries:
            if limit and n >= limit:
                break
            abs_off = pck + file_base + o
            r = read_fae(f, abs_off)
            if r is None:
                bad += 1
                if bad < 20:
                    print("FAIL read", path, hex(abs_off))
                n += 1
                continue
            data_dec, blklen, bmd5, biv = r
            out = maybe_decompress(data_dec)
            if out is not None:
                payload = out
            else:
                payload = data_dec
            # 校验 md5 (目录里记录的是文件 md5)
            if hashlib.md5(payload).hexdigest() != emd5:
                bad += 1
                if bad < 20:
                    print("FAIL md5", path, hashlib.md5(payload).hexdigest(), "exp", emd5)
            # 写文件: 用 size 截断 (无压缩时 size==blklen)
            if sz <= len(payload):
                payload = payload[:sz]
            rel = path
            if rel.startswith("res://"):
                rel = rel[6:]
            dst = os.path.join(OUT, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as fo:
                fo.write(payload)
            n += 1
            if n % 5000 == 0:
                print("进度", n, "/", len(entries), "bad", bad)
        print("完成 提取", n, "bad", bad, "->", OUT)
    if not skip_decompile:
        if bad == 0 and n > 0:
            if run_gdre_recover() and not keep_raw:
                cleanup_temp_out()
        else:
            print("[-] 提取存在失败项（bad=%d），已跳过 GDRE 反编译。" % bad)

if __name__ == "__main__":
    args = sys.argv[1:]
    skip = "--skip-decompile" in args or "-s" in args
    keep_raw = "--keep-raw" in args or "-k" in args
    limit = 0
    for a in args:
        if a in ("--skip-decompile", "-s", "--keep-raw", "-k"):
            continue
        if a.lstrip("-").isdigit():
            limit = int(a.lstrip("-"))
    main(limit, skip, keep_raw)
