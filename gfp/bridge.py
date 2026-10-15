# -*- coding: utf-8 -*-
"""SWF 注入服务（对标 mole 项目 bridge.py 的 swf 处理部分，命名保持一致）。

本地 HTTP 服务，Flash 经进程级代理过来：
- 请求命中 `swf/replace/` 下的同名文件 → 返回本地文件（覆盖官服同名 SWF/XML）；
- 请求命中 `swf/append/` 下的同名文件 → 返回本地文件（额外 mod）；
- 其余请求原样透传到上游 `http://gf.61.com`（保留缓存头、流式转发）。

域名机制（本进程 WinINet 代理，内存级）：
- Flash 以**官方域名、不带端口**的 URL 加载（`http://gf.61.com/…`）⇒ sol 归官方域
  （共享官方账号数据）、WinINet 缓存键与官方浏览器完全一致（可读官方缓存）；
- `set_proxy()` 把**本进程** WinINet HTTP 代理指向本服务（内存级；不改系统设置、退出即失效、
  多开互不干扰）⇒ Flash 的 HTTP 请求（绝对 URI 形式）必然到达本服务，本地替换/中继后返回
  （与"别人的登录器"同机制）；URL 域名不变 ⇒ 身份/缓存特性不受影响。

用法：主程序启动时 `port = start_bridge()`，再把 Flash 的 LoadMovie 指向
`injector_url("/Client.swf?t=...")`。
"""
import ctypes
import time
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from loguru import logger
from requests import Session

base_dir = Path(__file__).resolve().parent
replace_dir = base_dir / "swf" / "replace"  # 替换 SWF（覆盖官服同名文件）
append_dir = base_dir / "swf" / "append"    # 追加 SWF（额外 mod）
official_host = "gf.61.com"                 # 官方资源服域名（Flash 的身份 / sol 归属 / 缓存键都靠它）
chunk_size = 4096                           # 流式收发块大小

session = Session()
session.trust_env = False  # 上游必须直连：本进程代理已指向自己（set_proxy）——走代理会自环；
                           # 同时不走环境变量代理（开着 Fiddler 之类时也不会被劫走）
injector_prefer_port = 11000  # 默认端口（mole 从 10000 起，我们从 11000 起避开它的号段）；
                              # 端口不写进 URL（URL 恒为 http://gf.61.com/… 官方形态 ⇒ 缓存键与官方一致）——
                              # 实际端口通过进程级代理设置告诉 wininet（见 set_proxy）
injector_port: int = 0        # start_bridge() 后为实际监听端口
injector_started = False      # 幂等标记：重复调用 start_bridge() 不重复起服务（__main__ 与窗口各调一次）
rules_file = replace_dir / "rules.txt"   # 规则表：每行 "<URL 匹配串> | <本地文件路径>"
rules_cache = None
rules_ts = 0.0


class INTERNET_PROXY_INFO(ctypes.Structure):
    """WinINet 代理配置结构（InternetSetOptionA 的 INTERNET_OPTION_PROXY(38) 参数；A 版=窄字符串）。"""
    _fields_ = [("dwAccessType", ctypes.c_ulong),   # 3 = INTERNET_OPEN_TYPE_PROXY
                ("lpszProxy", ctypes.c_char_p),
                ("lpszProxyBypass", ctypes.c_char_p)]


