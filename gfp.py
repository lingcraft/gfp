#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gfp.py — 功夫派怀旧服存档图形修改器（PySide6）。

复用 main.py 的 Godot 4 加密容器 / Variant 编解码能力，提供：
  1. 开荒减负：给等级 <=5 的新手角色补齐「鲲鹏之征服者套装」7 件套到库存。
  2. 存档备份 / 恢复：把账号目录压缩为 zip 到 %appdata%\\gfp\\<账号名>\\，可回选恢复。

运行： uv run python gfp.py
"""

import os
import re
import json
import zipfile
import random
import time
import ctypes
from pathlib import Path
from datetime import datetime
from ui_main import Ui_MainWindow
import decrypt  # 复用解密/加密核心（read_encrypted_file / write_encrypted_file / Variant 编解码）
import sevenzip  # 7z.dll 封装：解压 .7z / .rar（RAR4+RAR5），无需 py7zr / rarfile / unrar
import style  # 界面样式集中定义（按钮 QSS + 下拉框的代理样式），色值见 style.py
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QMainWindow, QMessageBox
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtCore import (QAbstractNativeEventFilter, QStandardPaths, Qt, QTimer,
                            QTranslator)
from ctypes.wintypes import HWND, UINT, WPARAM, LPARAM, RECT, BOOL

# ============ 路径与常量 ============
APPDATA = Path(os.environ["appdata"])
DATA_DIR = APPDATA / "Godot" / "app_userdata" / "YierPai"
SAVES_DIR = DATA_DIR / "saves"
BACKUPS_DIR = DATA_DIR / "backups"  # 备份存放根目录
BASE_DIR = Path(__file__).resolve().parent
EQUIP_DIR = BASE_DIR / "装备"  # 装备数据库（4 角色 + 饰品）
GAME_WINDOW_TITLE = "YierPai"    # 怀旧服游戏窗口标题（toast 优先居中到该窗口）
# role_id（中文）-> 装备数据库文件名
ROLE_DB_FILE = {
    "伊尔": "伊尔装备图标数据.json",
    "派派": "派派装备图标数据.json",
    "大竹": "大竹装备图标数据.json",
    "敖天": "敖天装备图标数据.json",
}
user32 = ctypes.windll.user32
WM_HOTKEY = 0x0312
WM_KEYUP = 0x0101


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", HWND), ("message", UINT), ("wParam", WPARAM),
        ("lParam", LPARAM), ("time", ctypes.c_uint),
        ("pt", ctypes.c_long * 2),
    ]


class GlobalHotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, handlers):
        super().__init__()
        self.handlers = handlers  # {hotkey_id: callable}
        self.down = {}  # vk -> 触发时的单调时钟（按住期间去重）
        self.keyup = {}  # vk -> 最近一次 WM_KEYUP 的 MSG.time
        self.last = {}  # vk -> 最近一次真正触发的单调时钟（防抖）

    def nativeEventFilter(self, eventType, message):
        if eventType == "windows_generic_MSG":
            msg = ctypes.cast(int(message), ctypes.POINTER(MSG))
            m = msg.contents.message
            mt = msg.contents.time
            now = time.monotonic()
            if m == WM_HOTKEY:
                # lParam 高字为虚拟键码，低字为修饰键
                vk = (msg.contents.lParam >> 16) & 0xFFFF
                hid = msg.contents.wParam
                fn = self.handlers.get(hid)
                if fn:
                    # 1) 同一物理按键按住期间的自动重复：忽略（>3s 视为卡死兜底）
                    if vk in self.down:
                        if now - self.down[vk] < 3.0:
                            return False, 0
                        self.down.pop(vk, None)
                    # 2) 松开前已生成、却排队到松开后才派发的重复消息：忽略
                    if vk in self.keyup and mt <= self.keyup[vk]:
                        return False, 0
                    # 3) 已有模态弹窗（确认框/错误框）打开：忽略
                    if QApplication.activeModalWidget() is not None:
                        return False, 0
                    # 4) 1.2s 内同热键防抖（挡住键盘抖动/补发）
                    if now - self.last.get(vk, -1e9) < 1.2:
                        return False, 0
                    self.down[vk] = now
                    self.last[vk] = now
                    fn()
                    return True, 0  # 已处理，避免消息被二次派发
            elif m == WM_KEYUP:
                vk = msg.contents.wParam
                self.keyup[vk] = mt
                self.down.pop(vk, None)
        return False, 0


# ============ 工具函数 ============
def version_key(ver):
    """版本号 -> 可排序元组；版本号不是纯数字（如文件名就是一句中文说明）时回退 (0,)。"""
    try:
        return tuple(int(p) for p in ver.lstrip("Vv").split("."))
    except ValueError:
        return (0,)


# 备份文件名：`版本{sep}日期[{sep}时间][{sep}注释]`，sep 可以是下划线或空格（可混用）
# 文件名里可能出现的日期 / 时间写法（按匹配优先级排列）：
#   日期：20260917 / 2026-09-17 / 2026/09/17 / 2026.09.17
#   时间：053853 / 05:38:53 / 0538 / 05:38
DATE_PATTERNS = (
    (re.compile(r"\d{8}"), "%Y%m%d"),
    (re.compile(r"\d{4}-\d{2}-\d{2}"), "%Y-%m-%d"),
    (re.compile(r"\d{4}/\d{2}/\d{2}"), "%Y/%m/%d"),
    (re.compile(r"\d{4}\.\d{2}\.\d{2}"), "%Y.%m.%d"),
)
TIME_PATTERNS = (
    (re.compile(r"\d{2}:\d{2}:\d{2}"), "%H:%M:%S"),
    (re.compile(r"\d{6}"), "%H%M%S"),
    (re.compile(r"\d{2}:\d{2}"), "%H:%M"),
    (re.compile(r"\d{4}"), "%H%M"),
)
HEAD_RE = re.compile(r"^(?P<ver>[^_\s]+)(?P<rest>[_\s].*)?$")


def parse_backup_name(stem):
    """解析备份文件名 `{版本}{sep}{日期}[{sep}{时分}[{sep}{秒}]][{sep}{注释}]`。

    sep 可以是下划线或空格（可混用）；时间之后剩余的文字（如"刷新前"）作为注释，
    下划线统一转空格。匹配不到（或日期非法）则整个文件名都当注释。
    返回 (版本, 时间或 None, 注释, 时间显示格式串)。
    """
    m = HEAD_RE.match(stem)
    ver = m.group("ver") if m else ""
    rest = (m.group("rest") or "").lstrip("_ ") if m else ""

    # 日期：按上面的写法依次尝试（非法日期如 2026-13-32 会 strptime 失败并继续试下一种）
    t = None
    for rx, fmt in DATE_PATTERNS:
        dm = rx.match(rest)
        if not dm:
            continue
        try:
            t = datetime.strptime(dm.group(), fmt)
        except ValueError:
            continue
        rest = rest[dm.end():]
        break
    if t is None:
        # 匹配不到「版本+时间」格式：整个文件名都当作注释，下划线统一转空格
        # （如 "刷新瑶瑶任务前_1_2" -> "刷新瑶瑶任务前 1 2"）
        return "", None, stem.replace("_", " ").strip(), ""

    # 时间：显示精度跟随文件名实际写到的精度（只写到日就不补 00:00:00）
    disp = "%Y-%m-%d"
    rest = rest.lstrip("_ ")
    for rx, fmt in TIME_PATTERNS:
        tm = rx.match(rest)
        if not tm:
            continue
        try:
            tt = datetime.strptime(tm.group(), fmt)
        except ValueError:
            break
        t = t.replace(hour=tt.hour, minute=tt.minute, second=tt.second)
        disp += " %H:%M:%S" if fmt.endswith("S") else " %H:%M"
        rest = rest[tm.end():]
        break
    # 注释里的下划线统一显示为空格
    return ver, t, rest.replace("_", " ").strip(), disp


def shorten_path(p) -> str:
    """把路径开头的 AppData\\Roaming 换成 %appdata%，用于宽度不够时的降级显示。"""
    s = str(p)
    base = str(APPDATA)
    return "%appdata%" + s[len(base):] if s.lower().startswith(base.lower()) else s


def game_window_center(title=None):
    """查找标题包含指定文字的可见窗口，返回其中心坐标 (x, y)；找不到返回 None。

    默认找怀旧服游戏窗口（GAME_WINDOW_TITLE）。最小化或尺寸无效的窗口会跳过。
    """
    keyword = (title or GAME_WINDOW_TITLE).lower()
    matched = []

    @ctypes.WINFUNCTYPE(BOOL, HWND, LPARAM)
    def enum_windows(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if keyword in buf.value.lower():
                    matched.append(hwnd)
        return True

    user32.EnumWindows(enum_windows, 0)
    for hwnd in matched:
        if user32.IsIconic(hwnd):  # 最小化时窗口坐标无意义，跳过
            continue
        rect = RECT()
        if (user32.GetWindowRect(hwnd, ctypes.byref(rect))
                and rect.right > rect.left and rect.bottom > rect.top):
            return (rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2
    return None


def desktop_dir() -> Path:
    """系统桌面路径（优先注册表桌面位置，兜底 ~/Desktop）。"""
    d = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
    return Path(d) if d else Path.home() / "Desktop"


def archive_kind(path):
    """识别 zip / 7z / rar 压缩包类型。不支持的格式抛 ValueError。"""
    ext = path.suffix.lower()
    if ext == ".zip":
        return "zip"
    if ext == ".7z":
        return "7z"
    if ext == ".rar":
        return "rar"
    raise ValueError(f"不支持的压缩包格式：{path.name}（仅支持 .zip / .7z / .rar）")


def archive_files(path, kind):
    """列出压缩包内所有文件的相对路径（统一 '/' 分隔，不含目录项）。

    zip 走 Python 内置 zipfile；7z / rar（RAR4+RAR5）走随包的 7z.dll（sevenzip.py）。
    """
    if kind == "zip":
        with zipfile.ZipFile(path, "r") as z:
            names = [n for n in z.namelist() if not n.endswith("/")]
    else:
        names = sevenzip.list_names(str(path))
    return [
        n for n in (n.replace("\\", "/").lstrip("/") for n in names)
        if n and not n.endswith("/")
    ]


def extract_archive_to(path, kind, target_dir, prefix=""):
    """把压缩包内容解压到 target_dir。

    统一三种格式：先整包解到临时目录，再按 prefix 整理（只取 prefix 目录下的内容并剥离该前缀），
    从而把「.dat 所在目录」的内容直接铺到 saves/<账号名>/ 下。
    zip 走 Python 内置 zipfile；7z / rar 由随包的 7z.dll 解压。
    """
    import shutil
    import tempfile
    target_dir = Path(target_dir)
    # 解压到系统临时目录：with 退出时自动递归删除（抛异常时也会）。
    # ignore_cleanup_errors 防止 rar 内的只读文件让清理失败，被上层误判为"导入失败"。
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp_dir = Path(td)
        if kind == "zip":
            with zipfile.ZipFile(path, "r") as z:
                z.extractall(str(tmp_dir))
        else:
            sevenzip.extract_all(str(path), str(tmp_dir))
        for src in tmp_dir.rglob("*"):
            if not src.is_file():
                continue
            rel = src.relative_to(tmp_dir).as_posix()
            if prefix and not rel.startswith(prefix):
                continue
            dest = target_dir / rel[len(prefix):]
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)


def archive_target(names, arc_stem):
    """由包内文件列表推导账号名与解压前缀。

    .dat 在包内根目录 -> 账号名取压缩包文件名（arc_stem），前缀为空；
    .dat 在子目录   -> 账号名取其父目录名，前缀为该目录（只解压此目录下的内容）。
    包内没有 .dat 时返回 (None, "")。
    """
    dats = [n for n in names if n.lower().endswith(".dat")]
    if not dats:
        return None, ""
    pos = dats[0].rfind("/")
    if pos < 0:
        return arc_stem, ""
    return dats[0][:pos].rsplit("/", 1)[-1], dats[0][: pos + 1]


def gen_uid() -> str:
    """生成形如 '13581436926_2385082135' 的装备 uid。"""
    return f"{random.randint(10 ** 9, 10 ** 10 - 1)}_{random.randint(10 ** 9, 10 ** 10 - 1)}"


def kunpeng_ids(role_id: str):
    """返回指定 role_id 的「鲲鹏之征服者套装」7 件套装备 id 列表（int）。

    套装 = 6 件护甲（名称以 '鲲鹏之征服者' 开头，对应 上衣/头部/手部/腰带/裤子/足部）
         + 1 件武器（名称以 '鲲鹏之' 开头、且描述与护甲一致的基础款，如 '鲲鹏之沐恩之刃'）。
    套装数据.json(id 104) 也确认为 6 件护甲，武器单独占用第 7 个装备槽。
    """
    ARMOR_DESC = "集鲲鹏之力具有强大属性，可直接使用至45级，成为超灵侠士可升至更高级"
    targets = []
    files = []
    if role_id in ROLE_DB_FILE:
        files.append(ROLE_DB_FILE[role_id])
    else:
        files.extend(ROLE_DB_FILE.values())  # 未知角色：在所有库中找
    for fn in files:
        p = EQUIP_DIR / fn
        if not p.exists():
            continue
        try:
            db = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for v in db.values():
            if not isinstance(v, dict):
                continue
            name = str(v.get("名称", ""))
            desc = str(v.get("描述", ""))
            if name.startswith("鲲鹏之征服者"):
                kind = "armor"
            elif name.startswith("鲲鹏之") and desc == ARMOR_DESC:
                kind = "weapon"  # 基础款鲲鹏武器（与护甲同描述）
            else:
                continue
            try:
                targets.append((int(v["id"]), kind))
            except (KeyError, TypeError, ValueError):
                pass
    # 去重保序：先护甲后武器
    seen, out = set(), []
    for i, _ in targets:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def load_payload(profile):
    """解密 save.dat，返回 (payload_dict, version_str)。失败抛异常。"""
    raw = decrypt.read_encrypted_file(profile.save_file, profile.save_key())
    envelope = decrypt.raw_stream_to_envelope(raw)
    payload = decrypt.to_json_safe(envelope.get("payload"))
    sv = (payload.get("save_version") or {}).get("last_client_version", "V0.0.0")
    version = str(sv)  # 保留 "V" 前缀，用于文件名/显示
    return payload, version


def save_payload(profile, payload):
    """把 payload 重新打包加密覆盖回 save.dat。"""
    container = {
        "magic": decrypt.SAVE_CONTAINER_MAGIC,
        "container_version": decrypt.SAVE_CONTAINER_VERSION,
        "payload": payload,
    }
    raw = decrypt.envelope_to_raw_stream(container)
    decrypt.write_encrypted_file(profile.save_file, profile.save_key(), raw)


def owned_kunpeng_ids(payload, idx, kp_ids):
    """统计该角色当前已拥有的鲲鹏套装 id（库存装备 + 身上穿戴 + 账号共仓）。"""
    owned = set()
    ch = (payload.get("characters") or [])[idx] if isinstance(payload.get("characters"), list) else {}
    # 身上穿戴
    eq = ch.get("equipment") or {}
    for v in (eq.values() if isinstance(eq, dict) else []):
        if isinstance(v, dict) and "id" in v:
            owned.add(int(v["id"]))
    # 库存装备
    inv = ch.get("inventory") or {}
    for it in (inv.get("equipment") or []):
        if isinstance(it, dict) and "id" in it:
            owned.add(int(it["id"]))
    # 账号共仓
    store = payload.get("account_storehouse") or {}
    for e in (store.get("entries") or []):
        if isinstance(e, dict):
            if "id" in e:
                owned.add(int(e["id"]))
            for sub in (e.get("equipment") or []):
                if isinstance(sub, dict) and "id" in sub:
                    owned.add(int(sub["id"]))
    return owned


# Toast 提示浮窗配色：换风格只需改这三行（背景是自绘的，见 ToastLabel）
TOAST_BG = QColor(238, 216, 167, 240)  # 琥珀金底
TOAST_BORDER = QColor(150, 110, 40)  # 深棕外框
TOAST_TEXT = "#3B2A12"  # 深棕文字

# 按钮样式（主界面 + 弹窗）都在 ui_main.ui 的 styleSheet 属性里，由转换后的 ui_main.py 应用：
#   centralwidget 的 styleSheet → 主界面按钮（QPushButton 那 5 组规则）
#   MainWindow 的 styleSheet    → 弹窗按钮（QMessageBox QPushButton 那 6 组，带 min-width/padding 保住 80x20）
# 色值取自 WPF 版 wpf/Styles.xaml，渐变 stop 用 WPF 实机截图反解校准过（QSS 渐变含 1px 边框会偏 1 色阶）。

class ToastLabel(QLabel):
    """Toast 提示浮窗：自绘圆角底色 + 描边，文字颜色由样式表控制。

    顶层 QLabel 的样式表 background 不会被绘制（实测角落仍是标记色，加
    WA_StyledBackground 也无效），因此背景只能靠 paintEvent 自己画。
    """

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        outer = self.rect().adjusted(1, 1, -2, -2)
        painter.setBrush(TOAST_BG)
        painter.setPen(QPen(TOAST_BORDER, 2))
        painter.drawRoundedRect(outer, 10, 10)
        painter.end()
        super().paintEvent(event)  # 背景画完再交给 QLabel 画文字


# ============ 主窗口 ============
class MainWindow(QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()
        # 界面基础设置（样式集中在 style.py）
        self.setupUi(self)
        style.apply_window(self)

        self.accounts = {}  # name -> SaveProfile
        self.current_profile = None
        self.payload = None
        self.version = "V0.0.0"
        self.chars = []  # [{idx, name, role_id, level}]

        # 第 1 行：存档位置（过长时省略显示，见 set_path_label）
        self.path_label.setWordWrap(False)
        self.set_path_label(SAVES_DIR)

        # 连接信号
        self.relief_btn.clicked.connect(self.do_relief)
        self.backup_btn.clicked.connect(self.do_backup)
        self.restore_btn.clicked.connect(self.do_restore)
        self.delete_btn.clicked.connect(self.do_delete_backup)
        self.export_btn.clicked.connect(self.do_export_save)
        self.import_btn.clicked.connect(self.do_import_save)

        # 全局热键：备份 F7 / 恢复 F8 / 删除 F9（切到其它窗口也生效）
        self.hotkeys = {1: self.do_backup, 2: self.do_restore, 3: self.do_delete_backup}
        vk = {1: 0x76, 2: 0x77, 3: 0x78}  # F7 / F8 / F9 虚拟键码
        hwnd = int(self.winId())
        for hid in self.hotkeys:
            user32.RegisterHotKey(HWND(hwnd), hid, 0, vk[hid])
        self.hotkey_filter = GlobalHotkeyFilter(self.hotkeys)
        QApplication.instance().installNativeEventFilter(self.hotkey_filter)

        # 非阻塞成功提示：屏幕中央的浮窗（2.5s 自动隐藏），底色由 ToastLabel 自绘
        self.toast = ToastLabel()
        self.toast.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.toast.setAttribute(Qt.WA_TranslucentBackground, True)
        self.toast.setStyleSheet(
            f"QLabel{{color:{TOAST_TEXT};padding:12px 24px;font-size:14pt;font-weight:bold;}}"
        )
        self.toast.setAlignment(Qt.AlignCenter)
        self.toast.hide()
        # 复用同一个定时器：连点只会重新计时，避免多个 singleShot 叠加把新的 toast 提前隐藏
        self.toast_timer = QTimer(self)
        self.toast_timer.setSingleShot(True)
        self.toast_timer.timeout.connect(self.toast.hide)

        # 初始化账号下拉
        self.refresh_accounts()
        self.account_combo.currentTextChanged.connect(self.on_account_changed)

        # 开窗时不要把焦点落在第一个控件上：Qt 默认会把焦点给第一个可聚焦子控件，
        # 于是「账号」下拉框一启动就带着聚焦紫框。先把焦点收在窗口本身。
        # QMainWindow 默认 NoFocus，要先允许它接收焦点；用 singleShot 是因为窗口
        # 还没显示时设置焦点不生效（show() 之后才轮到它执行）。
        self.setFocusPolicy(Qt.StrongFocus)
        QTimer.singleShot(0, self.setFocus)

    # ---------- 第 1 行位置文本 ----------
    def set_path_label(self, location):
        """显示存档位置（统一用 %appdata% 形式），放不下时末尾省略。

        QLabel 不具备 elide 能力（没有 setTextElideMode），省略需自己用字体度量算。
        tooltip 始终保留完整的原始路径，鼠标悬停即可查看。
        """
        fm = QFontMetrics(self.path_label.font())
        width = max(0, self.path_label.width() - 4)  # 留点余量，避免边界被裁
        short = f"存档位置：{shorten_path(location)}"
        if fm.horizontalAdvance(short) <= width:
            text = short
        else:
            text = fm.elidedText(short, Qt.TextElideMode.ElideRight, width)  # 放不下：末尾省略
        self.path_label.setText(text)
        self.path_label.setToolTip(str(location))

    # ---------- 成功提示浮窗 ----------
    def show_toast(self, msg):
        self.toast.setText(msg)
        self.toast.adjustSize()
        # 优先居中到怀旧服游戏窗口；游戏未运行（或最小化）时才居中到主屏幕
        pos = game_window_center()
        if pos is None:
            screen = QApplication.primaryScreen()
            center = screen.availableGeometry().center() if screen else self.geometry().center()
            pos = (center.x(), center.y())
        self.toast.move(pos[0] - self.toast.width() // 2,
                        pos[1] - self.toast.height() // 2)
        self.toast.show()
        self.toast_timer.start(2500)  # 已在运行则重新开始计时（连点只保留最后一次）

    def closeEvent(self, event):
        # 注销全局热键，避免退出后仍占用 F7/F8/F9
        if getattr(self, "hotkeys", None):
            hwnd = int(self.winId())
            for hid in self.hotkeys:
                user32.UnregisterHotKey(HWND(hwnd), hid)
        super().closeEvent(event)

    # ---------- 账号 / 角色 ----------
    def refresh_accounts(self):
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        self.accounts.clear()
        profiles = decrypt.list_profiles()
        active = decrypt.active_profile_name()
        default_idx = 0
        for i, p in enumerate(profiles):
            self.accounts[p.name] = p
            self.account_combo.addItem(p.name)
            if p.name == active:
                default_idx = i
        if profiles:
            self.account_combo.setCurrentIndex(default_idx)
        self.account_combo.blockSignals(False)
        self.on_account_changed(self.account_combo.currentText())

    def on_account_changed(self, name):
        location = SAVES_DIR / name if name else SAVES_DIR
        self.set_path_label(location)
        self.current_profile = self.accounts.get(name)
        self.payload = None
        self.version = "V0.0.0"
        self.chars = []
        if self.current_profile is None:
            self.char_combo.clear()
            self.refresh_backups()
            return
        # 存档文件/目录不存在 => 该账号存档已被外部删除，刷新账号列表重新枚举，不弹错误
        if not self.current_profile.save_file.exists():
            if getattr(self, "refreshing", False):
                # 已刷新过却仍选中此已删账号：避免无限递归，直接清空
                self.char_combo.clear()
                self.refresh_backups()
                return
            self.refreshing = True
            try:
                self.refresh_accounts()
            finally:
                self.refreshing = False
            return
        try:
            self.payload, self.version = load_payload(self.current_profile)
        except Exception as e:
            QMessageBox.critical(self, "读取失败", f"无法解密存档：\n{e}")
            self.char_combo.clear()
            self.refresh_backups()
            return
        self.populate_chars()
        self.refresh_backups()

    def populate_chars(self):
        self.char_combo.blockSignals(True)
        self.char_combo.clear()
        self.chars = []
        chars = self.payload.get("characters") or []
        for idx, c in enumerate(chars):
            if not isinstance(c, dict):
                continue
            ident = c.get("identity") or {}
            prog = c.get("progression") or {}
            name = ident.get("name", f"角色{idx}")
            role_id = ident.get("role_id", "")
            level = prog.get("level", 0)
            try:
                level = int(level)
            except (TypeError, ValueError):
                level = 0
            self.chars.append({"idx": idx, "name": name, "role_id": role_id, "level": level})
            self.char_combo.addItem(f"{name}（{role_id}）Lv.{level}")
        self.char_combo.blockSignals(False)

    # ---------- 开荒减负 ----------
    def do_relief(self):
        if self.current_profile is None or self.payload is None:
            QMessageBox.warning(self, "提示", "请先选择有效账号。")
            return
        if not self.chars:
            QMessageBox.warning(self, "提示", "该存档没有角色数据。")
            return
        ci = self.char_combo.currentIndex()
        if ci < 0 or ci >= len(self.chars):
            QMessageBox.warning(self, "提示", "请选择角色。")
            return
        ch = self.chars[ci]
        if ch["level"] > 10:
            QMessageBox.warning(
                self, "等级过高",
                f'角色【{ch["name"]}（{ch["role_id"]}）】当前 Lv.{ch["level"]}，'
                f"开荒减负仅限等级 <= 10 的新手角色。",
            )
            return

        kp_ids = kunpeng_ids(ch["role_id"])
        if not kp_ids:
            QMessageBox.warning(self, "无套装数据", f'找不到角色【{ch["role_id"]}】的鲲鹏套装数据。')
            return

        owned = owned_kunpeng_ids(self.payload, ch["idx"], kp_ids)
        missing = [k for k in kp_ids if k not in owned]

        if not missing:
            QMessageBox.information(
                self, "已拥有",
                f'角色【{ch["name"]}（{ch["role_id"]}）】已拥有鲲鹏之征服者套装，无需减负。',
            )
            return

        # 确保 inventory.equipment 存在
        char = self.payload["characters"][ch["idx"]]
        inv = char.setdefault("inventory", {})
        eq_list = inv.setdefault("equipment", [])
        for kid in missing:
            eq_list.append({"id": float(kid), "uid": gen_uid()})

        try:
            save_payload(self.current_profile, self.payload)
        except Exception as e:
            QMessageBox.critical(self, "写回失败", f"加密回写失败：\n{e}")
            return

        # 刷新（重新解密，确保界面与磁盘一致）
        try:
            self.payload, self.version = load_payload(self.current_profile)
            self.populate_chars()
            self.char_combo.setCurrentIndex(ci)
        except Exception:
            pass

        QMessageBox.information(
            self, "完成",
            f"已给予角色【{ch["name"]}（{ch["role_id"]}）】{len(missing)} 件鲲鹏装备到背包"
        )

    # ---------- 备份 / 恢复 ----------
    def fmt_backup(self, ver, t, zpath, note="", disp_fmt="%Y-%m-%d %H:%M:%S"):
        """备份下拉框与中央提示共用的显示格式：`版本 时间[ 注释]`。

        disp_fmt 由 parse_backup_name 按文件名里实际写到的精度给出（只写到日期就不补
        00:00:00）；文件名尾部的自定义注释（如"刷新前"）追加在最后；
        时间解析不出来则整串按注释处理。
        """
        if t is None:
            # 无时间：整串按注释处理（下划线已转空格），不再额外拼版本号
            return note or zpath.stem
        base = f"{ver} {t.strftime(disp_fmt)}"
        return f"{base} {note}" if note else base

    def refresh_backups(self):
        self.restore_combo.blockSignals(True)
        self.restore_combo.clear()
        if self.current_profile is None:
            self.restore_combo.blockSignals(False)
            return
        for ver, t, zpath, note, fmt in self.list_backups(self.current_profile):
            self.restore_combo.addItem(self.fmt_backup(ver, t, zpath, note, fmt), str(zpath))
        self.restore_combo.blockSignals(False)

    def list_backups(self, profile):
        gfp_dir = BACKUPS_DIR / profile.name
        if not gfp_dir.is_dir():
            return []
        res = []
        for z in gfp_dir.glob("*.zip"):
            ver, t, note, fmt = parse_backup_name(z.stem)
            res.append((ver, t, z, note, fmt))
        res.sort(
            key=lambda x: (version_key(x[0]), x[1] or datetime.min),
            reverse=True,
        )
        return res

    def do_backup(self):
        if self.current_profile is None or self.payload is None:
            QMessageBox.warning(self, "提示", "请先选择有效账号。")
            return
        gfp_dir = BACKUPS_DIR / self.current_profile.name
        gfp_dir.mkdir(parents=True, exist_ok=True)
        file_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_path = gfp_dir / f"{self.version}_{file_time}.zip"
        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
                for f in self.current_profile.dir.iterdir():
                    if f.is_file():
                        z.write(f, arcname=f.name)
        except Exception as e:
            QMessageBox.critical(self, "备份失败", f"压缩出错：\n{e}")
            return
        self.refresh_backups()
        # 选中刚生成的备份
        for i in range(self.restore_combo.count()):
            if self.restore_combo.itemData(i) == str(zip_path):
                self.restore_combo.setCurrentIndex(i)
                break
        try:
            bt = datetime.strptime(file_time, "%Y%m%d_%H%M%S")
        except ValueError:
            bt = None
        self.show_toast(f"账号【{self.current_profile.name}】已备份存档：{self.fmt_backup(self.version, bt, zip_path)}")

    def do_restore(self):
        if self.current_profile is None:
            QMessageBox.warning(self, "提示", "请先选择有效账号。")
            return
        if self.restore_combo.count() == 0:
            QMessageBox.warning(self, "提示", "该账号还没有备份。")
            return
        data = self.restore_combo.currentData()
        if not data:
            QMessageBox.warning(self, "提示", "请选择要恢复的备份。")
            return
        zip_path = Path(data)
        if not zip_path.is_file():
            QMessageBox.critical(self, "错误", "备份文件不存在。")
            self.refresh_backups()  # 文件已失效，刷新下拉框剔除该项
            return
        bdisp = self.restore_combo.currentText()  # 下拉框同款显示格式
        # confirm = QMessageBox.question(
        #     self, "确认恢复",
        #     f"将恢复账号【{self.current_profile.name}】的备份存档【{bdisp}】，是否确定？",
        #     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        # )
        # if confirm != QMessageBox.StandardButton.Yes:
        #     return
        try:
            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(self.current_profile.dir)
        except Exception as e:
            QMessageBox.critical(self, "恢复失败", f"解压出错：\n{e}")
            return
        # 刷新界面
        try:
            self.payload, self.version = load_payload(self.current_profile)
            self.populate_chars()
        except Exception as e:
            QMessageBox.warning(self, "提示", f"恢复成功，但重新读取存档失败：\n{e}")
        self.show_toast(f"账号【{self.current_profile.name}】已恢复备份存档：{bdisp}")

    def do_delete_backup(self):
        if self.current_profile is None:
            QMessageBox.warning(self, "提示", "请先选择有效账号。")
            return
        if self.restore_combo.count() == 0:
            QMessageBox.warning(self, "提示", "该账号还没有备份。")
            return
        data = self.restore_combo.currentData()
        if not data:
            QMessageBox.warning(self, "提示", "请选择要删除的备份。")
            return
        zip_path = Path(data)
        if not zip_path.is_file():
            QMessageBox.critical(self, "错误", "备份文件不存在。")
            self.refresh_backups()  # 文件已失效，刷新下拉框剔除该项
            return

        disp = self.restore_combo.currentText()  # 下拉框同款显示格式
        cur_idx = self.restore_combo.currentIndex()

        # 仅当当前账号只剩最后 1 个备份时才弹窗确认，避免误删全部备份
        if self.restore_combo.count() == 1:
            confirm = QMessageBox.question(
                self, "确认删除",
                f"【{disp}】是账号【{self.current_profile.name}】的最后一个备份存档，是否删除？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

        try:
            zip_path.unlink()
        except Exception as e:
            QMessageBox.critical(self, "删除失败", f"删除出错：\n{e}")
            return
        self.refresh_backups()
        # 备份已删空：账号备份目录（backups/<账号名>）为空时一并移除，避免残留空文件夹
        acct_dir = BACKUPS_DIR / self.current_profile.name
        try:
            if acct_dir.is_dir() and not any(acct_dir.iterdir()):
                acct_dir.rmdir()
        except OSError:
            pass
        # 删除后切到上一个备份（仍保留则定位到被删项上方，无项则不切换）
        if self.restore_combo.count() > 0:
            self.restore_combo.setCurrentIndex(max(0, cur_idx - 1))
        self.show_toast(f"账号【{self.current_profile.name}】已删除备份存档：{disp}")

    # ---------- 账号存档导入 / 导出 ----------
    def do_export_save(self):
        """把当前账号的存档目录压缩为 zip 导出到桌面。"""
        if self.current_profile is None:
            QMessageBox.warning(self, "提示", "请先选择有效账号。")
            return
        name = self.current_profile.name
        dst = desktop_dir() / f"{name}.zip"
        if dst.exists():
            confirm = QMessageBox.question(
                self, "确认覆盖",
                f"桌面已存在存档文件【{dst.name}】，是否覆盖？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
        try:
            with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
                for f in self.current_profile.dir.iterdir():
                    if f.is_file():
                        z.write(f, arcname=f.name)
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"导出出错：\n{e}")
            return
        QMessageBox.information(self, "导出成功", f"账号【{name}】的存档已导出到桌面。")

    def backup_profile_dir(self, name, src_dir):
        """把 src_dir 压缩备份到 BACKUPS_DIR/<name>/<版本>_<时间>.zip；成功返回 True。"""
        try:
            _, ver = load_payload(decrypt.SaveProfile(name, src_dir))
        except Exception:
            ver = "V0.0.0"
        out_dir = BACKUPS_DIR / name
        out_dir.mkdir(parents=True, exist_ok=True)
        dst = out_dir / f"{ver}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        try:
            with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
                for f in src_dir.iterdir():
                    if f.is_file():
                        z.write(f, arcname=f.name)
        except Exception as e:
            QMessageBox.critical(self, "备份失败", f"导入前备份出错：\n{e}")
            return False
        return True

    def do_import_save(self):
        """从 zip / 7z / rar 导入账号存档。

        账号名规则：.dat 在包内根目录时取压缩包文件名；在子目录时取其父目录名，
        解压时只把该目录（即 .dat 所在目录）下的内容解到 saves/<账号名>。
        """
        path_str, _ = QFileDialog.getOpenFileName(
            self, "选择存档文件", str(desktop_dir()), "存档压缩包 (*.zip *.7z *.rar)"
        )
        if not path_str:
            return
        arc_path = Path(path_str)
        if not arc_path.is_file():
            QMessageBox.critical(self, "错误", "文件不存在。")
            return
        try:
            kind = archive_kind(arc_path)
            names = archive_files(arc_path, kind)
        except ValueError as e:
            QMessageBox.warning(self, "提示", str(e))
            return
        except Exception as e:
            QMessageBox.critical(self, "导入失败", f"无法读取压缩包：\n{e}")
            return
        # 校验含 .dat 存档数据，并按其所在目录推导账号名与解压前缀
        name, prefix = archive_target(names, arc_path.stem)
        if name is None:
            QMessageBox.warning(self, "提示", "该压缩包内没有 .dat 存档数据，无法导入。")
            return
        target_dir = SAVES_DIR / name
        has_existing = target_dir.is_dir() and any(
            p.is_file() and p.suffix.lower() == ".dat" for p in target_dir.iterdir()
        )
        if has_existing:
            confirm = QMessageBox.question(
                self, "确认导入",
                f"将覆盖账号【{name}】的当前存档，是否确定？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
            # 覆盖前先备份一次当前存档
            if not self.backup_profile_dir(name, target_dir):
                return
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            extract_archive_to(arc_path, kind, target_dir, prefix)
        except Exception as e:
            QMessageBox.critical(self, "导入失败", f"解压出错：\n{e}")
            return
        # 刷新界面并选中导入的账号
        self.refresh_accounts()
        idx = self.account_combo.findText(name)
        if idx >= 0:
            self.account_combo.setCurrentIndex(idx)
        QMessageBox.information(self, "导入成功", f"账号【{name}】的存档已恢复。")


def path(file: str):
    return str(BASE_DIR / file)



if __name__ == "__main__":
    app = QApplication([])
    style.apply(app)  # 下拉框的悬停/聚焦外观（见 style.py）
    trans = QTranslator()
    trans.load(path("zh_CN.qm"))
    app.installTranslator(trans)
    window = MainWindow()
    window.show()
    app.exec()
