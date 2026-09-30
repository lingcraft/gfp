#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功夫派.exe (Godot 4.6.1) PCK 解密抽取器 + GDRE 反编译（三阶段一体）
阶段一 抽取: 用 KEY(AES-256-CFB128) 解出 PCK 全部文件 -> OUT(临时提取目录)
  进度：GDRE 同款状态栏（status_bar，\r 原地刷新），形如 `提取资源 [==========>     ] 42%`
阶段二 反编译: 调用 GDRE 对 OUT 做资源转换 / .gdc 反编译 -> RECOVERED(最终目录)
  进度：**管道捕获 GDRE 自己的进度条**（实测它走管道就有输出）⇒ 解析出真实百分比后用
    status_bar 重绘 ⇒ 真百分比 + 我们自己的样式（带 '>'）+ 干净（**只显示进度条**，
    它的其它输出一律不显示；只统计 ERROR 条数，收尾提示一句）
    ★ 2026-09-30 更正：此前"GDRE 只在真控制台才输出、非 TTY 一个字节都不写"是**错的** ——
      那只对**文件重定向**（`> out.txt`）成立；**管道能拿到全部输出**（实测 150s 捕获 50205
      行，其中 16729 行带百分比：`Extracting files... [====  ] 95%`）。
    （曾试过 `--conpty` 伪控制台捕获：实测伪控制台下 Godot 一个字节都不吐，该路与 pywinpty 依赖已删除）
