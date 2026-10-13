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
from pathlib import Path
from socket import fromfd, AF_INET, SOCK_STREAM
from struct import pack, unpack_from
from threading import Lock
from re import sub, search
from dict import analyse
from cffi import FFI

BASE_DIR = Path(__file__).resolve().parent
SEND_DELAY = 9   # 发送间隔
LOG_FILE = BASE_DIR / "gfp.log"
FLASH_CLSID = "{d27cdb6e-ae6d-11cf-96b8-444553540000}"
DEFAULT_URL = "http://gf.61.com/Client.swf?t="

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
hook = ffi.dlopen(str(BASE_DIR / "hook.dll"))
# 不使用 hook.LoadFlash()（那是给摩尔工具自带 Flash.ocx 用的方案）。
# DllMain 已自动挂好 send/recv 钩子，Flash 直接用系统已注册的控件。

# ---------------------------------------------------------------- 抓包核心
stream_bufs = {}   # (direction, sock) -> bytearray 重组缓冲
peer_cache = {}    # sock -> "ip:port"
buf_lock = Lock()
log_lock = Lock()
log_fh = None      # 持久日志句柄：每包开关文件太慢，会拖住游戏线程
pending = []       # 待上列表的包 (direction, sock, peer, cmd, packet)——游戏线程只入队，UI 定时批量上屏
pending_lock = Lock()

# ---------------------------------------------------------------- 封包加解密
# Packet 类直接拷贝自 test.py（算法已对照官方 com.fcc.MEncrypt/MDecrypt + 实机抓包逐字节验证）
secret_key = b"taomee_konfu_rock77#!%&~\x00"
key_len = len(secret_key)
user_id = 0
serial_num = 1
growth_num = 0
game_socket_num = 0   # 游戏服通信号（出现 cmd>=1001 的连接），默认发送目标 / 指定通信号自动填充

# 各连接的 serial/growth 链状态（从观察到的发送包同步——序列号流程参考 mole.py：
# 每个需要加密的发送包都由 Packet.encrypt() 自动续算链式 serial 并递增 growth）
serial_chains = {}   # sock -> {"serial": int, "growth": int}
manual_sent = {}     # sock -> True：该连接手发过包，之后客户端所有包都要重算 serial/growth（mole 同款）


class Packet:
    def __init__(self, packet=None, cmd_id=None, body=None):
        self.length = self.cmd_id = self.user_id = self.result = self.growth_num = 0
        self.body = bytearray()
        if packet is not None:
            packet = self.to_bytearray(packet)
            if len(packet) >= 18:
                self.length, self.cmd_id, self.user_id, self.result, self.growth_num = unpack_from("!IHIII", packet)
                self.body = packet[18:]
        elif cmd_id is not None:
            self.cmd_id = cmd_id
            self.body = self.to_bytearray(body)

    def data(self):
        head = pack("!IHIII", self.length, self.cmd_id, self.user_id, self.result, self.growth_num)
        return head + self.body

    @staticmethod
    def to_bytearray(data: str | bytearray | bytes | None):
        if data is None:
            return bytearray()
        if isinstance(data, str):
            def to_field(match):
                value = match.group(1)
                if value == "":
                    return value
                base = 16 if value.startswith("0") or search(r"[a-fA-F]", value) else 10
                return f"{int(value, base):08X}"

            data = sub(r"{([^}:]*)(?::[^}]*)?}", to_field, data.split("：", 1)[-1])
            return bytearray.fromhex(data)
        return bytearray(data)

    def get_serial_num(self):
        global growth_num, serial_num
        self.length, self.user_id, self.growth_num = len(self.body) + 19, user_id, growth_num
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


def packet_to_plain(direction: str, packet: bytes) -> bytes:
    """线上包 → 明文形态（18B 包头 + 明文包体）。
    登录服命令（cmd<1001）本身不加密；1001 发送方向免加密；其余游戏服包解密。"""
    if len(packet) < 18:
        return packet
    cmd = (packet[4] << 8) | packet[5]
    if cmd < 1001 or (direction == "send" and cmd == 1001):
        return packet
    if len(packet) <= 18:
        return packet
    try:
        p = Packet(packet)
        p.decrypt()
        return packet[:18] + bytes(p.body)
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


