# -*- coding: utf-8 -*-
"""SWF 注入服务（对标 mole 项目 bridge.py 的 swf 处理部分，命名保持一致）。

本地 HTTP 服务，Flash 直连：
- 请求命中 `swf/replace/` 下的同名文件 → 返回本地文件（覆盖官服同名 SWF/XML）；
- 请求命中 `swf/append/` 下的同名文件 → 返回本地文件（额外 mod）；
- 其余请求原样透传到官服 `http://gf.61.com`（保留缓存头、流式转发）。

用法：主程序启动时 `port = start_bridge()`，再把 Flash 的 LoadMovie 指向
`injector_url("/Client.swf?t=...")`。
"""
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
upstream_base = "http://gf.61.com"          # 官服基址
chunk_size = 4096                           # 流式收发块大小

session = Session()
session.trust_env = False  # 直连官服：不走环境变量/系统代理（开着 Fiddler 之类时也不会被劫走）
injector_prefer_port = 20000  # 固定起始端口（mole 从 10000 起，我们从 20000 起，避开它的号段）；
                              # 固定端口让 URL 稳定 ⇒ Flash 磁盘缓存能命中；被占用才逐个顺延
injector_port: int = 0        # start_injector() 后为实际监听端口
rules_file = replace_dir / "rules.txt"   # 规则表：每行 "<URL 匹配串> | <本地文件路径>"
_rules_cache = None
_rules_ts = 0.0


def find_local(name: str, url: str) -> "tuple[str, Path] | None":
    """按优先级找本地替换文件（对应"别人的登录器"那张规则表的能力）：
    ① `swf/replace/rules.txt` 规则表：每行 `<URL 匹配串> | <本地文件路径>`（`#` 注释、空行忽略）；
    ② `replace/<URL 路径镜像>`，如 `replace/module/app/EveryDayOnlinePanel.swf`；
    ③ `replace/<文件名>` / `append/<文件名>`（按文件名找，兼容旧用法）。
    返回 (来源说明, 文件路径)；都没命中返回 None。"""
    key = url.split("?", 1)[0]
    # ① 规则表
    for pat, path in _rules():
        if pat in key:
            p = Path(path)
            if p.is_file():
                return f"rules.txt ← {pat}", p
    # ② 目录镜像（按 URL 路径）
    rel = key.split("://", 1)[-1]                    # 去掉 http://
    rel = rel.split("/", 1)[-1] if "/" in rel else rel   # 去掉域名
    if rel:
        for label, folder in (("replace", replace_dir), ("append", append_dir)):
            p = folder / Path(rel)
            if p.is_file():
                return f"{label}/{rel}", p
    # ③ 文件名（旧行为）
    for label, folder in (("replace", replace_dir), ("append", append_dir)):
        p = folder / name
        if p.is_file():
            return f"{label}/", p
    return None


