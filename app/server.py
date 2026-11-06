#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""汽水音乐分享链接解析下载 —— 本地服务

用法:
  python3 server.py [--host 127.0.0.1] [--port 1314]
  也可用环境变量 QISHUI_HOST / QISHUI_PORT

接口：
  /api/parse   POST {url}          → 元信息 + 128k 直链（纯 HTTP，跨设备可用）
  /api/audio   GET  ?url=&name=    → 代理下载音频
  /api/flac    GET  ?vid=&name=    → 本机无损：从 App 落盘 player_info 取 lossless，
                                     下载 CENC 文件并用 spade 解出密钥后 ffmpeg 解密输出 FLAC
"""
import json, os, re, shutil, subprocess, sys, tempfile, threading, time, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Termux 里 Python 默认找不到证书链，解析分享页会 CERTIFICATE_VERIFY_FAILED
_CERT = "/data/data/com.termux/files/usr/etc/tls/cert.pem"
if os.path.exists(_CERT):
    os.environ.setdefault("SSL_CERT_FILE", _CERT)
    os.environ.setdefault("SSL_CERT_DIR", os.path.dirname(_CERT))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qishui import parse
import lossless
import trackvid

HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(HERE)

# ── 无损数据通道 ────────────────────────────────────────────────
# Termux 身份读不到汽水 App 的私有目录，也不该长期养一个 root 进程。
# 做法：需要时临时 `su -c` 跑一条命令，把 App 数据库拷到 /data/local/tmp
# （root 可写、Termux 用户可读），服务只从那里只读。命令跑完即退，
# 手机上不会留任何常驻 root 进程。
DB_DIR = os.environ.get("LUNA_DB_DIR") or "/data/local/tmp/qishui_db"
APP_DB_CANDIDATES = (
    "/data_mirror/data_ce/null/0/com.luna.music/databases",
    "/data/data/com.luna.music/databases",
    "/data/user/0/com.luna.music/databases",
)
AUTO_WAIT = 75
UA_DL = ("Mozilla/5.0 (Linux; Android 14; K) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36")
INDEX = os.path.join(HERE, "index.html")

_sync_lock = threading.Lock()
_sync_last = 0.0


def safe_name(s):
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", s).strip()
    return s[:120] or "audio"


def _su(cmd, timeout=60):
    """临时起一个 root 命令，跑完就退。不是常驻进程。"""
    try:
        r = subprocess.run(["su", "-c", cmd], timeout=timeout,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return r.returncode == 0
    except Exception:
        return False


def _sync_db(force=False, throttle=2.0, su_timeout=15):
    """把汽水 App 的数据库拷一份到 /data/local/tmp，供本服务只读"""
    global _sync_last
    if not force and time.time() - _sync_last < throttle:
        return os.path.isdir(DB_DIR)
    with _sync_lock:
        if not force and time.time() - _sync_last < throttle:
            return os.path.isdir(DB_DIR)
        cands = " ".join('"%s"' % d for d in APP_DB_CANDIDATES)
        sh = (
            "DEST='%s'; DB=''; "
            "for d in %s; do "
            "if [ -d \"$d\" ] && ls \"$d\"/player_*.db >/dev/null 2>&1; "
            "then DB=\"$d\"; break; fi; done; "
            "[ -z \"$DB\" ] && exit 3; "
            "mkdir -p \"$DEST\" 2>/dev/null || exit 4; "
            "for f in \"$DB\"/player_*.db \"$DB\"/player_*.db-wal \"$DB\"/player_*.db-shm "
            "\"$DB\"/recent_played_*.db \"$DB\"/recent_played_*.db-wal "
            "\"$DB\"/recent_played_*.db-shm; do "
            "[ -f \"$f\" ] || continue; b=${f##*/}; "
            "cp -f \"$f\" \"$DEST/.$b.tmp\" 2>/dev/null || continue; "
            "mv -f \"$DEST/.$b.tmp\" \"$DEST/$b\" 2>/dev/null; done; "
            "chmod 755 \"$DEST\" 2>/dev/null; "
            "chmod 644 \"$DEST\"/* 2>/dev/null; exit 0"
        ) % (DB_DIR, cands)
        ok = _su(sh, timeout=su_timeout)
        _sync_last = time.time()
        return ok


def _trigger_play(track_id):
    """临时 su 一次：深链让 App 播这首歌，让 player_info 落库，然后退出"""
    if not track_id:
        return False
    tid = re.sub(r"[^0-9]", "", str(track_id))
    if not tid:
        return False
    return _su(
        "am start -a android.intent.action.VIEW "
        "-d 'luna://luna.com/playing?track_id=%s' >/dev/null 2>&1; "
        "sleep 2; dumpsys media_session 2>/dev/null | grep -q 'state=PLAYING' "
        "|| input keyevent 126" % tid,
        timeout=20,
    )


def _best_lossless(vid, track_id):
    """先按分享页的 vid 找；找不到就按 track_id 反查 App 实际播放的 vid"""
    got = lossless.lookup(vid, "lossless", strict=True)
    if got:
        got["vid"] = vid
        return got
    if track_id:
        for v in trackvid.vids_for(track_id):
            if v == vid:
                continue
            g = lossless.lookup(v, "lossless", strict=True)
            if g:
                g["vid"] = v
                return g
    return None


def _autofetch(vid, track_id, timeout=AUTO_WAIT):
    """本机没记录时，让 App 播一遍，等 player_info 落库后再取无损

    timeout 是整个补抓阶段的总预算（含 su 调用），不是单纯轮询时长。
    """
    deadline = time.time() + timeout
    got = _best_lossless(vid, track_id)
    if got:
        return got
    if not _trigger_play(track_id):
        return None
    while time.time() < deadline:
        time.sleep(2.0)
        _sync_db(force=True, su_timeout=10)
        got = _best_lossless(vid, track_id)
        if got:
            return got
    return _best_lossless(vid, track_id)


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % a))

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(b)

    def _file(self, path, ctype, filename, cleanup=False):
        size = os.path.getsize(path)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition",
                         "attachment; filename*=UTF-8''%s" % urllib.parse.quote(filename))
        self.end_headers()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(262144)
                if not chunk:
                    break
                self.wfile.write(chunk)
        if cleanup:
            try:
                os.remove(path)
            except Exception:
                pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            try:
                with open(INDEX, "rb") as f:
                    b = f.read()
            except FileNotFoundError:
                return self._json({"error": "index.html missing"}, 500)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return

        if u.path == "/api/audio":
            url = (q.get("url") or [""])[0]
            name = safe_name((q.get("name") or ["audio"])[0])
            if not url.startswith("http"):
                return self._json({"error": "bad url"}, 400)
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": UA_DL, "Referer": "https://music.douyin.com/"})
                r = urllib.request.urlopen(req, timeout=30)
            except Exception as e:
                return self._json({"error": "fetch failed: %s" % e}, 502)
            self.send_response(200)
            self.send_header("Content-Type", "audio/mp4")
            total = r.headers.get("Content-Length")
            if total:
                self.send_header("Content-Length", total)
            self.send_header("Content-Disposition",
                             "attachment; filename*=UTF-8''%s.m4a" % urllib.parse.quote(name))
            self.end_headers()
            try:
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            except Exception:
                pass
            return

        if u.path == "/api/flac":
            vid = (q.get("vid") or [""])[0]
            tid = (q.get("track_id") or [""])[0]
            name = safe_name((q.get("name") or ["audio"])[0])
            auto = (q.get("auto") or [""])[0] in ("1", "true", "yes")
            _sync_db(su_timeout=10)
            got = _best_lossless(vid, tid)
            if not got and auto and tid:
                got = _autofetch(vid, tid)
            if not got:
                any_q = lossless.lookup(vid, None)
                if any_q:
                    return self._json({
                        "error": "这首歌在本机没有无损档（App 里音质标签显示“无损”才有），当前只有 %s" % any_q["quality"],
                        "vid": vid}, 404)
                return self._json({
                    "error": "本机补抓没拿到数据：App 没能播放这首歌，或该曲无版权/需登录",
                    "vid": vid}, 404)
            tmpdir = tempfile.mkdtemp(prefix="luna_")
            enc = os.path.join(tmpdir, "in.mdl")
            out = os.path.join(tmpdir, "out.flac")
            try:
                req = urllib.request.Request(got["url"], headers={"User-Agent": UA_DL})
                with urllib.request.urlopen(req, timeout=120) as r, open(enc, "wb") as f:
                    shutil.copyfileobj(r, f, 262144)
                cmd = ["ffmpeg", "-y", "-v", "error"]
                if got.get("key"):
                    cmd += ["-decryption_key", got["key"]]
                cmd += ["-i", enc, "-c", "copy", out]
                subprocess.run(cmd, check=True, timeout=600,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                if not os.path.exists(out) or os.path.getsize(out) == 0:
                    raise RuntimeError("解密失败")
            except Exception as e:
                shutil.rmtree(tmpdir, ignore_errors=True)
                return self._json({"error": "无损下载失败: %s" % e}, 502)
            self._file(out, "audio/flac", name + ".flac", cleanup=False)
            shutil.rmtree(tmpdir, ignore_errors=True)
            return

        self._json({"error": "not found"}, 404)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path != "/api/parse":
            return self._json({"error": "not found"}, 404)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(min(n, 65536)).decode("utf-8", "replace")
            body = json.loads(raw or "{}")
            url = (body.get("url") or "").strip()
            if not url:
                return self._json({"error": "缺少链接"}, 400)
            info = parse(url)
            if not info.get("audio_url"):
                return self._json({"error": "解析不到音频地址"}, 502)
            fn = "%s - %s" % (info["title"], info["artist"]) if info.get("artist") else info["title"]
            info["filename"] = safe_name(fn)
            info["download"] = "/api/audio?url=%s&name=%s" % (
                urllib.parse.quote(info["audio_url"], safe=""), urllib.parse.quote(info["filename"]))
            _sync_db()
            hi = _best_lossless(info.get("vid"), info.get("track_id"))
            info["lossless"] = {
                "available": bool(hi),
                "quality": (hi or {}).get("quality"),
                "size": (hi or {}).get("size"),
                "codec": (hi or {}).get("codec"),
                "download": "/api/flac?vid=%s&track_id=%s&auto=1&name=%s" % (
                    urllib.parse.quote(info.get("vid") or "", safe=""),
                    urllib.parse.quote(info.get("track_id") or "", safe=""),
                    urllib.parse.quote(info["filename"])),
            }
            return self._json(info)
        except Exception as e:
            return self._json({"error": str(e)}, 500)


def _ppid_of(pid):
    try:
        with open("/proc/%d/status" % pid) as f:
            for line in f:
                if line.startswith("PPid:"):
                    return int(line.split()[1])
    except Exception:
        pass
    return None


def _cmd0(pid):
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            return f.read(64).split(b"\0")[0]
    except Exception:
        return b""


def _find_termux_pid():
    """从父链往上找 Termux 主进程（cmdline 首项就是 com.termux）

    Termux 里普通用户看不到 /proc 下别的进程，所以只能顺着自己的父链走。
    """
    pid = os.environ.get("QISHUI_TERMUX_PID", "")
    if pid.isdigit():
        return int(pid)
    p = os.getppid()
    for _ in range(16):
        if p is None or p <= 1:
            break
        if _cmd0(p) == b"com.termux":
            return p
        p = _ppid_of(p)
    return None


def _watch_termux(anchor):
    """Termux 主进程没了（被划掉/被杀），服务立刻结束"""
    while True:
        time.sleep(3.0)
        if _cmd0(anchor) != b"com.termux":
            sys.stderr.write("Termux 已退出，服务随之结束\n")
            sys.stderr.flush()
            os._exit(0)


def _watch_orphan():
    """备用：父进程被 1 收养，说明 Termux 那边的会话已经没了"""
    me = os.getpid()
    while True:
        time.sleep(3.0)
        if _ppid_of(me) == 1:
            sys.stderr.write("Termux 已退出，服务随之结束\n")
            sys.stderr.flush()
            os._exit(0)


def main():
    host = os.environ.get("QISHUI_HOST", "127.0.0.1")
    port = int(os.environ.get("QISHUI_PORT", "1314"))
    exit_with_termux = os.environ.get("QISHUI_EXIT_WITH_TERMUX") == "1"
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--host", "-H") and i + 1 < len(args):
            host = args[i + 1]; i += 2
        elif a in ("--port", "-p") and i + 1 < len(args):
            port = int(args[i + 1]); i += 2
        elif a == "--exit-with-termux":
            exit_with_termux = True; i += 1
        elif a.isdigit():
            port = int(a); i += 1
        else:
            i += 1
    if exit_with_termux:
        anchor = _find_termux_pid()
        if anchor:
            sys.stderr.write("Termux 锚点 pid=%d\n" % anchor)
            sys.stderr.flush()
            threading.Thread(target=_watch_termux, args=(anchor,), daemon=True).start()
        else:
            # 找不到锚点就退而求其次：父进程变成 1 说明 Termux 的 shell 没了
            sys.stderr.write("没找到 Termux 主进程，用父进程守护\n")
            sys.stderr.flush()
            threading.Thread(target=_watch_orphan, daemon=True).start()

    # 启动时先同步一次汽水数据库（一次性 su，跑完即退）
    threading.Thread(target=lambda: _sync_db(force=True), daemon=True).start()

    srv = ThreadingHTTPServer((host, port), H)
    srv.daemon_threads = True
    sys.stderr.write("listening on %s:%d\n" % (host, port))
    sys.stderr.flush()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
