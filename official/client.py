# -*- coding: utf-8 -*-
"""功夫派协议端：官方登录流程复刻 + 存物品

全部对照 2026-10-12 05:13 实机抓包逐字节复刻：
  登录服 118.89.141.225:1863
    连接①: 103 登录(pwd+固定字段) → 收 session(16B)；107 角色列表 → 取 creatTime/level
    连接②: 105 服务器列表 → 取 1服 ip:port（118.89.142.223:1204）
  游戏服 118.89.142.223:1204
    1001 游戏登录（免加密，session 用登录服的）→ 2220B 登录数据
    2619 存物品 (itemID, count)（加密发送，serial 链式）

用法:
  python client.py                        # 完整登录并存入 1500973 ×1
  python client.py --deposit 1500973:829  # 指定物品:数量
  python client.py --no-deposit           # 只登录不进物品
"""
import hashlib
import re
import socket
import struct
import sys
import time
from os import environ
from pathlib import Path

USER_ID = 0   # 运行时由 derive_uid() 从 login.sol 填充，代码不落账号敏感信息
LOGIN_HOST, LOGIN_PORT = "118.89.141.225", 1863
GAME_HOST, GAME_PORT = "118.89.142.223", 1204
SERVER_VERSION = 20150515   # 官方 client_type=1 的服务器版本号（抓包 0x013378F3）
GAME_ID = 6

KEY = b"taomee_konfu_rock77#!%&~\x00"
LOG_FILE = Path(__file__).resolve().parent / "client.log"


def find_login_sol():
    """login.sol 位置动态发现（参考 mole.py 的 #SharedObjects 遍历方式）。
    标准位置: %APPDATA%\\Macromedia\\Flash Player\\#SharedObjects\\<站点ID>\\gf.61.com\\#gf\\common\\login.sol
    兼容 PPAPI（浏览器内置 Flash）的 Pepper Data 目录（如 360 极速浏览器）。"""
    cands = []
    bases = [
        Path(environ["APPDATA"]) / "Macromedia" / "Flash Player" / "#SharedObjects",
        Path(environ["LOCALAPPDATA"]) / "Macromedia" / "Flash Player" / "#SharedObjects",
        Path(r"D:\Software\360ChromeX\Chrome\User Data\Default\Pepper Data\Shockwave Flash\WritableRoot\#SharedObjects"),
    ]
    for base in bases:
        if base.exists():
            cands += list(base.glob("*/gf.61.com/#gf/common/login.sol"))
    return cands[0] if cands else None


def derive_pwd():
    """从 login.sol 提取 encodePWD（4 段乱序的 md5）→ 还原顺序 → md5，即登录包密码字段。"""
    sol = find_login_sol()
    if sol is None:
        raise SystemExit("[!] 未找到 login.sol —— 请先在浏览器里登录一次功夫派官网（勾选记住密码）")
    data = sol.read_bytes()
    for m in re.finditer(rb"[0-9a-f]{32}", data):
        enc = m.group().decode()
        raw = enc[8:16] + enc[0:8] + enc[24:32] + enc[16:24]
        return hashlib.md5(raw.encode()).hexdigest()
    raise SystemExit("[!] login.sol 中没有找到密码字段（在官网勾选记住密码登录一次即可）")


def derive_uid():
    """从 login.sol 提取账号 ID（id 整数字段，AMF3 u29 编码；兜底 nickName 数字串）。
    与 derive_pwd 同源，代码里不出现任何真实账号。"""
    sol = find_login_sol()
    if sol is None:
        raise SystemExit("[!] 未找到 login.sol —— 请先在浏览器里登录一次功夫派官网（勾选记住密码）")
    data = sol.read_bytes()
    i = data.find(b"\x05id\x04")
    if 0 <= i <= len(data) - 5:
        v, j = 0, i + 4
        for _ in range(3):
            c = data[j]; j += 1
            if c >= 0x80:
                v = (v << 7) | (c & 0x7F)
            else:
                return (v << 7) | c
        return (v << 8) | data[j]
    m = re.search(rb"nickName\x06[\x01-\x7F](\d{5,})", data)
    if m:
        return int(m.group(1))
    raise SystemExit("[!] login.sol 中没有账号 ID 字段（在官网登录一次即可）")