def set_proxy(port: int, host: str = "127.0.0.1") -> None:
    """把**本进程**的 WinINet HTTP 代理指向本地桥接 —— 只影响本进程，不改系统代理设置。

    ⚠ 实测要点（2026-10-16）：
    · NULL 句柄 + INTERNET_OPTION_PROXY(38) 是**进程内存级**设置：注册表分毫不动、进程退出即失效、
      新开的会话自动继承、其它进程不受影响（"别人的登录器"同款机制，无需备份/还原）；
    · 必须用 **A 版**（InternetSetOptionA + 窄字符串）——W 版在 NULL 句柄下字符串会乱码、不生效（实测）；
    · 只代理 http（https 直连）；勿用 INTERNET_OPTION_PER_CONNECTION_OPTION(75)——它写注册表全局值（实测）。
    URL 域名不变 ⇒ WinINet 缓存键/sol 归属不受影响。"""
    try:
        info = INTERNET_PROXY_INFO(3, f"http={host}:{port}".encode(), b"")
        if ctypes.windll.wininet.InternetSetOptionA(None, 38, ctypes.byref(info), ctypes.sizeof(info)):
            logger.info(f"[inject] 本进程 WinINet 代理已指向本地服务: http={host}:{port}（仅本进程，不改系统设置）")
        else:
            logger.warning(f"[inject] 进程代理设置失败（err={ctypes.get_last_error()}）")
    except Exception as e:
        logger.warning(f"[inject] 进程代理设置异常：{e}")


def load_rules() -> list:
    """读 replace/rules.txt（带 1 秒缓存，避免每请求读盘）。"""
    global rules_cache, rules_ts
    if rules_cache is not None and time.perf_counter() - rules_ts <= 1.0:
        return rules_cache
    rules_cache = []
    try:
        if rules_file.is_file():
            for line in rules_file.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "|" not in line:
                    continue
                pat, sep, path = line.partition("|")
                rules_cache.append((pat.strip(), path.strip()))
    except OSError:
        pass
    rules_ts = time.perf_counter()
    return rules_cache


def find_local(name: str, url: str) -> "tuple[str, Path] | None":
    """按优先级找本地替换文件（对应"别人的登录器"那张规则表的能力）：
    ① `swf/replace/rules.txt` 规则表：每行 `<URL 匹配串> | <本地文件路径>`（`#` 注释、空行忽略）；
    ② `replace/<URL 路径镜像>`，如 `replace/module/app/EveryDayOnlinePanel.swf`；
    ③ `replace/<文件名>` / `append/<文件名>`（按文件名找，兼容旧用法）。
    返回 (来源说明, 文件路径)；都没命中返回 None。"""
    key = url.split("?", 1)[0]
    for pat, path in load_rules():                      # ① 规则表
        if pat in key:
            p = Path(path)
            if p.is_file():
                return f"rules.txt ← {pat}", p
    rel = key.split("://", 1)[-1]                       # ② 目录镜像：去掉 http://
    rel = rel.split("/", 1)[-1] if "/" in rel else rel  # 再去掉域名
    folders = (("replace", replace_dir), ("append", append_dir))
    if rel:
        for label, folder in folders:
            p = folder / Path(rel)
            if p.is_file():
                return f"{label}/{rel}", p
    for label, folder in folders:                       # ③ 文件名（旧行为）
        p = folder / name
        if p.is_file():
            return f"{label}/", p
    return None


def content_type_for(name: str) -> str:
    lower = name.lower()
    if lower.endswith(".swf"):
        return "application/x-shockwave-flash"
    if lower.endswith(".xml"):
        return "application/xml"
    return "application/octet-stream"


class InjectHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive：Flash 复用连接
    timeout = 15                   # 空闲连接回收，避免刷新后僵尸线程堆积

    def log_message(self, fmt, *args):
        pass  # 静默 BaseHTTPRequestHandler 的 stderr 访问日志

    def serve_local_stream(self, path: Path, content_type: str) -> None:
        """分块流式返回本地文件（mole `serve_local_stream` 同款：边读边写、不整块入内存）。
        缓存：`no-cache` + `Last-Modified` ⇒ 每次条件请求校验：文件没变回 **304**（几 MB 的 SWF
        不重传），改了 `swf/replace` 里的文件**立刻生效**。⚠ 勿改 no-store：与 304 分支自相矛盾。"""
        try:
            stat = path.stat()
        except OSError:
            self.send_response(404)
            self.end_headers()
            return
        last_modified = formatdate(stat.st_mtime, usegmt=True)
        if self.headers.get("If-Modified-Since") == last_modified:
            self.send_response(304)
            self.send_header("Last-Modified", last_modified)
            self.end_headers()
            logger.info(f"[inject] 本地 {path.name} → 304（Flash 缓存命中，未重传）")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(stat.st_size))
        self.send_header("Last-Modified", last_modified)
        self.send_header("Cache-Control", "no-cache")   # 与上面的 304 分支配合（mole 同款）
        self.end_headers()
        start = time.perf_counter()
        sent = 0
        try:
            with path.open("rb") as file:
                while True:
                    chunk = file.read(chunk_size)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    sent += len(chunk)
        except OSError:
            pass  # 客户端中途断开：静默结束
        # 「发出 X/Y KB」能直接看出是不是传输中断（发出 < 文件大小 ⇒ 客户端中途断了）
        logger.info(f"[inject] 本地 {path.name} → 发出 {sent // 1024}/{stat.st_size // 1024}KB "
                    f"{(time.perf_counter() - start) * 1000:.0f}ms")

    def dispatch(self) -> None:
        # 代理请求行是绝对 URI（http://host/path?query）→ 拆出目标 host 与路径
        path = self.path
        proxy_host = None
        if path[:7].lower() == "http://":
            rest = path[7:]
            slash = rest.find("/")
            proxy_host, path = (rest, "/") if slash < 0 else (rest[:slash], rest[slash:])
        name = path.split("?", 1)[0].rsplit("/", 1)[-1]
        lower = name.lower()
        # 1) 本地替换（仅官方域名）：① rules.txt ② replace/<URL 路径镜像> ③ 按文件名（replace→append）
        if (proxy_host is None or proxy_host.lower() == official_host) and (lower.endswith(".swf") or lower.endswith(".xml")):
            found = find_local(name, path)
            if found:
                label, local = found
                logger.info(f"[inject] {name} → 本地 {label}")
                self.serve_local_stream(local, content_type_for(name))
                return
        # 2) 其余请求透传上游：官方域名 → 官服；其它域名（代理卷进来的）→ 原目标主机
        self.relay(path, proxy_host or official_host)

    def relay(self, path: str, host: str = official_host) -> None:
        """透传上游（对标 mole 的 `relay_stream`）：
        · `host`：官方域名走官服；代理卷进来的其它域名按原目标主机转发（通用代理行为）；
        · **转发客户端的条件请求头**（If-None-Match / If-Modified-Since）⇒ 上游可回 304，
          Flash 直接命中自身缓存 —— 这是"能不能命中缓存"的关键一步；
        · 保留上游 `content-encoding` / `content-length`（压缩体原样透传，不二次解压）；
        · 上游没有任何缓存指令时补 `max-age=2592000`，促使 Flash 缓存。"""
        start = time.perf_counter()
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in ("proxy-connection", "proxy-authorization", "host")}
        body = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0)) or None
        target = f"http://{host}{path}"   # Host 头由 requests 按 URL 自动生成
        logger.debug(f"[inject] 透传 {target}")
        try:
            resp = session.request(self.command, target, headers=headers,
                                   data=body, stream=True, timeout=8)
        except Exception as e:
            logger.warning(f"[inject] 透传失败 {host}{path}: {e}")
            self.send_response(502)
            self.end_headers()
            return
        has_length = "content-length" in resp.headers
        has_cache = False
        self.send_response(resp.status_code)
        for k, v in resp.headers.items():
            lk = k.lower()
            if lk in ("transfer-encoding", "connection"):
                continue
            if lk == "content-encoding" and not has_length:
                # 下面用 resp.content 取数据（已自动解压成明文）⇒ 必须去掉压缩声明，
                # 否则客户端按 gzip 解压明文会失败（主 SWF 直接加载不出来）
                continue
            if lk in ("cache-control", "pragma", "expires"):
                has_cache = True   # 上游自带缓存指令（含 no-store/no-cache）⇒ 原样遵循
            self.send_header(k, v)
        if not has_cache:
            self.send_header("Cache-Control", "max-age=2592000")
        sent = 0
        try:
            if not has_length:
                # 上游分块传输（或压缩且未给长度）：按实际长度补 Content-Length
                # （否则 keep-alive 下客户端会一直等）
                data = resp.content
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if resp.status_code != 304:
                    self.wfile.write(data)
                    sent = len(data)
            else:
                self.end_headers()
                if resp.status_code != 304:   # 304 无实体，直接跳过
                    # 压缩体原样透传（decode_content=False 保留 gzip 字节），与转发的头一致
                    for chunk in resp.raw.stream(chunk_size, decode_content=False):
                        if chunk:
                            self.wfile.write(chunk)
                            sent += len(chunk)
        except OSError:
            pass  # 客户端中途断开（如刷新取消下载）
        finally:
            resp.close()
        logger.info(f"[inject] 透传 {path.rsplit('/', 1)[-1]} → {resp.status_code} "
                    f"{sent // 1024}KB {(time.perf_counter() - start) * 1000:.0f}ms")

    def do_GET(self):
        self.dispatch()

    def do_POST(self):
        self.dispatch()