def _rules() -> list:
    """读 replace/rules.txt（带 1 秒缓存，避免每请求都读盘）。"""
    global _rules_cache, _rules_ts
    if _rules_cache is None or time.perf_counter() - _rules_ts > 1.0:
        rules = []
        try:
            if rules_file.is_file():
                for line in rules_file.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "|" not in line:
                        continue
                    pat, _, path = line.partition("|")
                    rules.append((pat.strip(), path.strip()))
        except OSError:
            pass
        _rules_cache = rules
        _rules_ts = time.perf_counter()
    return _rules_cache


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
        缓存：内容照旧进 Flash 磁盘缓存，但用 `no-cache` + `Last-Modified` ⇒ 每次带条件请求校验：
        文件没变回 **304**（几 MB 的 SWF 不重传），改了 `swf/replace` 里的文件**立刻生效**。"""
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
        # no-cache（mole 同款）：内容进 Flash 磁盘缓存，但每次都要带条件请求来校验 ⇒
        # 文件没变回 304（几 MB 的 SWF 不重传），换了 swf/replace 里的文件也立刻生效。
        # ⚠ 之前这里写的是 no-store（禁止缓存）⇒ 与上面的 304 分支自相矛盾（客户端永远不会发条件请求）。
        self.send_header("Cache-Control", "no-cache")
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
        url = self.path        # Flash 的 LoadMovie 指向本服务 ⇒ 一定是相对路径
        name = url.split("?", 1)[0].rsplit("/", 1)[-1]
        lower = name.lower()
        # 1) 本地替换：① rules.txt 规则表 ② replace/<URL 路径镜像> ③ 按文件名（replace→append）
        if lower.endswith(".swf") or lower.endswith(".xml"):
            found = find_local(name, url)
            if found:
                label, local = found
                logger.info(f"[inject] {name} → 本地 {label}")
                self.serve_local_stream(local, content_type_for(name))
                return
        # 2) 其余请求透传上游
        self.relay(upstream_base + url)

    def relay(self, target: str) -> None:
        """透传上游（对标 mole 的 `relay_stream`）：
        · **转发客户端的条件请求头**（If-None-Match / If-Modified-Since）⇒ 上游可回 304，
          Flash 直接命中自身缓存 —— 这是"能不能命中缓存"的关键一步；
        · 保留上游 `content-encoding` / `content-length`（压缩体原样透传，不二次解压）；
        · 上游没有任何缓存指令时补 `max-age=2592000`，促使 Flash 缓存。"""
        start = time.perf_counter()
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in ("proxy-connection", "proxy-authorization", "host")}
        body = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0)) or None
        logger.debug(f"[inject] 透传 {target}")
        try:
            resp = session.request(self.command, target, headers=headers,
                                   data=body, stream=True, timeout=8)
        except Exception as e:
            logger.warning(f"[inject] 透传失败 {target}: {e}")
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
                # 无 content-length 时下面用 resp.content 取数据（已自动解压成明文）
                # ⇒ 必须去掉压缩声明，否则客户端按 gzip 解压明文会失败（主 SWF 直接加载不出来）
                continue
            if lk in ("cache-control", "pragma", "expires"):
                has_cache = True   # 上游自带缓存指令（含 no-store/no-cache）⇒ 原样遵循
            self.send_header(k, v)
        if not has_cache:
            self.send_header("Cache-Control", "max-age=2592000")
        sent = 0
        try:
            if not has_length:
                # 上游分块传输（或压缩且未给长度）：resp.content 已是解压后明文
                # ⇒ 按实际长度补 Content-Length（否则 keep-alive 下客户端会一直等）
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
        logger.info(f"[inject] 透传 {target.rsplit('/', 1)[-1]} → {resp.status_code} "
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
    """启动本地注入服务，返回实际端口。

    **优先用固定端口**（URL 稳定 ⇒ Flash 的磁盘缓存能命中，不必每次重下几 MB 的 SWF）；
    端口被占用时按 **+2 递增**重试（mole 同款：每个实例占一对，`+1` 留给以后可能加入的命令桥），
    最多试 20 对（20000 → 20002 → … → 20038）。"""
    global injector_port
    last_error = None
    for candidate in range(port, port + 40, 2):
        try:
            server = ExclusiveHTTPServer(("127.0.0.1", candidate), InjectHandler)
        except OSError as e:
            last_error = e
            logger.warning(f"[inject] 端口 {candidate} 已被占用，顺延")
            continue
        injector_port = candidate
        Thread(target=server.serve_forever, daemon=True, name="bridge").start()
        logger.info(f"[inject] 本地 SWF 注入服务: http://127.0.0.1:{injector_port}")

        return candidate
    raise RuntimeError(f"注入服务端口 {port}~{port + 19} 全被占用：{last_error}")


def injector_url(path: str = "/Client.swf") -> str:
    """返回本地注入服务的完整 URL（Flash 的 LoadMovie 目标，mole 同款）。"""
    return f"http://127.0.0.1:{injector_port}{path}"