阶段三 清理: 反编译成功后直接删除整个 OUT 临时目录（整体 rmtree，比逐文件删快得多）
  (GDRE 2.7 无法直接解 exe 内加密 PCK——AES 模式不匹配；故必须加载已解密目录，且目录模式
   下 res://** 通配符不生效，所以 --recover 不带 key / 不带过滤，全量恢复)

用法:
    python extract.py                 # 抽取 + 反编译 + 删除临时提取目录
                                      # ★ 若 GFP_raw 已存在且非空 ⇒ 自动跳过抽取，直接反编译（测试用）
    python extract.py 5000            # 只抽前 5000 个文件做测试，仍会反编译+清理
    python extract.py --skip-decompile # 仅抽取，不跑 GDRE（也不删 OUT）
    python extract.py -s              # 同上
    python extract.py --keep-raw      # 反编译后保留 OUT 临时目录（不删除）
    python extract.py -k              # 同上
"""
import sys, struct, os, re, queue, hashlib, zlib, subprocess, shutil, threading, time, unicodedata
from Crypto.Cipher import AES

KEY = bytes.fromhex("D9073F3209116603A0024DEA3FC369B6EDFBAC458C262E7B43A94A7EA36F7759")
GDRE = r"D:\Personal Files\Reverse\Godot\gdre_tools.exe"
EXE = r"D:\Software\功夫派\YierPai.pck"
OUT = r"D:\Downloads\temp\GDRE\GFP_raw"
RECOVERED = r"D:\Downloads\temp\GDRE\GFP"

# ===================== 进度条（复刻 GDRE 的控制台状态栏） =====================
# 出处：gdsdecomp `utility/gdre_logger.cpp::GDRELogger::print_status_bar`（master 分支）：
#   constexpr size_t width = 30;
#   progress_width = MIN(width, width * progress);  前 progress_width 格填 '='，其余空格
#   不确定态（indeterminate）：前 progress_width-1 格是空格，只有游标那一格是 '='
#   stdout_print("\r%-80s", "label [bar] NN%")  ⇒ \r 回行首 + 左对齐补到 80 列 = 原地覆盖
#   ⚠ **GDRE 原版没有 '>'**（读源码确认，别再来回找）—— 这里按用户要求加：在已填充的 '='
#     右侧补一个 '>' 当"进度头"（`[=====>     ]`），更符合常见进度条观感。
# ★ 行尾**不补到 80 列**（用户 2026-09-30："光标那里太长了，只显示到 45% 后面"）：只在
#   本行比上一行**短**时补空格擦残影，然后立刻用 `\b` 退回来 ⇒ **光标永远停在 `%` 后面**
#   （残影只在"标签/位数变化"那一瞬间出现，靠这串空格擦掉）。
# 清行常量 GDRE 是 "\r \r"（只盖 1 格，收尾会留残影）⇒ 这里盖满 80 格，收尾一次擦干净。
BAR_WIDTH = 30
STATUS_BAR_CLEAR = "\r" + " " * 80 + "\r"
_bar_last_width = 0          # 上一次状态栏的**屏幕宽度**（中文算 2 列），用于擦短了之后的残影


def _disp_width(text):
    """字符串在终端占几列（中文/全角 2 列，其余 1 列）。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def status_bar(label, progress=None, indeterminate=-1.0):
    """画一行 GDRE 同款进度条并原地刷新（不换行）。

    progress      —— 0.0~1.0，确定态（如抽取百分比），末尾显示 ` NN%`
    indeterminate —— 0.0~1.0，不确定态（只有游标格是 '='，GDRE 每 100ms 推进 1 格）
    与 GDRE 原版的差异（三处有意为之）：
      · 已填充段**右侧补一个 '>'** 当进度头（`[=====>     ]`）—— GDRE 原版只有 '='、没有 '>'
      · **行尾不补到 80 列**（GDRE 用 `"\r%-80s"` 补满）—— 光标只停在 `%` 后面，不拖长尾
      · 进度未知（不确定态）时省略末尾百分比 —— GDRE 恒拼 `%d%%`，那是它内部步数，我们拿不到
    """
    cells = [" "] * BAR_WIDTH
    p = indeterminate if indeterminate != -1 else (progress or 0.0)
    filled = min(BAR_WIDTH, int(BAR_WIDTH * p))
    for i in range(filled):
        cells[i] = " " if (indeterminate != -1 and i != filled - 1) else "="
    if filled < BAR_WIDTH:            # '=' 右侧补 '>' 当进度头（GDRE 原版没有，按用户要求加）
        cells[filled] = ">"
    bar = "".join(cells)
    tail = f" {int(progress * 100)}%" if progress is not None else ""
    global _bar_last_width
    text = f"{label} [{bar}]{tail}"
    width = _disp_width(text)
    pad = max(0, _bar_last_width - width)     # ★ 只在本行变短时补空格，擦掉上一行的尾巴
    _bar_last_width = width + pad
    # 补完空格再用 \b 退回 ⇒ 屏幕上的残影照样被擦掉，但**光标始终停在 `%` 后面**（用户要求）
    sys.stdout.write("\r" + text + " " * pad + "\b" * pad)
    sys.stdout.flush()


def status_bar_clear():
    """清掉状态栏那一行（否则随后打印的普通行会和进度条叠在一起）。"""
    global _bar_last_width
    _bar_last_width = 0
    sys.stdout.write(STATUS_BAR_CLEAR)
    sys.stdout.flush()

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

# ===================== 第二阶段进度：管道读 GDRE 自己的进度条（2026-09-30 实测方案） =====================
# ★ 更正此前结论：GDRE 的输出**走管道就能拿到**。实测（150s 真 recovery，`Popen(stdout=PIPE)`）
#   捕获 50205 行，其中 **16729 行带百分比**：`Loading import files... [   ] 0%` …
#   `Extracting files... [============================  ] 95%`。
#   当初测到"0 字节"用的是**文件重定向**（`> out.txt`）—— 文件 ≠ 管道，两者行为不同，别再被它误导。
#   ⇒ 于是不再轮询日志：直接 PIPE 边读边解析它自己的百分比，用我们的 status_bar 重绘
#     ⇒ 真实百分比 + 我们的样式（带 '>'）+ 干净：**只显示进度条这一行**，GDRE 的其它输出
#       （banner / Opening directory / Loaded N imported files / Extracted N files / ERROR 刷屏…）
#       一律**不显示**，只统计 ERROR 条数在收尾提示（用户 2026-09-30 明确要求"多余的信息不要显示"）。
GDRE_BAR_RE = re.compile(r"\[([=> ]*)]\s*(\d{1,3})%")
GDRE_LABEL_OK = re.compile(r"^[A-Za-z][A-Za-z0-9 ._\-]{0,28}$")
GDRE_PHASE_CN = {
    "Loading import files": "加载文件",
    "Extracting files": "提取资源",
    "Exporting resources": "导出资源",
}


def _gdre_label(raw, current):
    """进度条左侧的阶段名（如 `Extracting files...`）尽量译成中文；不像名字就沿用上一个。"""
    name = raw.strip().rstrip(".").strip()
    if not GDRE_LABEL_OK.match(name):
        return current
    return GDRE_PHASE_CN.get(name, name)


def tail_file(path, count=8):
    """取文件最后 count 行（兜底诊断用；读不到就返回空表）。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return [ln.rstrip("\r\n") for ln in f.readlines()[-count:]]
    except OSError:
        return []


def run_gdre_with_progress(cmd, log_path, started):
    """跑 GDRE，把它的进度实时重绘成我们的状态栏；返回退出码（启动失败返回 None）。

    读法：子进程 stdout 交给后台线程灌进队列，主线程每 1s 取一次 —— 取不到就按"心跳"重画
    一次（状态栏里有已用秒数，长阶段不会看起来卡死）。
    只显示进度条那一行；GDRE 的其它输出（banner / 日志 / ERROR 刷屏）**一律不显示**，
    只在收尾报一句 ERROR 条数。没解析到进度条时（异常情况）取日志尾部作诊断。
    """
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace")
    except OSError as e:
        print(f"[-] 启动 GDRE 失败：{e}")
        return None
    box = queue.Queue()

    def pump():
        try:
            for raw in proc.stdout:       # text 模式 + universal newlines ⇒ 每个 \r 也算一行
                box.put(raw)
        except Exception:                 # noqa: BLE001 —— 读管道出错不该影响主流程收尾
            pass
        finally:
            box.put(None)                 # 哨兵：stdout 关闭 ⇒ 主线程收尾

    threading.Thread(target=pump, daemon=True).start()

    label, pct = "准备中", None       # pct 未定 ⇒ 不确定态占位条（GDRE 要先花 ~40s 加载导入文件索引，
    last_key, last_beat = None, 0.0   #    这期间它自己还没输出任何百分比）；拿到第一条真进度条后 label 会被换成它自己的阶段名
    err_seen, errs = set(), 0
    while True:
        try:
            line = box.get(timeout=1.0)
        except queue.Empty:
            line = ""                     # 心跳：没新行也重画，秒数继续走
        if line is None:
            break
        text = line.strip()
        if text:
            last = None
            for m in GDRE_BAR_RE.finditer(line):
                last = m                   # 一行里可能有多次刷新，取最后一个
            if last is not None:
                label = _gdre_label(line[:last.start()], label)
                v = int(last.group(2))
                if v <= 100:
                    pct = v
            elif "ERROR" in text:
                # 非进度条行一律不显示（用户要求"多余的信息不要显示"）：只统计不同的 ERROR 条数
                if text not in err_seen:
                    err_seen.add(text)
                    errs += 1
        now = time.time()
        key = (label, pct)
        if key != last_key or now - last_beat >= 2.0:
            last_key, last_beat = key, now
            elapsed = int(now - started)
            if pct is None:               # 还没见到进度条 ⇒ 不确定态（游标滑动）
                status_bar(f"{label} {elapsed}s", None, (elapsed * 10 % BAR_WIDTH) / BAR_WIDTH)
            else:
                status_bar(f"{label} {elapsed}s", pct / 100.0)
    code = proc.wait()
    status_bar_clear()                    # 收尾：先擦掉状态栏行，再打普通行
    if errs:
        print(f"[i] GDRE 报告 {errs} 条 ERROR（完整内容见 {log_path}）", flush=True)
    if pct is None:
        print("[i] 本次没解析到 GDRE 的进度条，日志尾部：", flush=True)
        for ln in tail_file(log_path, 8):
            print(f"    {ln}", flush=True)
    return code


def run_gdre_recover():
    """第二阶段：调用 GDRE 对已解密的 OUT 目录做资源转换 + .gdc 反编译。

    关键：GDRE 2.7 解 exe 内加密 PCK 必失败（AES 模式错），必须加载已解密目录；
    且目录模式下 res://** 通配符不生效，故不带 key / 不带 include 过滤，全量恢复。
    进度：**管道捕获** GDRE 自己的输出、解析出真实百分比，再用我们的 status_bar 重绘
    （run_gdre_with_progress）。
    返回 True 表示反编译成功（退出码 0）。
    """
    if not os.path.isfile(GDRE):
        print(f"[-] 找不到 GDRE 工具：{GDRE}，跳过反编译。")
        return False
    if not os.path.isdir(OUT):
        print(f"[-] 提取目录不存在：{OUT}，跳过反编译。")
        return False
    os.makedirs(RECOVERED, exist_ok=True)
    log_path = os.path.join(RECOVERED, "gdre_export.log")
    try:
        os.remove(log_path)          # 清掉上一轮的日志，避免进度串台
    except OSError:
        pass
    print("=" * 60, flush=True)
    print(f"[*] 第二阶段：GDRE 反编译 {OUT} -> {RECOVERED}", flush=True)
    cmd = [GDRE, "--headless", f"--recover={OUT}", f"--output={RECOVERED}"]
    started = time.time()
    # 唯一路径（2026-09-30 实测）：GDRE 的输出**走管道就有** ⇒ PIPE 捕获 + 解析它自己的百分比
    # ⇒ 用我们的 status_bar 重绘。不再区分 TTY、不再轮询 gdre_export.log、不再需要伪控制台。
    code = run_gdre_with_progress(cmd, log_path, started)
    if code is None:
        return False
    if code != 0:
        print(f"[-] GDRE 反编译失败，退出码 {code}（详见 {RECOVERED}\\gdre_export.log）")
        return False
    print(f"[🎉] GDRE 反编译完成（用时 {time.time() - started:.0f}s；脚本 .gdc->.gd、"
          f"资源 .res/.scn->.tres/.tscn、贴图 .ctex->.png）。", flush=True)
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


def extract_all(limit=0):
    """第一阶段：把 EXE(pck) 里的全部文件解出到 OUT，返回 (抽取条数, 失败条数)。

    ⚠ 耗时 ~160s ⇒ 测试第二阶段时可用"复用已有 OUT"跳过它（见 main 的 reuse 逻辑）。
    """
    with open(EXE, "rb") as f:
        pck = find_pck_start(f)
        if pck is None:
            print("找不到 GDPC")
            return 0, 1
        # 头: file_base @24 (8B), dir_offset @32 (8B)
        f.seek(pck + 24)
        file_base, dir_off = struct.unpack("<2Q", f.read(16))
        dir_abs = pck + dir_off
        # 目录: [file_count 4][FAE 块]
        f.seek(dir_abs)
        fc = struct.unpack("<I", f.read(4))[0]
        dent = read_fae(f, dir_abs + 4)
        if dent is None:
            print("目录 FAE 读取失败")
            return 0, 1
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
        total = len(entries)
        print("解析条目数", total, flush=True)
        os.makedirs(OUT, exist_ok=True)
        n = 0
        bad = 0
        last_pct = -1
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
            pct = n * 100 // total
            if pct != last_pct:          # 与 GDRE 一致：百分比整数每变 1，就刷新一次状态栏
                last_pct = pct
                status_bar("提取资源", n / total)
        status_bar_clear()
        print(f"完成 提取 {n} / {total}（bad={bad}）-> {OUT}", flush=True)
    return n, bad


def main(limit=0, skip_decompile=False, keep_raw=False):
    # ⚠ 真控制台（cmd/PowerShell，或 IDE 勾了「在输出控制台中模拟终端」）常是 **GBK 代码页**：
    #    直接 print emoji（🎉/🧹）会抛 UnicodeEncodeError 把整个脚本打断 ⇒ 把编码错误降级成 '?'
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    # ★ 测试便捷：OUT(GFP_raw) 已存在且非空 ⇒ 跳过第一阶段（抽包 ~160s）直接进第二阶段；
    #   该模式也不删 OUT，方便连着反复测第二阶段（要强制重新抽包就删掉该目录再跑）。
    reuse = False
    try:
        with os.scandir(OUT) as it:
            reuse = next(it, None) is not None
    except OSError:
        reuse = False
    if reuse:
        print(f"[i] 检测到已有提取目录 {OUT} ⇒ 跳过第一阶段，直接进入第二阶段", flush=True)
        print("[i] 复用模式不会删除该目录（想强制重新抽包就删掉它再跑）", flush=True)
        n, bad = 1, 0
    else:
        n, bad = extract_all(limit)
    if not skip_decompile:
        if bad == 0 and n > 0:
            if run_gdre_recover():
                if reuse:
                    print(f"[i] 复用模式：保留提取目录 {OUT}", flush=True)
                elif not keep_raw:
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
