# -*- coding: utf-8 -*-
"""功夫派抓包工具（最简版）

左侧：内嵌系统 Flash，游戏区域（手动登录）
右侧：封包列表 / 发送封包

抓包：hook.dll 挂钩本进程 ws2_32 的 send/recv（加载即生效），
      Flash 与服务器的通信全部经过这里。
日志：每包一行写入同目录 gfp.log（原始密文，便于复盘）：
      [==>]发送包HEX   [<==]接收包HEX
界面：右侧列表显示解密后的明文包；发送区输入明文，点发送自动加密后发出。
序列：手发过包后，该连接上客户端后续包会在 send 钩子里 解密 → 按当前链
      重算 serial/growth → 再加密发出（mole 同款），服务器看到的序列号保持连续。
"""
import sys
import time
from collections import deque
from enum import StrEnum
from loguru import logger
from pathlib import Path
from socket import fromfd, AF_INET, SOCK_STREAM
from struct import pack, unpack_from
from threading import Lock
from re import sub, search
from dict import analyse
from os import environ

from bridge import start_bridge, injector_url, replace_dir, replace_resources
from ctypes import windll, c_void_p
from cffi import FFI
from _cffi_backend import buffer

base_dir = Path(__file__).resolve().parent
hook_log = base_dir / "hook.log"
gfp_log = base_dir / "gfp.log"
send_delay = 10      # 发送间隔

# ---------------------------------------------------------------- hook
ffi = FFI()
ffi.cdef("""
typedef int (*SendCallBack)(ULONG64, PCHAR, INT);
typedef void (*RecvCallBack)(ULONG64, PCHAR, INT);
void SetSendCallBack(SendCallBack);
void SetRecvCallBack(RecvCallBack);
int WINAPI Send(ULONG64, PCHAR, INT);
void LoadFlash();
""")

# ---------------------------------------------------------------- 抓包核心
stream_bufs = {}  # (Show, sock) -> bytearray 重组缓冲
peer_cache = {}  # sock -> "ip:port"
ignored_socks = set()  # 非游戏连接（HTTP/SWF 资源流）：整条忽略，不解析/不解密/不上屏
buf_lock = Lock()
is_log = True  # 是否把封包写入 gfp.log（每包一行；mole 同款 loguru 方案）
is_show_send = True  # 上屏开关（勾选框变化时更新；钩子线程读，避免跨线程访问 Qt 控件）
is_show_recv = True


class Show(StrEnum):
    """封包方向标识（mole 同款）：贯穿整条抓包流水线 ——
    流重组缓冲的 key、上屏「类型」列、日志前缀，全部用它，代码里不再出现 "send"/"recv" 字符串。"""
    SEND = "S ==>"
    RECV = "R <=="


# ---------------------------------------------------------------- 封包加解密
# Packet 类直接拷贝自 test.py（算法已对照官方 com.fcc.MEncrypt/MDecrypt + 实机抓包逐字节验证）
secret_key = b"taomee_konfu_rock77#!%&~\x00"
key_len, head_len, serial_num, growth_num = len(secret_key), 18, 1, 0
user_id = 0
login_socket_num = 0  # 游戏服通信号（出现 cmd>=1001 的连接），默认发送目标 / 指定通信号自动填充

# 各连接的 serial/growth 链状态（从观察到的发送包同步——序列号流程参考 mole.py：
# 每个需要加密的发送包都由 Packet.encrypt() 自动续算链式 serial 并递增 growth）
send_lock = Lock()  # 手动/自动注入发送互斥（hook.Send + 链重算必须原子）
is_window_init = False  # 主窗口是否已就绪（mole 同款；__main__ 里建完窗口置 True，钩子线程用前先判断）
manual_sent = {}  # sock -> True：手动发过包后，客户端后续包需要按全局链重算 serial/growth
serial_chains = {}  # sock -> {"serial": int, "growth": int}：各连接最近一次发送包的链状态
STAGE_ENTRY = 2406  # CommandID.STAGE_ENTRY：进入关卡
not_deduct_stage = True  # 「关卡不扣次数」（默认开启）：进入关卡包 stageID 首字节 00→01


