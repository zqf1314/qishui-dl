#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从汽水 App 落盘的 player_info 数据库里取出无损档（main_url + spade 密钥）

App 使用 WAL 模式：新写入先落在 -wal，所以必须用 mode=ro 打开（不能 immutable，
否则读不到 WAL），并保证同目录 -shm 可写。
"""
import glob, json, os, sqlite3, time

from spade import spade_key

# 默认读项目内 data/db（由 root 侧 sync 脚本同步过来）
DB_DIR = os.environ.get("LUNA_DB_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "db")

# 档位优先级（从高到低）
ORDER = ["lossless", "hi_res", "spatial", "highest", "higher", "medium"]


def _db_path():
    best, best_mtime = None, 0
    for p in glob.glob(os.path.join(DB_DIR, "player_*.db")):
        if p.endswith(("-wal", "-shm")):
            continue
        try:
            m = os.path.getmtime(p)
        except OSError:
            continue
        if m > best_mtime:
            best, best_mtime = p, m
    return best


def _read_row(db, vid, tries=3):
    last = None
    for _ in range(tries):
        con = None
        try:
            con = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=5.0)
            con.execute("PRAGMA busy_timeout=4000")
            row = con.execute(
                "SELECT videoModelString FROM player_info WHERE mediaId=? LIMIT 1", (vid,)
            ).fetchone()
            con.close()
            con = None
            return row
        except Exception as e:      # 同步替换文件时的瞬时错误，重试一次
            last = e
            time.sleep(0.35)
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass
    if last:
        raise last
    return None


def lookup(vid, quality="lossless", strict=False):
    """返回 {quality,url,key,size,codec,encrypted} 或 None

    strict=True 时只接受指定档位（用于无损下载，避免把 aac 当成 flac 输出）。
    """
    if not vid:
        return None
    db = _db_path()
    if not db:
        return None
    try:
        row = _read_row(db, vid)
    except Exception:
        return None
    if not row or not row[0]:
        return None
    try:
        vm = json.loads(row[0])
    except Exception:
        return None
    root = vm.get("data") if isinstance(vm.get("data"), dict) else vm
    items = root.get("video_list") or []
    by_q = {}
    for it in items:
        m = it.get("video_meta") or {}
        q = m.get("quality")
        if q and q not in by_q:
            by_q[q] = (m, it)
    if quality and strict:
        want = [quality]
    else:
        want = [quality] if quality else []
        want += [q for q in ORDER if q not in want]
    for q in want:
        if q not in by_q:
            continue
        m, it = by_q[q]
        url = it.get("main_url")
        if not url:
            continue
        ei = it.get("encrypt_info") or {}
        key = None
        if ei.get("spade_a"):
            try:
                key = spade_key(ei["spade_a"])
            except Exception:
                key = None
        return {
            "quality": q,
            "url": url,
            "key": key,
            "size": m.get("size"),
            "codec": m.get("codec_type"),
            "encrypted": bool(ei.get("encrypt")),
        }
    return None


def available(vid):
    got = lookup(vid, "lossless", strict=True) or lookup(vid, None)
    if not got:
        return None
    return {"quality": got["quality"], "size": got["size"], "codec": got["codec"]}


def has_lossless(vid):
    got = lookup(vid, "lossless", strict=True)
    return got is not None


if __name__ == "__main__":
    import sys
    print(json.dumps(lookup(sys.argv[1], strict=True), ensure_ascii=False)[:400])
