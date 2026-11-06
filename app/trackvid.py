#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""track_id → 实际播放 vid 的映射

分享页 SSR 给的 vid 有时不是播放器真正用的 vid（同一首歌会有多个 vid），
但 App 播放后会把它写进 recent_played 的 cached_playable，所以补抓后
要按 track_id 反查真实 vid，再去 player_info 里找无损档。
"""
import glob, json, os, sqlite3, time

DB_DIR = os.environ.get("LUNA_DB_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "db")


def _db_path():
    best, best_mtime = None, 0
    for p in glob.glob(os.path.join(DB_DIR, "recent_played_*.db")):
        if p.endswith(("-wal", "-shm")):
            continue
        try:
            m = os.path.getmtime(p)
        except OSError:
            continue
        if m > best_mtime:
            best, best_mtime = p, m
    return best


def _collect_vids(o, out):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == "vid" and isinstance(v, str) and v:
                out.add(v)
            _collect_vids(v, out)
    elif isinstance(o, list):
        for v in o:
            _collect_vids(v, out)


def vids_for(track_id, tries=3):
    """返回该 track_id 关联的所有 vid（可能为空集合）"""
    tid = str(track_id or "").strip()
    if not tid:
        return set()
    db = _db_path()
    if not db:
        return set()
    row = None
    for _ in range(tries):
        con = None
        try:
            con = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=5.0)
            con.execute("PRAGMA busy_timeout=4000")
            row = con.execute(
                "SELECT playableJson FROM cached_playable WHERE id=? LIMIT 1", (tid,)
            ).fetchone()
            con.close()
            con = None
            break
        except Exception:
            time.sleep(0.3)
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass
    if not row or not row[0]:
        return set()
    try:
        out = set()
        _collect_vids(json.loads(row[0]), out)
        return out
    except Exception:
        return set()


if __name__ == "__main__":
    import sys
    print(sorted(vids_for(sys.argv[1])))