class Packet:
    def __init__(self, packet=None, cmd_id=None, body=None):
        self.length = self.cmd_id = self.user_id = self.result = self.growth_num = 0
        self.body = bytearray()
        if packet is not None:
            packet = self.to_bytearray(packet)
            if len(packet) >= head_len:
                self.length, self.cmd_id, self.user_id, self.result, self.growth_num = unpack_from("!IHIII", packet)
                self.body = packet[head_len:]
        elif cmd_id is not None:
            self.cmd_id = cmd_id
            self.body = self.to_bytearray(body)

    def data(self):
        head = pack("!IHIII", self.length, self.cmd_id, self.user_id, self.result, self.growth_num)
        return head + self.body

    @staticmethod
    def to_bytearray(data: str | bytearray | bytes | buffer | None):
        if data is None:
            return bytearray()
        if isinstance(data, str):
            # 支持带标注的输入，如：“学习技能：0000000000000004670000000000000000
            # {00009A96:拉姆ID}{00000003:技能类别}{3:技能等级}”
            # 大括号里的值：0 开头 → 16 进制、按写的位数原样使用（仅补齐偶数位）——
            # {01}=1字节、{001}=2字节、{00009A96}=4字节；
            # 非 0 开头：含 [a-fA-F] 按 16 进制、纯数字按 10 进制，统一转 4 字节（8 位、前补 0）。
            def to_field(match):
                value = match.group(1)
                if value == "":
                    return value
                if value.startswith("0"):
                    return "0" + value if len(value) % 2 else value
                base = 16 if search(r"[a-fA-F]", value) else 10
                return f"{int(value, base):08X}"

            data = sub(r"{([^}:]*)(?::[^}]*)?}", to_field, data.split("：", 1)[-1])
            return bytearray.fromhex(data)
        return bytearray(data)

    def get_serial_num(self):
        global growth_num, serial_num
        self.length, self.user_id, self.growth_num = len(self.body) + head_len + 1, user_id, growth_num
        growth_num = (growth_num + 1) & 0xFFFFFFFF
        if self.cmd_id == 999:
            serial_num = 0
        else:
            crc = 0
            for byte in self.body:
                crc ^= byte
            # 计算发送包序列号
            serial_num = (serial_num - serial_num // 7 + 151 + (self.length - 1) % 13 + self.cmd_id % 23 + crc) & 0xFFFFFFFF
        self.result = serial_num

    def encrypt(self, is_get_serial_num: bool = True):
        if is_get_serial_num:
            self.get_serial_num()
        res = bytearray(len(self.body) + 1)
        key_index = 0
        for index in range(len(self.body)):
            res[index] = self.body[index] ^ secret_key[key_index % key_len]
            key_index += 1
            if key_index > key_len:
                key_index = 0
        for index in range(len(res) - 1, 0, -1):
            res[index] |= res[index - 1] >> 3
            res[index - 1] = (res[index - 1] << 5) % 256
        res[0] |= 3
        self.body = res
        return self

    def decrypt(self):
        if len(self.body) == 0:
            return self
        res = bytearray(len(self.body) - 1)
        key_index = 0
        for index in range(len(res)):
            res[index] = (self.body[index] >> 5) | (self.body[index + 1] << 3) % 256
            res[index] ^= secret_key[key_index % key_len]
            key_index += 1
            if key_index > key_len:
                key_index = 0
        self.body = res
        return self


def packet_to_plain(show: Show, packet: bytes) -> bytes:
    """线上包 → 明文形态（18B 包头 + 明文包体）。
    登录服命令（cmd<1001）本身不加密；1001 发送方向免加密；其余游戏服包解密。"""
    if len(packet) < head_len:
        return packet
    cmd = (packet[4] << 8) | packet[5]
    if cmd < 1001 or (show is Show.SEND and cmd == 1001):
        return packet
    if len(packet) <= head_len:
        return packet
    try:
        p = Packet(packet)
        p.decrypt()
        return packet[:head_len] + bytes(p.body)
    except Exception:
        return packet


def get_peer(sock):
    """查询 socket 远端地址（缓存）。"""
    peer = peer_cache.get(sock)
    if peer:
        return peer
    try:
        with fromfd(sock, AF_INET, SOCK_STREAM) as s:
            ip, port = s.getpeername()
        peer = f"{ip}:{port}"
        peer_cache[sock] = peer
        return peer
    except Exception:
        return ""


def show_data(show: Show, sock: int, peer: str, cmd: int, data: bytes) -> None:
    """投递**已解密的明文包**给界面（mole 同款：窗口未就绪直接跳过；
    同线程直调 add_data，跨线程 emit 信号——queued connection 保序、非阻塞）。"""
    if not is_window_init or cmd == 0:
        return
    hex_data = data.hex().upper()
    if QThread.currentThread() is QApplication.instance().thread():
        window.add_data(show, sock, peer, cmd, hex_data)          # 同线程：直调，省一次信号排队
    else:
        window.show_signal.emit(show, sock, peer, cmd, hex_data)  # 跨线程：queued signal 保序


def emit_packet(show: Show, sock, peer, packet):
    """一个完整包：同步 serial/growth 链状态，并直接 emit 信号上屏。

    ⚠ serial/growth 链是【纯发送方向】（SocketImpl 源码铁证：_result 只在 send()→
    parseResult() 更新，onData 接收解析不碰它；growthNum 只在 send() 末尾 +1）——
    接收包不参与链，严禁用 R 包更新链头。"""
    global user_id, login_socket_num
    try:
        cmd = unpack_from("!H", packet, 4)[0] if len(packet) >= 6 else 0
    except Exception:
        cmd = 0
    if len(packet) >= head_len and show is Show.SEND:
        # 同步该连接最近一次发送包的链状态（手动发包 build_outgoing 的续算基准）
        serial_chains[sock] = {"serial": unpack_from("!I", packet, 10)[0],
                               "growth": unpack_from("!I", packet, 14)[0]}
        if cmd == 1001:
            login_socket_num = sock
            user_id = unpack_from("!I", packet, 6)[0]
    show_on = (show is Show.SEND and is_show_send) or (show is Show.RECV and is_show_recv)
    if is_log or show_on:
        try:
            data = packet_to_plain(show, packet)   # 明文形态：只解密一次，日志与上屏共用
        except Exception as e:
            # 解密失败不能让整条钩子链崩掉（否则钩子 except 会把包【原样】发出 ⇒ 绕过改写/上屏）
            logger.exception(f"[dbg] packet_to_plain 异常 show={show} cmd={cmd} len={len(packet)}: {e}")
            data = packet
        if is_log:
            # 与 mole 同款：loguru 文件 sink（enqueue=True，钩子线程写日志不阻塞 Flash）
            # 格式：[方向][功能解析]明文HEX
            try:
                name = analyse(cmd)
            except Exception as e:
                name = f"analyse异常:{e}"
            logger.info(f"[{show}][{name}]{data.hex().upper()}")
        if show_on:
            show_data(show, sock, peer, cmd, data)


def send(socket_num: int, buf: bytes | buffer, length: int):
    """经 hook.dll 的原始 Send 发出（绕过 ws2_32 钩子，避免再次触发回调；mole 同款）。"""
    return hook.Send(socket_num, ffi.from_buffer(buf), length)


def feed(show: Show, sock, data):
    """按 4 字节长度字段重组流，切出完整游戏包后下发。

    ⚠ 客户端加载 SWF/XML 等资源走的是 HTTP（同样经过 hook）⇒ 首字节不是 00 00。
    这类连接**一旦识别就整条拉黑**：不再扫描/解密/上屏——否则本地注入服务瞬间返回的
    几 MB SWF 会被当作包流反复切分，产生成百上千伪包、把游戏卡死。"""
    if sock in ignored_socks:
        return
    peer = get_peer(sock)
    with buf_lock:
        buf = stream_bufs.setdefault((show, sock), bytearray())
        buf.extend(data)
        if len(buf) < 2:
            return
        if buf[0] or buf[1]:
            # 首 2 字节非 00 00 ⇒ 不是游戏包（HTTP 响应/请求头、TLS、SWF 内容…）⇒ 拉黑该连接
            ignored_socks.add(sock)
            buf.clear()
            return
        while len(buf) >= 4:
            plen = int.from_bytes(buf[:4], "big")
            if not head_len <= plen <= 65535:
                del buf[:2]  # 帧错位容错：滑两字节重新对齐
                continue
            if len(buf) < plen:
                break
            packet = bytes(buf[:plen])
            del buf[:plen]
            emit_packet(show, sock, peer, packet)
        if len(buf) > (1 << 20):  # 防护：长期拼不成完整包则丢弃
            buf.clear()


@ffi.callback("int(ULONG64, PCHAR, INT)")
def process_send_packet(socket_num, buf, length):
    global login_socket_num, user_id, serial_num, growth_num
    raw_buf = ffi.buffer(buf, length)
    try:
        # 游戏包：首 2 字节 00 00 且长度够（>=head_len 含 18B 空体包；HTTP 资源流/TLS 首字节不同 ⇒ 原样放行）
        if raw_buf[:2] == b"\x00\x00" and len(raw_buf) >= head_len:
            packet = Packet(raw_buf)
            sock = int(socket_num)
            if packet.cmd_id == 1001:
                # 登录游戏包（明文）：记录游戏服连接/user_id，全局 serial/growth 链对齐到
                # 客户端算的值（它是游戏服加密链的起点），并清除上一会话残留的手发标记
                # ⇒ 原样放行。⚠ 绝不能走下面的解密/加密，否则服务器收到"加密的 1001"，
                #   会话建立不了（症状：卡在"加载个人信息"）。
                login_socket_num = sock
                user_id = packet.user_id
                serial_num = packet.result
                growth_num = packet.growth_num + 1   # 链头 growth 统一为"下一包基准"
                manual_sent.pop(sock, None)
                feed(Show.SEND, sock, bytes(raw_buf))
                return send(sock, raw_buf, length)
            if sock == login_socket_num:
                packet.decrypt()
                # ---- 「关卡不扣次数」：明文上直接改写 stageID 首字节 ----
                # ⚠ 改写 body ⇒ crc 变 ⇒ serial 必须按【改写后 body】重算
                #   （别人方案实测：2406 serial = f(上一S包serial, crc_new) ⇒ 服务器按收到的
                #     body 校验 serial；保持客户端原值反而差 1 ⇒ close）
                # ⚠ 空体包（18B，如 0964 战斗准备完成）也必须处理：客户端按自己的链算 serial，
                #   2406 改写后客户端链与服务器链脱节 ⇒ 空体若原样放行会把链永久打断；
                #   空体重算 serial 但【不加密】（AS send() 空体不走 encrypt），length 修正回 18
                rewrite = not_deduct_stage and packet.cmd_id == STAGE_ENTRY and bool(packet.body)
                if rewrite:
                    packet.body[0] = 1  # 关卡 ID 首字节 00 → 01 ⇒ 服务器消耗查询 miss ⇒ 不扣活力
                    logger.info("[inject] 关卡不扣次数：进入关卡包 stageID 首字节 → 01（serial 按新 body 重算）")
                with send_lock:
                    if manual_sent.get(sock):
                        # 手动发过包（含 2406 改写）：客户端自己的 serial/growth 已与服务器期望脱节
                        # ⇒ 每个客户端包都按全局纯发送链重算
                        if packet.body:
                            packet.encrypt()
                        else:
                            packet.get_serial_num()           # serial/growth 照链推进
                            packet.length = head_len          # 空体 length 修正回 18（不按密文体 +1）
                    elif rewrite:
                        growth_num = packet.growth_num   # growth 保持客户端本包值（= 链头+1，等价）
                        packet.encrypt()                 # serial = f(链头, crc_new) + 加密
                    elif packet.body:
                        # 正常登录：客户端序列自身连续 ⇒ serial/growth 保持客户端原值，只加密
                        packet.encrypt(is_get_serial_num=False)
                        serial_num = packet.result          # 链头 serial = 本包（手动发包接在这后面）
                        growth_num = packet.growth_num + 1  # 链头 growth = 下一包基准
                    else:
                        # 未手发空体：原样放行（客户端 serial 连续），仅同步链头
                        serial_num = packet.result
                        growth_num = packet.growth_num + 1
                if rewrite:
                    manual_sent[sock] = True   # 改写推进了链 ⇒ 之后的客户端包按全局链重算
                data = packet.data()
            else:
                data = packet.data()   # 登录服（103/105/107，本身明文）：原样
            feed(Show.SEND, sock, data)
            return send(sock, data, len(data))
        else:
            return send(int(socket_num), raw_buf, length)
    except Exception as e:
        # 任何异常都不能吞包（吞包 ⇒ 客户端-服务器失步 ⇒ 掉线）：原样放行兜底（bak.2 同款）
        try:
            logger.exception(f"[dbg] 发送钩子异常 sock={socket_num} len={length}: {e}")
        except Exception:
            pass
        try:
            return send(int(socket_num), raw_buf, length)
        except Exception:
            return 0



@ffi.callback("void(ULONG64, PCHAR, INT)")
def process_recv_packet(sock, buf, length):
    try:
        data = bytes(ffi.buffer(buf, length))
        feed(Show.RECV, int(sock), data)
    except Exception:
        pass


# ---------------------------------------------------------------- UI
from PySide6.QtCore import Qt, QTimer, QEvent, Signal, QThread
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QPlainTextEdit, QPushButton, QLineEdit,
    QCheckBox, QHeaderView, QAbstractItemView, QGroupBox, QMessageBox,
)
from PySide6.QtAxContainer import QAxWidget


