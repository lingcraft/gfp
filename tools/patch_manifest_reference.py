# -*- coding: utf-8 -*-
"""往二进制 AndroidManifest.xml (AXML) 添加 uses-permission 节点。
用法: python patch_manifest.py <in_manifest> <out_manifest> <permission_string>
"""
import struct
import sys

def main():
    in_path, out_path, perm = sys.argv[1], sys.argv[2], sys.argv[3]
    data = bytearray(open(in_path, 'rb').read())

    xml_type, hdr_size, xml_size = struct.unpack_from('<HHI', data, 0)
    assert xml_type == 0x0003, f'not AXML: {xml_type:#x}'

    # ---------- string pool ----------
    sp = hdr_size
    sp_type, sp_hdr, sp_size, cnt, style_cnt, flags, strings_start, styles_start = \
        struct.unpack_from('<HHIIIIII', data, sp)
    assert sp_type == 0x0001, f'expect string pool, got {sp_type:#x}'
    assert style_cnt == 0
    is_utf8 = bool(flags & (1 << 8))
    base = sp + strings_start
    offsets = list(struct.unpack_from(f'<{cnt}I', data, sp + sp_hdr))

    def read_str(off):
        p = base + off
        if is_utf8:
            l = data[p]; p += 1
            if l & 0x80:
                l = ((l & 0x7F) << 8) | data[p]; p += 1
            # utf8 pool: 第二个长度(字节数)也可能变长
            bl = data[p]; p += 1
            if bl & 0x80:
                bl = ((bl & 0x7F) << 8) | data[p]; p += 1
            return bytes(data[p:p + bl])
        else:
            l = struct.unpack_from('<H', data, p)[0]; p += 2
            if l & 0x8000:
                l = ((l & 0x7FFF) << 16) | struct.unpack_from('<H', data, p)[0]; p += 2
            return bytes(data[p:p + l * 2]).decode('utf-16-le')

    strs = [read_str(o) for o in offsets]
    print(f'字符串池: {cnt} 条, utf8={is_utf8}')

    def find(s):
        for i, x in enumerate(strs):
            if x == s:
                return i
        return -1

    idx_uses_perm = find('uses-permission')
    idx_android_ns = find('http://schemas.android.com/apk/res/android')
    idx_name = find('name')
    idx_perm = find(perm)
    assert idx_uses_perm >= 0 and idx_android_ns >= 0 and idx_name >= 0, \
        f'前提字符串缺失: uses-permission={idx_uses_perm} ns={idx_android_ns} name={idx_name}'

    new_added = False
    if idx_perm < 0:
        new_added = True
        # 追加字符串
        sb = perm.encode('utf-8')
        if is_utf8:
            def enc_len(n):
                if n < 0x80:
                    return bytes([n])
                return bytes([0x80 | (n >> 8), n & 0xFF])
            enc = enc_len(len(perm)) + enc_len(len(sb)) + sb + b'\x00'
        else:
            enc = struct.pack('<H', len(perm)) + perm.encode('utf-16-le') + b'\x00\x00'
        # 新字符串数据相对 strings_start 的偏移 = 旧数据区长度
        old_data_len = None
        if styles_start:
            old_data_len = styles_start - strings_start
        else:
            old_data_len = sp_size - strings_start
        # 去掉 padding 尾部的不确定性：用最后一个字符串的实际结束位置
        last_end = 0
        for o in offsets:
            p = base + o
            if is_utf8:
                l = data[p]; pl = 1
                if l & 0x80: l = ((l & 0x7F) << 8) | data[p+1]; pl = 2
                bl = data[p+pl]; pl += 1
                if bl & 0x80: pl += 1
                last_end = max(last_end, o + pl + bl + 1)
            else:
                l = struct.unpack_from('<H', data, p)[0]; pl = 2
                if l & 0x8000: l = ((l & 0x7FFF) << 16) | struct.unpack_from('<H', data, p+2)[0]; pl = 4
                last_end = max(last_end, o + pl + l * 2 + 2)
        new_off = last_end
        # 对齐后的新数据区
        def pad4(n):
            return (n + 3) & ~3
        new_data = bytes(data[base:base + last_end]) + enc
        padded = pad4(len(new_data))
        new_data += b'\x00' * (padded - len(new_data))

        new_cnt = cnt + 1
        new_strings_start = pad4(sp_hdr + 4 * new_cnt)
        # 重建 chunk
        new_sp_size = new_strings_start + len(new_data)
        chunk = struct.pack('<HHIIIIII', sp_type, sp_hdr, new_sp_size,
                            new_cnt, style_cnt, flags, new_strings_start, styles_start)
        chunk += struct.pack(f'<{new_cnt}I', *(offsets + [new_off]))
        chunk += new_data
        # 替换旧 chunk
        data[sp:sp + sp_size] = chunk
        # 后续所有位置偏移
        delta = new_sp_size - sp_size
        sp_size = new_sp_size
        idx_perm = new_cnt - 1
        print(f'追加权限字符串 idx={idx_perm}, pool 增量 {delta:+d}')
    else:
        delta = 0
        print(f'权限字符串已存在 idx={idx_perm}')

    # ---------- resource map ----------
    pos = sp + sp_size
    if struct.unpack_from('<H', data, pos)[0] == 0x0180:
        rm_type, rm_hdr, rm_size = struct.unpack_from('<HHI', data, pos)
        map_cnt = (rm_size - rm_hdr) // 4
        # 该 Manifest 的 map 条目数本就与字符串数不一致（非标准打包产物），
        # 且 Android 运行时按索引宽容处理（新节点属性值为 STRING 类型，不查 map），
        # 因此保持 map 原样不动，仅跳过。
        print(f'resource map: {map_cnt} 条目（保持原样）')
        pos = pos + rm_size
    else:
        pos = sp + sp_size

    # ---------- 定位最后一个 uses-permission END_ELEMENT ----------
    uses_perm_idx = find('uses-permission')
    insert_at = None
    scan = pos
    while scan < len(data):
        t, hs, sz = struct.unpack_from('<HHI', data, scan)
        if t == 0x0103:
            ns, nm = struct.unpack_from('<iI', data, scan + hs)
            if nm == uses_perm_idx:
                insert_at = scan + sz
        scan += sz

    assert insert_at is not None, '未找到 uses-permission 节点'
    print(f'插入点: {insert_at} (原文件尾 {len(data)})')

    def start_elem(name_idx, attrs):
        n = len(attrs)
        size = 0x10 + 0x14 + 0x14 * n
        b = struct.pack('<HHI', 0x0102, 0x10, size)
        b += struct.pack('<iI', 0, 0xFFFFFFFF)
        b += struct.pack('<iIHHHHHH', -1, name_idx, 0x14, 0x14, n, 0, 0, 0)
        for (ns, nm, raw, val) in attrs:
            b += struct.pack('<iiIHBBI', ns, nm, raw, 8, 0, 0x03, val)
        return b

    def end_elem(name_idx):
        b = struct.pack('<HHI', 0x0103, 0x10, 0x18)
        b += struct.pack('<iI', 0, 0xFFFFFFFF)
        b += struct.pack('<ii', -1, name_idx)
        return b

    nodes = (start_elem(uses_perm_idx, [(idx_android_ns, idx_name, idx_perm, idx_perm)])
             + end_elem(uses_perm_idx))
    data[insert_at:insert_at] = nodes

    # ---------- 更新文件头 size ----------
    total = len(data)
    struct.pack_into('<I', data, 4, total)
    open(out_path, 'wb').write(data)
    print(f'完成: {out_path}, 大小 {total} (原 {xml_size})')

if __name__ == '__main__':
    main()
