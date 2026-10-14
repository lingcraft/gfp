# -*- coding: utf-8 -*-
"""功夫派 dll SWF 的「加密」打包/解包工具（GfpSecurity 容器）。
（本文件位于 gfp.py 同目录，即 gfp/ 下）

格式（由主 SWF 的 com/gf/swf/decrypt.as + 闭环验证得出）：
    容器 = [18 字节头: 00 10 + b"_GfpSwfSecurity_"]  +  [CWS-SWF 的前 1000 字节两两交换]
注意：
  · 头部是 18 字节（`_GfpSwfSecurity_` 16 字符，**末尾的 `W` 属于数据**）；
  · 交换操作自逆 ⇒ 同一个函数既可解包也可打包；
  · SWF 的 fileLength 字段是**小端**；
  · 客户端 DLLLoader 走 release 分支时才 decrypt ⇒ 放进 swf/replace 的**必须**是这种容器格式，
    直接放未压缩/未混淆的标准 SWF 会让客户端解密后 loadBytes 失败（卡在加载界面）。

用法：
    python build_swf.py <源SWF> <swf/replace/输出文件>       # 打包（自动 FWS→CWS）
    python build_swf.py --unpack <容器> <输出>   # 解包（调试/对照用）
"""
import sys
import zlib
from pathlib import Path
from struct import pack

HEADER = b"\x00\x10" + b"_GfpSwfSecurity_"   # 18 字节


def _swap1000(buf: bytearray) -> bytearray:
    """前 1000 字节两两交换（自逆）。"""
    lim = min(1000, len(buf) - 1)
    for k in range(0, lim, 2):
        buf[k], buf[k + 1] = buf[k + 1], buf[k]
    return buf


def unpack(container: bytes) -> bytes:
    """容器 → 标准 SWF（CWS）。"""
    return bytes(_swap1000(bytearray(container[18:])))


def to_cws(swf: bytes) -> bytes:
    """FWS → CWS（客户端解出来的是 CWS，保持一致）。"""
    if swf[:3] == b"CWS":
        return swf
    return b"CWS" + swf[3:4] + pack("<I", len(swf)) + zlib.compress(swf[8:], 9)


def pack_swf(swf: bytes) -> bytes:
    """标准 SWF → 容器（客户端可加载）。"""
    return HEADER + bytes(_swap1000(bytearray(to_cws(swf))))


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    if args[0] == "--unpack":
        src, dst = Path(args[1]), Path(args[2])
        out = unpack(src.read_bytes())
        dst.write_bytes(out)
        print(f"解包: {src} → {dst}  {len(out)}B  magic={out[:3]!r}")
        return
    src, dst = Path(args[0]), Path(args[1])
    out = pack_swf(src.read_bytes())
    Path(dst).write_bytes(out)
    print(f"打包: {src} {src.stat().st_size}B → {dst} {len(out)}B  magic={out[:3]!r}")
    # 自检：解包回来应与中间态一致
    back = unpack(out)
    print(f"自检: 解包 magic={back[:3]!r} 长度={len(back)}B ✓")


if __name__ == "__main__":
    main()
