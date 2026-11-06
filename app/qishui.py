#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""汽水音乐分享链接解析（纯 HTTP，无签名/无设备依赖）"""
import json, re, urllib.parse, urllib.request

UA_M = ("Mozilla/5.0 (Linux; Android 14; K) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36")

def _get(url, timeout=20, headers=None):
    h = {"User-Agent": UA_M, "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.geturl(), r.read(), dict(r.headers)

TRACK_IN_URL = [
    re.compile(r"[?&]track_id=(\d+)"),
    re.compile(r"/qishui/song/(\d+)"),
    re.compile(r"[?&]id=(\d+)"),
]

def resolve_track_id(share_url):
    share_url = share_url.strip()
    if not share_url.startswith("http"):
        m = re.search(r"https?://[^\s，。、）)]+", share_url)
        if not m:
            raise ValueError("没有识别到链接")
        share_url = m.group(0)
    for p in TRACK_IN_URL:
        m = p.search(share_url)
        if m:
            return m.group(1), share_url
    final, _, _ = _get(share_url, timeout=20)
    for p in TRACK_IN_URL:
        m = p.search(final)
        if m:
            return m.group(1), final
    raise ValueError("分享链接里没有 track_id")

def _router_data(html):
    for key in ("_ROUTER_DATA = ", "_ROUTER_DATA="):
        i = html.find(key)
        if i >= 0:
            try:
                obj, _ = json.JSONDecoder().raw_decode(html[i + len(key):])
                return obj
            except Exception:
                return None
    return None

def track_info(track_id):
    url = "https://music.douyin.com/qishui/share/track?track_id=%s" % track_id
    final, body, _ = _get(url, timeout=25)
    html = body.decode("utf-8", "replace")
    data = _router_data(html)
    if not data:
        raise ValueError("分享页没有 SSR 数据")
    tp = (data.get("loaderData") or {}).get("track_page") or {}
    al = tp.get("audioWithLyricsOption") or {}
    if not al:
        raise ValueError("分享页没有音频数据")
    ti = al.get("trackInfo") or {}
    album = ti.get("album") or {}
    artists = ti.get("artists") or []
    cover = al.get("coverURL") or ""
    if not cover:
        urls = (album.get("url_cover") or {}).get("urls") or []
        uri = (album.get("url_cover") or {}).get("uri") or ""
        if urls and uri:
            cover = urls[0] + uri + "~c5_500x500.jpg"
    bitrate = 0
    m = re.search(r"[?&]br=(\d+)", al.get("url") or "")
    if m:
        bitrate = int(m.group(1))
    return {
        "track_id": str(al.get("track_id") or track_id),
        "vid": al.get("vid") or "",
        "title": al.get("trackName") or ti.get("name") or "",
        "artist": al.get("artistName") or ", ".join(a.get("name", "") for a in artists),
        "album": album.get("name") or "",
        "duration": al.get("duration") or 0,
        "cover": cover,
        "audio_url": al.get("url") or "",
        "encrypted": bool(al.get("encrypt")),
        "bitrate": bitrate,
        "quality": "128k AAC",
    }

def parse(share_url):
    tid, final = resolve_track_id(share_url)
    info = track_info(tid)
    info["source_url"] = final
    return info

if __name__ == "__main__":
    import sys
    print(json.dumps(parse(sys.argv[1]), ensure_ascii=False, indent=1))