def emit_packet(direction, sock, peer, packet):
    """一个完整包：日志记原始密文（持久句柄），原始包入队等 UI 批量上屏。
    同时同步该连接的 serial/growth 链状态（mole 同款流程：链随每个发送包推进）。

    注意：本函数跑在游戏线程的 send/recv 钩子回调里，必须保持轻量——
    之前直接在这里同步刷新界面列表，点背包时的数据风暴会把 Flash 消息泵
    卡住、心跳发不出去，直接断线。解密和上列表全部挪到 UI 线程定时批量做。"""
    global user_id, game_socket_num
    try:
        cmd = unpack_from("!H", packet, 4)[0] if len(packet) >= 6 else 0
    except Exception:
        cmd = 0
    if len(packet) >= 18:
        if direction == "send":
            serial_chains[sock] = {
                "serial": unpack_from("!I", packet, 10)[0],
                "growth": unpack_from("!I", packet, 14)[0],
            }
            if cmd == 1001:
                game_socket_num = sock
                user_id = unpack_from("!I", packet, 6)[0]
    # prefix = "[==>]" if direction == "send" else "[<==]"
    # with log_lock:
    #     try:
    #         if log_fh is not None:
    #             log_fh.write(prefix + packet.hex().upper() + "\n")
    #             log_fh.flush()
    #     except Exception:
    #         pass
    with pending_lock:
        pending.append((direction, sock, peer, cmd, packet))


def rewrite_outgoing(sock, data):
    """手发过包之后，客户端自身的 serial/growth 计数就和服务器期望的链脱节了：
    服务器以收到的最后一个包续链，客户端不知道手发包的存在，再按自己计数发就会被踢。
    参考 mole：此后该连接上客户端发的每个包都 解密 → 按当前链重算 serial/growth → 再加密发出，
    服务器看到的序列永远连续。未手发过包的连接原样放行，不碰客户端流量。"""
    if not manual_sent.get(sock) or len(data) < 18 or data[0] or data[1]:
        return data
    global serial_num, growth_num, user_id
    try:
        cmd = unpack_from("!H", data, 4)[0]
        ch = serial_chains.get(sock)
        if ch is None:
            return data   # 没有链基准，重算只会出错，原样放行
        p = Packet(data)
        if cmd < 1001:  # 登录服：明文包，serial 简单自增、growth 恒 0
            serial = ch["serial"] + 1
            serial_chains[sock] = {"serial": serial, "growth": 0}
            return pack("!IHIII", p.length, cmd, p.user_id, serial, 0) + data[18:]
        # 游戏服：解密 → 按链重算 serial/growth → 再加密（1001 与空包体免加密）
        serial_num = ch["serial"]
        growth_num = ch["growth"] + 1
        if p.user_id:
            user_id = p.user_id
        else:
            p.user_id = user_id
        encrypted = bool(p.body) and cmd != 1001
        if encrypted:
            p.decrypt()
        p.get_serial_num()      # 基于明文包体链式重算 serial，growth 递增
        if encrypted:
            p.encrypt(is_get_serial_num=False)   # serial 已重算，只加密
        else:
            p.length = len(p.body) + 18
        serial_chains[sock] = {"serial": p.result, "growth": p.growth_num}
        return p.data()
    except Exception:
        return data


def feed(direction, sock, data):
    """按 4 字节长度字段重组流，切出完整游戏包后下发。"""
    peer = get_peer(sock)
    with buf_lock:
        buf = stream_bufs.setdefault((direction, sock), bytearray())
        buf.extend(data)
        while len(buf) >= 4:
            if buf[0] or buf[1]:
                # 非游戏包（如 HTTP 噪音）：跳到下一个 00 00
                idx = buf.find(b"\x00\x00")
                if idx == -1:
                    buf.clear()
                    break
                del buf[:idx]
                continue
            plen = int.from_bytes(buf[:4], "big")
            if not 18 <= plen <= 65535:
                del buf[:2]
                continue
            if len(buf) < plen:
                break
            packet = bytes(buf[:plen])
            del buf[:plen]
            emit_packet(direction, sock, peer, packet)
        if len(buf) > (1 << 20):  # 防护：长期拼不成完整包则丢弃
            buf.clear()


@ffi.callback("int(ULONG64, PCHAR, INT)")
def on_send(sock, buf, length):
    try:
        data = bytes(ffi.buffer(buf, length))
        data = rewrite_outgoing(int(sock), data)   # 手发过包后重算客户端后续包的 serial/growth
        feed("send", int(sock), data)
        return hook.Send(sock, ffi.new("char[]", data), len(data))
    except Exception:
        return hook.Send(sock, buf, length)  # 兜底原样放行


@ffi.callback("void(ULONG64, PCHAR, INT)")
def on_recv(sock, buf, length):
    try:
        data = bytes(ffi.buffer(buf, length))
        feed("recv", int(sock), data)
    except Exception:
        pass