def log_line(s):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(s + "\n")
    except Exception:
        pass


def gfp_encrypt(plain: bytes) -> bytes:
    res = bytearray(len(plain) + 1)
    ki = 0
    for i in range(len(plain)):
        res[i] = plain[i] ^ KEY[ki % 25]
        ki += 1
        if ki > 25:   # 官方序列 = 0..24 后 key[0] 双发（周期26）
            ki = 0
    for i in range(len(res) - 1, 0, -1):
        res[i] |= res[i - 1] >> 3
        res[i - 1] = (res[i - 1] << 5) % 256
    res[0] |= 3
    return bytes(res)


def gfp_decrypt(wire: bytes) -> bytes:
    if not wire:
        return wire
    res = bytearray(len(wire) - 1)
    ki = 0
    for i in range(len(res)):
        res[i] = ((wire[i] >> 5) | ((wire[i + 1] << 3) % 256)) ^ KEY[ki % 25]
        ki += 1
        if ki > 25:
            ki = 0
    return bytes(res)


def next_serial(prev: int, cmd: int, plain: bytes) -> int:
    # SocketImplGFP.as:41 直译：serial - serial//7 + 151 + 明文len+18 %13 + cmd%23 + crc(明文)
    crc = 0
    for b in plain:
        crc ^= b
    return (prev - prev // 7 + 151 + (len(plain) + 18) % 13 + cmd % 23 + crc) & 0xFFFFFFFF


class Conn:
    def __init__(self, host, port, label, use_growth=False):
        self.label = label
        self.sock = socket.create_connection((host, port), timeout=8)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buf = b""
        self.use_growth = use_growth   # 游戏服发包计数递增；登录服恒 0（LoginSocket.as: writeInt(0)）
        self.growth = 0
        print(f"[*] 已连接 {label} {host}:{port}")

    def send(self, cmd, body, serial, encrypt):
        wire = gfp_encrypt(body) if encrypt else body
        g = self.growth if self.use_growth else 0
        pkt = struct.pack("!IHIII", 18 + len(wire), cmd, USER_ID, serial, g) + wire
        self.sock.sendall(pkt)
        if self.use_growth:
            self.growth += 1
        print(f"[==>] {self.label} cmd={cmd} len={len(pkt)} serial={serial} growth={g} body={body.hex().upper()[:80]}")
        log_line(f"[==>]{pkt.hex().upper()}")
        return pkt

    def recv_packet(self, timeout=8.0):
        self.sock.settimeout(timeout)
        while len(self.buf) < 4:
            c = self.sock.recv(65536)
            if not c:
                raise ConnectionError(f"{self.label} 连接被关闭")
            self.buf += c
        ln = struct.unpack_from("!I", self.buf, 0)[0]
        while len(self.buf) < ln:
            c = self.sock.recv(65536)
            if not c:
                raise ConnectionError(f"{self.label} 连接被关闭")
            self.buf += c
        pkt, self.buf = self.buf[:ln], self.buf[ln:]
        log_line(f"[<==]{pkt.hex().upper()}")
        return pkt

    def recv_until(self, want_cmd, timeout=8.0):
        deadline = time.monotonic() + timeout
        while True:
            left = max(0.2, deadline - time.monotonic())
            pkt = self.recv_packet(left)
            ln, cmd, uid, serial, growth = struct.unpack_from("!IHIII", pkt, 0)
            if cmd == want_cmd:
                return pkt
            print(f"    (跳过 cmd={cmd} len={ln})")

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def main():
    global USER_ID
    args = sys.argv[1:]
    no_deposit = "--no-deposit" in args
    deposits = [(1500973, 1)]
    if "--deposit" in args:
        item, cnt = args[args.index("--deposit") + 1].split(":")
        deposits = [(int(item), int(cnt))]

    t0 = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"===== 功夫派协议端 {t0} =====")
    log_line(f"===== {t0} =====")

    pwd = derive_pwd()
    USER_ID = derive_uid()
    print(f"[*] 账号 ID: {USER_ID}（来自 login.sol）")
    print(f"[*] 登录密码哈希: {pwd}")

    # ---------- 连接①：103 登录 + 107 角色列表 ----------
    c1 = Conn(LOGIN_HOST, LOGIN_PORT, "登录服①")
    body = pwd.encode() + struct.pack("!III", 0, 6, 0) + bytes(16) + bytes(6) + bytes(64)
    c1.send(103, body, 1, encrypt=False)
    rbody = c1.recv_until(103)[18:]
    flag, session, roles = struct.unpack_from("!I16sI", rbody, 0)
    print(f"[<==] 103 响应: flag={flag} roles={roles} session={session.hex().upper()}")
    if flag != 0:
        print("[!] 登录被拒，终止")
        return

    c1.send(107, session + struct.pack("!I", GAME_ID), 2, encrypt=False)
    rbody = c1.recv_until(107)[18:]
    roleTime = struct.unpack_from("!I", rbody, 28)[0]
    level = struct.unpack_from("!I", rbody, 60)[0]
    if not (1420070400 <= roleTime <= 2000000000):
        roleTime = 1577255752
    if not (1 <= level <= 999):
        level = 120
    print(f"[<==] 107 响应: roleTime={roleTime} level={level}")
    c1.close()

    # ---------- 连接②：105 服务器列表 ----------
    c2 = Conn(LOGIN_HOST, LOGIN_PORT, "登录服②")
    c2.send(105, session + struct.pack("!III", 0, roleTime, level) + struct.pack("!I", GAME_ID), 1, encrypt=False)
    rbody = c2.recv_until(105)[18:]
    ip, port = GAME_HOST, GAME_PORT
    for m in re.finditer(rb"(\d{1,3}(?:\.\d{1,3}){3})", rbody):
        idx = int.from_bytes(rbody[m.end() + 12:m.end() + 16], "big")
        p = int.from_bytes(rbody[m.end():m.end() + 4], "big")
        if idx == 1 and 1 <= p <= 65535:
            ip, port = m.group().decode(), p
            break
    print(f"[<==] 105 响应: 1服 → {ip}:{port}")
    c2.close()

    # ---------- 游戏服：1001 登录 ----------
    c3 = Conn(ip, port, "游戏服", use_growth=True)
    body = session + struct.pack("!5I", roleTime, SERVER_VERSION, 0, 0, GAME_ID) + bytes(64)
    s = next_serial(0, 1001, body)
    c3.send(1001, body, s, encrypt=False)
    pkt = c3.recv_until(1001)
    print(f"[<==] 1001 响应: {len(pkt)}B（2220B = 登录成功）")
    pt = gfp_decrypt(pkt[18:])
    print(f"      明文头: {pt[:48].hex().upper()}")
    if str(USER_ID).encode() not in pt:
        print("[!] 响应里没有账号字段，登录可能异常")

    if no_deposit:
        print("[*] --no-deposit：结束")
        return

    # ---------- 存物品 2619 ----------
    for item, count in deposits:
        plain = struct.pack("!II", item, count)
        s = next_serial(s, 2619, plain)
        c3.send(2619, plain, s, encrypt=True)
        pkt = c3.recv_until(2619)
        ln, cmd, uid, serial, growth = struct.unpack_from("!IHIII", pkt, 0)
        if ln == 18:
            print(f"[结果] 2619 被拒！错误码 = {growth}")
        else:
            rpt = gfp_decrypt(pkt[18:])
            print(f"[结果] 2619 成功回执: {rpt.hex().upper()}")
    print("[*] 完成")


if __name__ == "__main__":
    main()