class ExclusiveHTTPServer(ThreadingHTTPServer):
    """⚠ 必须关闭地址复用（mole 的 ExclusiveHTTPServer 同款）：
    `HTTPServer` 默认 `allow_reuse_address = 1`，而 Windows 下 `SO_REUSEADDR` 允许**不同进程
    同时 bind 同一端口** —— 于是本服务会"假装绑定成功"，实际请求被先占的进程（如 mole 的
    注入服务）接走，表现为游戏加载异常。设为 0 后占用即 bind 失败 ⇒ 顺延到真正空闲的端口。"""
    allow_reuse_address = 0
    daemon_threads = True  # 连接线程随主线程退出（配合 InjectHandler.timeout 回收空闲连接）

    def handle_error(self, request, client_address):
        # Flash 刷新/取消下载时会直接 RST keep-alive 连接，属正常客户端行为，压掉 traceback 噪声
        import sys
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError)):
            return
        super().handle_error(request, client_address)


def start_bridge(port: int = injector_prefer_port) -> int:
    """启动本地注入服务，返回实际端口（**幂等**：已启动则直接返回现有端口）。

    端口策略：默认 **11000**，被占用时按 **+2 依次顺延**（11000 → 11002 → … → 11038）；
    端口不写进 URL（URL 恒为 `http://gf.61.com/…` 官方形态 ⇒ WinINet 缓存键与官方一致），
    实际端口通过进程级代理设置（`set_proxy`）告诉 wininet。"""
    global injector_port, injector_started
    if injector_started:
        return injector_port
    last_error = None
    for candidate in range(port, port + 40, 2):
        try:
            server = ExclusiveHTTPServer(("127.0.0.1", candidate), InjectHandler)
        except OSError as e:
            last_error = e
            logger.warning(f"[inject] 端口 {candidate} 已被占用，顺延")
            continue
        injector_port = candidate
        injector_started = True
        set_proxy(injector_port)    # ★ 主通道：本进程 WinINet http 代理 → 本地服务（内存级，退出即失效）
        Thread(target=server.serve_forever, daemon=True, name="bridge").start()
        logger.info(f"[inject] 本地 SWF 注入服务: 127.0.0.1:{injector_port} ← {official_host}（Flash 身份=官方域名）")
        return candidate
    raise RuntimeError(f"注入服务端口 {port}~{port + 38} 全被占用：{last_error}")


def injector_url(path: str = "/Client.swf") -> str:
    """Flash 的 LoadMovie 目标：**官方域名 + 官方形态（不带端口）**。

    域名决定身份（sol 归属 / WinINet 缓存键）⇒ 必须用官方域名；
    端口不进 URL ⇒ 缓存键与官方一致（读官方缓存的关键），
    实际连接由进程级代理（`set_proxy`）落到本服务。"""
    return f"http://{official_host}{path}"