# ---------------------------------------------------------------- UI
from PySide6.QtCore import Qt, QTimer, QEvent
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QPlainTextEdit, QPushButton, QLineEdit,
    QCheckBox, QHeaderView, QAbstractItemView, QGroupBox, QMessageBox,
)
from PySide6.QtAxContainer import QAxWidget


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("功夫派")
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, False)  # 禁用最大化按钮
        self.resize(1800, 708)  # 宽度固定 1800；高度先给估计值，布局完成后按内容贴紧
        self.scale_start = 0.0

        # 菜单栏：刷新游戏（mole 同款，直接挂 menuBar，紧凑单行）
        self.menuBar().addAction("刷新游戏", self.load_movie)

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
        if not self.ax.setControl(FLASH_CLSID):
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

        # 封包批量上屏：游戏线程的钩子回调只入队；UI 每 50ms 最多取 200 条，
        # 保证消息泵不被卡住（卡泵 → Flash 心跳发不出 → 游戏断线）
        self.drain_timer = QTimer(self)
        self.drain_timer.timeout.connect(self.drain_pending)
        self.drain_timer.start(50)

        # 匀速发送：按 SEND_LIMIT 折算间隔逐包发出，PreciseTimer 保证节奏均匀
        self.send_queue = deque()   # 待发队列（明文 hex）
        self.loop_mode = False
        self._recv_before_loop = True
        self.send_pace_timer = QTimer(self)
        self.send_pace_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.send_pace_timer.setInterval(SEND_DELAY)
        self.send_pace_timer.timeout.connect(self.paced_send_one)

        # 加载后短暂应用缩放模式（拉伸到控件大小）
        self.scale_timer = QTimer(self)
        self.scale_timer.timeout.connect(self.apply_scale)

        # 首次加载
        QTimer.singleShot(0, self.load_movie)

    def closeEvent(self, event):
        # 关闭窗口后删除 hook.log，收尾持久日志句柄
        try:
            (BASE_DIR / "hook.log").unlink(missing_ok=True)
        except Exception:
            pass
        global log_fh
        # with log_lock:
        #     try:
        #         if log_fh is not None:
        #             log_fh.flush()
        #             log_fh.close()
        #     except Exception:
        #         pass
        #     log_fh = None
        super().closeEvent(event)

    def load_movie(self):
        # 刷新游戏（也用于首次加载）：带时间戳重新加载舞台，避免缓存
        self.ax.dynamicCall("LoadMovie(long,string)", 0, DEFAULT_URL + str(int(time.time())))
        self.scale_start = time.monotonic()
        self.scale_timer.start(100)

    def apply_scale(self):
        try:
            self.ax.dynamicCall("SetScaleMode(int)", 2)
        except Exception:
            pass
        if time.monotonic() - self.scale_start > 1.5:
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
        if state > 0 and len(self.sock_edit.text()) == 0 and game_socket_num != 0:
            self.sock_edit.setText(str(game_socket_num))

    def drain_pending(self):
        """把游戏线程入队的包批量上屏：解密也在 UI 线程做，单次最多 200 条。"""
        with pending_lock:
            batch = pending[:200]
            del pending[:200]
        if not batch:
            return
        send_on = self.cb_send.isChecked()
        recv_on = self.cb_recv.isChecked()
        t = self.table
        t.blockSignals(True)
        shown = False
        try:
            for direction, sock, peer, cmd, packet in batch:
                if direction == "send" and not send_on:
                    continue
                if direction == "recv" and not recv_on:
                    continue
                disp = packet_to_plain(direction, packet).hex().upper()
                self.add_data("S ==>" if direction == "send" else "R <==", sock, peer, cmd, disp)
                shown = True
        finally:
            if shown and self.packet_index >= 10:
                t.scrollToBottom()
            t.blockSignals(False)

    def add_data(self, data_type: str, socket_num: int, peer: str, cmd_id: int, data: str):
        # 单行插入（drain_pending 已统一 blockSignals / 滚动）
        if self.packet_index >= 10000:  # 已有数据10000条，清空
            self.clear_table()
            self.table.blockSignals(True)  # clear_table 会解除阻断，批量插入期间保持阻断
        if self.packet_index >= self.table.rowCount():
            self.table.setRowCount(self.packet_index + 1)
        self.table.setItem(self.packet_index, 0, QTableWidgetItem(data_type))
        self.table.setItem(self.packet_index, 1, QTableWidgetItem(str(socket_num)))
        self.table.setItem(self.packet_index, 2, QTableWidgetItem(str(cmd_id)))
        self.table.setItem(self.packet_index, 3, QTableWidgetItem(analyse(cmd_id)))
        self.table.setItem(self.packet_index, 4, QTableWidgetItem(data))
        if peer:
            ip, _, port = peer.partition(":")
            tip = f"IP: {ip} Port: {port}"
        else:
            tip = "IP: 0 Port: 0"
        self.table.item(self.packet_index, 0).setToolTip(tip)
        self.table.item(self.packet_index, 1).setToolTip(str(socket_num))
        self.table.item(self.packet_index, 2).setToolTip(str(cmd_id))
        self.table.item(self.packet_index, 3).setToolTip(analyse(cmd_id))
        self.table.item(self.packet_index, 4).setToolTip(data)
        self.packet_index += 1  # 下一条要插入数据的索引

    def build_outgoing(self, sock, plain):
        """明文形态 → 线上包：serial/growth 按链式流程自动续算（参考 mole.py），再加密。
        登录服命令（cmd<1001）：serial 简单自增（新连接首包 1）、growth 恒 0、明文发送。
        1001 发送方向：免加密（serial 照链推进）。
        其余游戏服命令：从该连接观察到的链状态续算链式 serial，growth 递增，并加密。"""
        global serial_num, growth_num, user_id
        p = Packet(plain)
        ch = serial_chains.get(sock)
        if p.cmd_id < 1001:
            # 登录服：serial 简单自增（新连接首包 1），growth 恒 0，明文发送
            serial = (ch["serial"] + 1) if ch else (p.result or 1)
            p.result, p.growth_num = serial, 0
            serial_chains[sock] = {"serial": p.result, "growth": p.growth_num}
            return p.data()
        if ch:
            serial_num = ch["serial"]          # f(prev_serial) 由 get_serial_num 计算
            growth_num = ch["growth"] + 1      # 下一包 growth = 上一个 + 1
        if p.user_id:
            user_id = p.user_id
        else:
            p.user_id = user_id
        if p.cmd_id == 1001:
            p.get_serial_num()        # 1001 发送免加密；serial 照链推进
            p.length = len(p.body) + 18
        if p.body:
            p.encrypt()               # 自动链式 serial + 加密（mole 同款流程）
        else:
            p.get_serial_num()        # 空包体：只算 serial，不加密（实机 len=18）
            p.length = len(p.body) + 18
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
            hx = sub(r"[^0-9a-fA-F]", "", line)
            if hx and len(hx) % 2 == 0:
                self.send_queue.append(hx)

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
            if game_socket_num == 0:
                return   # 队列保留，等后续拍（循环模式下捕获到连接后自动继续）
            sock = game_socket_num
        hx = self.send_queue.popleft()
        plain = bytes.fromhex(hx)                    # 输入是明文形态
        wire = self.build_outgoing(sock, plain)      # serial/growth 链式续算 + 自动加密
        buf = ffi.new("char[]", wire)
        if hook.Send(sock, buf, len(wire)) > 0:
            manual_sent[sock] = True   # 手发过包：此后该连接客户端的包都要重算 serial/growth
            emit_packet("send", sock, get_peer(sock), wire)