caches_dir = Path(environ["localappdata"]) / "Microsoft" / "Windows" / "INetCache" / "IE"


class ClearThread(QThread):
    def run(self):
        # 前缀 = replace_resources 的键（别名源的缓存挂在原请求名下）∪ replace 目录下所有 swf 的文件名（去扩展名，小写比较）
        prefixes = {path.stem.lower() for path in replace_dir.rglob("*.swf")}
        prefixes |= {Path(key).stem.lower() for key in replace_resources}
        prefixes = tuple(prefixes)
        cleared = 0
        if prefixes:
            for cache_file in caches_dir.rglob("*"):
                name = cache_file.name.lower()
                if name.endswith(".swf") and name.startswith(prefixes):
                    try:
                        cache_file.unlink()
                        cleared += 1
                    except OSError:
                        pass
        logger.info(f"[cache] 已清除 swf 缓存文件 {cleared} 个")


class MainWindow(QMainWindow):
    # 钩子线程 → UI 线程的封包投递（mole 同款：Qt queued signal 按 emit 顺序保序，
    # 替代原先「入队 + 50ms 定时批量上屏」，包次序与实时性都由信号队列保证）
    show_signal = Signal(str, int, str, int, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("功夫派")
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, False)  # 禁用最大化按钮
        self.resize(1800, 708)  # 宽度固定 1800；高度先给估计值，布局完成后按内容贴紧
        self.scale_start = 0.0

        # 菜单栏：刷新游戏（mole 同款，直接挂 menuBar，紧凑单行）
        self.menuBar().addAction("刷新游戏", self.refresh)
        self.menuBar().addAction("清除缓存", self.clear_cache)
        # 「关卡不扣次数」：默认开启，点菜单切换（对钩直接画进文字）。
        self.action_not_deduct = self.menuBar().addAction(self.not_deduct_text(not_deduct_stage))
        self.action_not_deduct.triggered.connect(self.toggle_not_deduct)
        self.clear_thread = ClearThread()

        central = QWidget()
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)  # 贴边：游戏区左右不留空白
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)
        outer.addWidget(splitter)

        # ---------------- 左侧：游戏区域 ----------------
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)
        self.ax = QAxWidget()
        if not self.ax.setControl("{d27cdb6e-ae6d-11cf-96b8-444553540000}"):
            QMessageBox.warning(self, "提示", "未能创建 Flash 控件（系统未注册 Flash ActiveX？）")
        self.ax.setFixedSize(1200, 660)  # 游戏区域固定为舞台原生尺寸 1200x660
        lv.addWidget(self.ax, 1, Qt.AlignTop | Qt.AlignHCenter)
        left.setFixedWidth(1200)  # 左栏=游戏区宽度，左右不留空白
        splitter.addWidget(left)

        # ---------------- 右侧（整体包进 GroupBox：单层边框贴满右侧，内容离边框 3px） ----------------
        right = QWidget()
        outer = QVBoxLayout(right)
        outer.setContentsMargins(0, 0, 0, 0)   # group 正好填满右侧，不额外留白
        group = QGroupBox()
        group.setContentsMargins(0, 0, 0, 0)   # 去掉样式自带的内边距（之前那层白）
        # 单线边框贴控件边缘（Fusion 原生是 3px 凹凸浮雕，最外 1px 浅线看起来像多了一层间隔）
        group.setStyleSheet("QGroupBox { border: 0; margin: 0; padding: 0; }")
        rv = QVBoxLayout(group)
        rv.setContentsMargins(10, 10, 10, 10)   # 内容离边框 10px，只露出这一圈边框
        rv.setSpacing(3)
        outer.addWidget(group)
        splitter.addWidget(right)

        # 封包列表
        self.table = QTableWidget()
        self.table.setFont(QFont("Cascadia Code, Microsoft YaHei UI", 9))
        self.table.verticalHeader().setFont(self.table.font())
        self.table.verticalHeader().setDefaultSectionSize(10)  # 行高
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)  # 禁止编辑单元格
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)  # 禁止选多行
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)  # 一次选一行
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)  # 允许手动调整列宽
        self.table.horizontalHeader().setStretchLastSection(True)  # 封包数据列顶到右边缘，不留空竖线
        self.clear_table()
        self.table.setHorizontalHeaderLabels(["类型", "通信号", "命令号", "解析", "封包数据"])
        self.table.currentCellChanged.connect(self.change_row)
        rv.addWidget(self.table)
        # 表格高度 = 表头 + 20 行（+ 横向滚动条若出现），正好显示 20 行；剩余高度全给发送区
        self.fit_table_height()
        self.table.viewport().installEventFilter(self)  # 滚动条出没会改视口尺寸，跟随校准
        QTimer.singleShot(0, self.fit_table_height)

        # 勾选框行（mole ui: 拦截Send 80x20 / 拦截Recv 80x20 / 清空封包 61x26 | 指定通信号： 85x20 + 输入 50x20）
        bar = QHBoxLayout()
        self.cb_send = QCheckBox("拦截 Send")
        self.cb_send.setFixedSize(80, 20)
        self.cb_send.setChecked(True)
        self.cb_recv = QCheckBox("拦截 Recv")
        self.cb_recv.setFixedSize(80, 20)
        self.cb_recv.setChecked(True)
        self.clear_btn = QPushButton("清空封包")
        self.clear_btn.setFixedSize(61, 26)
        self.sock_check = QCheckBox("指定通信号：")
        self.sock_check.setFixedSize(85, 20)
        self.sock_edit = QLineEdit()
        self.sock_edit.setFixedSize(50, 20)
        self.sock_edit.setEnabled(False)   # 勾选"指定通信号"后才可用（mole 同款）
        bar.addWidget(self.cb_send)
        bar.addWidget(self.cb_recv)
        bar.addWidget(self.clear_btn)
        bar.addStretch(1)
        bar.addWidget(self.sock_check)
        bar.addWidget(self.sock_edit)
        rv.addLayout(bar)

        # 发送区（mole ui: 发送框在勾选框行下方；此处拉高占满剩余空间）
        self.send_edit = QPlainTextEdit()
        f = self.send_edit.font()
        f.setPointSize(10)   # 只加大字号，字族保持默认
        self.send_edit.setFont(f)
        rv.addWidget(self.send_edit, 1)
        # 发送/循环发送/清空 按钮：group 的兄弟层浮在发送框右下角（mole 同款），置顶不被滚动条覆盖
        self.group = group
        self.send_btns = QWidget(group)
        sl = QHBoxLayout(self.send_btns)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(2)
        self.send_btn = QPushButton("发送")
        self.send_btn.setFixedSize(50, 25)
        self.send_loop_btn = QPushButton("循环发送")
        self.send_loop_btn.setFixedSize(70, 25)
        self.send_clear_btn = QPushButton("清空")
        self.send_clear_btn.setFixedSize(50, 25)
        sl.addStretch(1)
        sl.addWidget(self.send_btn)
        sl.addWidget(self.send_loop_btn)
        sl.addWidget(self.send_clear_btn)
        self.send_btns.raise_()
        self.send_edit.installEventFilter(self)  # 随发送框尺寸贴右下角（mole: 右/下留 5px）

        splitter.setStretchFactor(0, 0)  # 左栏固定（游戏区宽度），窗口缩放只影响右侧
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([1200, 499])

        # 窗口高度贴合内容（菜单栏 + 游戏区），并上下固定、不可拉伸；宽度可变，多出的空间给右侧
        snug_h = self.menuBar().sizeHint().height() + self.centralWidget().sizeHint().height()
        self.setFixedSize(1800, snug_h)

        # 信号
        self.clear_btn.clicked.connect(self.clear_table)
        self.send_btn.clicked.connect(self.do_send)
        self.send_loop_btn.clicked.connect(self.toggle_send_loop)
        self.send_clear_btn.clicked.connect(self.send_edit.clear)
        self.sock_check.stateChanged.connect(self.change_socket)
        self.cb_send.stateChanged.connect(self.change_show_send)
        self.cb_recv.stateChanged.connect(self.change_show_recv)
        self.show_signal.connect(self.add_data)  # mole 同款：钩子线程 emit → UI 线程 add_data（保序）

        # 匀速发送：按 SEND_LIMIT 折算间隔逐包发出，PreciseTimer 保证节奏均匀
        self.send_queue = deque()   # 待发队列（明文 hex）
        self.loop_mode = False
        self._recv_before_loop = True
        self.send_pace_timer = QTimer(self)
        self.send_pace_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.send_pace_timer.setInterval(send_delay)
        self.send_pace_timer.timeout.connect(self.paced_send_one)

        # 加载后短暂应用缩放模式（拉伸到控件大小）
        self.scale_timer = QTimer(self)
        self.scale_timer.timeout.connect(self.apply_scale)

        # 首次加载
        start_bridge()
        QTimer.singleShot(0, self.refresh)

    def closeEvent(self, event):
        if hook_log.exists():
            hook_log.unlink()
        if gfp_log.exists():
            logger.remove()
            try:
                gfp_log.unlink()
            except:
                pass
        super().closeEvent(event)

    def url(self):
        """LoadMovie 目标（mole 同名方法）：本地注入服务 + 时间戳防旧缓存。"""
        return injector_url(f"/Client.swf?t={int(time.time())}")

    def refresh(self):
        # 刷新游戏（mole 同名方法；也用于首次加载与"清完缓存自动刷新"）：
        # 指向本地注入服务（mole 同款机制）⇒ 命中 swf/replace 的同名文件就地替换，其余透传官服
        self.ax.dynamicCall("LoadMovie(long,string)", 0, self.url())
        self.set_scale_mode()

    def clear_cache(self):
        """清除 Flash 缓存中的「替换 SWF / 别名（replace_resources 键）」缓存副本（后台线程执行，不卡界面）——
        线程未在跑才启动（mole 同款启动方式）；清完不自动刷新（需要时手动点「刷新游戏」）。"""
        if not self.clear_thread.isRunning():
            self.clear_thread.start()

    def toggle_not_deduct(self, *_):
        """菜单点击 ⇔ 「关卡不扣次数」开关（发送方向把进入关卡包 diff 字段 1→4，
        关卡配置表 consume[3]=0 ⇒ 不扣活力；stageID 不动，避免被服务器当不存在关卡踢）。
        ⚠ action 不是 checkable ⇒ triggered 的 checked 参数恒为 False，不能用它，直接取反全局状态。"""
        global not_deduct_stage
        not_deduct_stage = not not_deduct_stage
        self.action_not_deduct.setText(self.not_deduct_text(not_deduct_stage))

    @staticmethod
    def not_deduct_text(checked: bool) -> str:
        return "✔关卡不扣次数" if checked else "关卡不扣次数"

    def set_scale_mode(self):
        """mole 同款：LoadMovie 之后 ~1 秒内反复 `SetScaleMode(2)`，让 Flash 舞台随控件拉伸。
        （mole 用 `RunTimer(apply, Interval.NORMAL, 0)`：delay=0 立即触发一次 + 之后每 25ms 一次，
          我们用 QTimer 等价实现。）"""
        self.scale_start = time.monotonic()
        self.scale_timer.start(25)   # Interval.NORMAL = 25ms
        self.apply_scale()           # delay=0：立即先调一次

    def apply_scale(self):
        self.ax.dynamicCall("SetScaleMode(int)", 2)
        if time.monotonic() - self.scale_start > 1:   # mole: monotonic() - start > 1
            self.scale_timer.stop()

    def eventFilter(self, obj, event):
        # 表格视口尺寸变化（滚动条出没/拖列宽）时重新校准，保证正好显示 20 行
        if obj is self.table.viewport() and event.type() == QEvent.Type.Resize:
            self.fit_table_height()
        # 发送按钮容器贴发送框右下角（mole ui: 右/下留 5px），兄弟层置顶不被滚动条覆盖
        if obj is self.send_edit and event.type() == QEvent.Type.Resize:
            w = self.send_btns.sizeHint().width()
            g = self.send_edit.geometry()
            self.send_btns.setGeometry(g.x() + g.width() - w - 6, g.y() + g.height() - 30, w, 25)
            self.send_btns.raise_()
        return super().eventFilter(obj, event)

    def toggle_send_loop(self):
        if self.loop_mode:   # 停止
            self.loop_mode = False
            self.send_loop_btn.setText("循环发送")
            if self._recv_before_loop:
                self.cb_recv.setChecked(True)
        else:                # 启动：把发送框内容排入匀速队列，循环反复发出
            self._recv_before_loop = self.cb_recv.isChecked()
            if self._recv_before_loop:
                self.cb_recv.setChecked(False)
            self.send_loop_btn.setText("停止")
            self.loop_mode = True
            self.enqueue_lines()
            self.send_pace_timer.start()

    def fit_table_height(self):
        """表格高度 = 边框 + 表头 + 20 行行高 + 横向滚动条（若可见）- 1。
        高度比整 20 行少 1px，内容始终比视口高一点：纵向滚动条从初始就显示（mole 样式）。"""
        row_h = self.table.verticalHeader().sectionSize(0)
        head_h = self.table.horizontalHeader().height()
        if head_h <= 0:  # 未布局时用 sizeHint 估算
            head_h = self.table.horizontalHeader().sizeHint().height()
        sb = self.table.horizontalScrollBar()
        sb_h = sb.height() if sb.isVisible() else 0
        self.table.setFixedHeight(self.table.frameWidth() * 2 + head_h + 20 * row_h + sb_h - 1)

    def clear_table(self):
        self.table.blockSignals(True)
        self.packet_index = 0
        self.table.clearContents()  # 清空内容
        self.table.setRowCount(20)  # 初始行数
        self.table.setColumnCount(5)
        self.table.setColumnWidth(0, 45)
        self.table.setColumnWidth(1, 45)
        self.table.setColumnWidth(2, 45)
        self.table.setColumnWidth(3, 100)
        self.table.setColumnWidth(4, 1)   # 最后一列交给 stretchLastSection 重新顶满（清掉拖宽残留）
        self.table.setCurrentCell(-1, -1)  # 清除选中，避免恢复信号后触发 currentCellChanged
        self.table.scrollToTop()  # 拖动到顶部
        self.table.blockSignals(False)

    def change_row(self, row: int, column: int):
        data = self.table.item(row, column if column < 2 else 4)
        if data is not None:
            self.send_edit.setPlainText(data.toolTip() if column == 0 else data.text())

    def change_socket(self, state: int):
        self.sock_edit.setEnabled(state > 0)
        if state > 0 and len(self.sock_edit.text()) == 0 and login_socket_num != 0:
            self.sock_edit.setText(str(login_socket_num))

    def change_show_send(self, state: int):
        global is_show_send
        is_show_send = bool(state)

    def change_show_recv(self, state: int):
        global is_show_recv
        is_show_recv = bool(state)

    def add_data(self, data_type: str, socket_num: int, peer: str, cmd_id: int, data: str):
        """单条上屏（mole 同款：每条包独立 blockSignals，10 条后每包滚动到底部）。"""
        t = self.table
        t.blockSignals(True)
        try:
            if self.packet_index >= 10000:  # 已有数据10000条，清空
                self.clear_table()
                t.blockSignals(True)  # clear_table 会解除阻断，插入期间保持阻断
            if self.packet_index >= t.rowCount():
                t.setRowCount(self.packet_index + 1)
            t.setItem(self.packet_index, 0, QTableWidgetItem(data_type))
            t.setItem(self.packet_index, 1, QTableWidgetItem(str(socket_num)))
            t.setItem(self.packet_index, 2, QTableWidgetItem(str(cmd_id)))
            t.setItem(self.packet_index, 3, QTableWidgetItem(analyse(cmd_id)))
            t.setItem(self.packet_index, 4, QTableWidgetItem(data))
            if peer:
                ip, _, port = peer.partition(":")
                tip = f"IP: {ip} Port: {port}"
            else:
                tip = "IP: 0 Port: 0"
            t.item(self.packet_index, 0).setToolTip(tip)
            t.item(self.packet_index, 1).setToolTip(str(socket_num))
            t.item(self.packet_index, 2).setToolTip(str(cmd_id))
            t.item(self.packet_index, 3).setToolTip(analyse(cmd_id))
            t.item(self.packet_index, 4).setToolTip(data)
            if self.packet_index >= 10:  # 已有10条数据后拖动到底部
                t.scrollToBottom()
            self.packet_index += 1  # 下一条要插入数据的索引
        finally:
            t.blockSignals(False)

    def build_outgoing(self, sock, plain):
        """明文形态 → 线上包：serial/growth 按链式流程自动续算（参考 mole.py），再加密。
        登录服命令（cmd<1001）：serial 简单自增（新连接首包 1）、growth 恒 0、明文发送。
        1001 发送方向：免加密（serial 照链推进）。
        其余游戏服命令：从该连接观察到的链状态续算链式 serial，growth = 链 + 1
        （占客户端下一坑位，bak.2 实测 61→62 验证通过），并加密。"""
        global serial_num, growth_num, user_id
        p = Packet(plain)
        ch = serial_chains.get(sock)
        # 「关卡不扣次数」：手动发送的进入关卡包同样改写（明文 ⇒ 直接改 stageID 首字节）
        if not_deduct_stage and p.cmd_id == STAGE_ENTRY and p.body:
            p.body[0] = 1
            logger.info("[inject] 关卡不扣次数：手动发送的进入关卡包 stageID 首字节 → 01")
        if p.user_id:
            user_id = p.user_id
        else:
            p.user_id = user_id
        if p.cmd_id < 1001:
            # 登录服：明文包，serial 简单自增（新连接首包 1），growth 恒 0，明文发送
            serial = (ch["serial"] + 1) if ch else (p.result or 1)
            p.result, p.growth_num = serial, 0
            p.length = len(p.body) + head_len
            serial_chains[sock] = {"serial": p.result, "growth": 0}
            return p.data()
        if ch:
            serial_num = ch["serial"]          # f(prev_serial) 由 get_serial_num 计算
            growth_num = ch["growth"] + 1      # 下一包 growth = 上一个 + 1
        if p.cmd_id == 1001:
            # 1001 发送免加密：serial 照链推进，length 不按密文体（+1）扩容 ⇒ 直接返回
            p.get_serial_num()
            p.length = len(p.body) + head_len
            serial_chains[sock] = {"serial": p.result, "growth": p.growth_num}
            return p.data()
        if p.body:
            p.encrypt()               # 自动链式 serial + 加密（2406 手发同样按链重算，
                                      # serial = f(链头, crc_改写后body)，与别人方案同构）
        else:
            p.get_serial_num()        # 空包体：只算 serial，不加密（实机 len=18）
            p.length = len(p.body) + head_len
        # 链状态 = 该连接已发送的最后一包（serial/growth）
        serial_chains[sock] = {"serial": p.result, "growth": p.growth_num}
        return p.data()

    def do_send(self):
        # 发送目标在 paced_send_one 每拍按当前设置解析（默认游戏服通信号 / 勾选"指定通信号"用填写值）
        # 这里只把发送框内容排入匀速队列，由 send_pace_timer 逐包发出
        self.enqueue_lines()
        if not self.send_pace_timer.isActive():
            self.send_pace_timer.start()

    def enqueue_lines(self):
        for line in self.send_edit.toPlainText().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                # Packet.to_bytearray 支持 {值:注释} 模板（冒号后为注释，随大括号一起丢弃），
                # 中文注释里的 hex 字符（如"ID"的 D、"前2个"的 2）不会被误保留
                data = bytes(Packet(line).data())
            except Exception:
                continue   # 解析失败（残缺行）跳过
            if len(data) >= head_len:
                self.send_queue.append(data.hex())

    def paced_send_one(self):
        """匀速发送：每拍发出 1 个包（间隔 = ceil(1000/SEND_LIMIT) ms）。
        队列空了：循环模式自动续内容，手动模式自动停。
        发送目标每拍按当前设置解析，目标无效时本拍跳过、队列保留。"""
        if not self.send_queue:
            if self.loop_mode:
                self.enqueue_lines()
            if not self.send_queue:
                self.send_pace_timer.stop()
                return
        if self.sock_check.isChecked():
            sock_txt = self.sock_edit.text().strip()
            if not sock_txt.isdigit():
                return
            sock = int(sock_txt)
        else:
            if login_socket_num == 0:
                return   # 队列保留，等后续拍（循环模式下捕获到连接后自动继续）
            sock = login_socket_num
        hx = self.send_queue.popleft()
        with send_lock:
            plain = bytes.fromhex(hx)                    # 输入是明文形态
            wire = self.build_outgoing(sock, plain)      # serial/growth 链式续算 + 自动加密
            sent = send(sock, wire, len(wire)) > 0
        if sent:
            manual_sent[sock] = True   # 手发过包：之后客户端的包由发送钩子按全局链重算
            emit_packet(Show.SEND, sock, get_peer(sock), wire)

if __name__ == "__main__":
    windll.user32.SetProcessDpiAwarenessContext(c_void_p(-4))
    if is_log:
        logger.add(gfp_log, format="[{time:YYYY-MM-DD HH:mm:ss}] {message}", encoding="utf-8", enqueue=True)
    hook = ffi.dlopen("hook.dll")
    hook.SetSendCallBack(process_send_packet)
    hook.SetRecvCallBack(process_recv_packet)
    hook.LoadFlash()
    app = QApplication([])
    app.setStyle("Fusion")  # 界面样式与 mole 一致
    window = MainWindow()
    is_window_init = True
    window.show()
    # 隐藏式启动（run.vbs 的 Run(...,0) / SW_HIDE）会让首个窗口继承隐藏状态——在这里强制显示
    try:
        window.showNormal()
        window.raise_()
        window.activateWindow()
        hwnd = int(window.winId())
        windll.user32.ShowWindow(hwnd, 5)  # SW_SHOW
        windll.user32.SetForegroundWindow(hwnd)
    except Exception:
        pass
    app.exec()