def main():
    global log_fh
    try:
        from ctypes import windll, c_void_p
        windll.user32.SetProcessDpiAwarenessContext(c_void_p(-4))
    except Exception:
        pass
    hook.SetSendCallBack(on_send)
    hook.SetRecvCallBack(on_recv)
    hook.LoadFlash()
    # with log_lock:
    #     try:
    #         # 打开窗口前清空 gfp.log（写模式打开即清空），写会话头并持有句柄——
    #         # 游戏线程每包只 write+flush，不再反复开关文件
    #         log_fh = open(LOG_FILE, "w", encoding="utf-8")
    #         log_fh.write(f"==== 会话开始 {datetime.now():%Y-%m-%d %H:%M:%S} ====\n")
    #         log_fh.flush()
    #     except Exception:
    #         log_fh = None
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # 界面样式与 mole 一致
    win = MainWindow()
    win.show()
    # 隐藏式启动（run.vbs 的 Run(...,0) / SW_HIDE）会让首个窗口继承隐藏状态——在这里强制显示
    try:
        win.showNormal()
        win.raise_()
        win.activateWindow()
        from ctypes import windll as _w
        hwnd = int(win.winId())
        _w.user32.ShowWindow(hwnd, 5)          # SW_SHOW
        _w.user32.SetForegroundWindow(hwnd)
    except Exception:
        pass
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
