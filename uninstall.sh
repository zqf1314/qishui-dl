#!/data/data/com.termux/files/usr/bin/bash
# 汽水音乐下载器 · 彻底卸载
# 用法：bash uninstall.sh        交互确认后卸载
#       bash uninstall.sh -y     不询问，直接卸载
# 清单：服务进程、$PREFIX/bin/qishui、项目目录、/data/local/tmp/qishui_db
set -u

c_g=$'\033[32m'; c_r=$'\033[31m'; c_y=$'\033[33m'; c_d=$'\033[2m'; c_b=$'\033[1m'; c_0=$'\033[0m'
ok()   { printf '%s✓%s %s\n' "$c_g" "$c_0" "$*"; }
warn() { printf '%s!%s %s\n' "$c_y" "$c_0" "$*"; }
err()  { printf '%s✗%s %s\n' "$c_r" "$c_0" "$*"; }
die()  { err "$*"; exit 1; }

PROJ="$(cd "$(dirname "$0")" && pwd)"
PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
DBDIR="/data/local/tmp/qishui_db"

[ -d "$PREFIX/bin" ] || die "没检测到 Termux（$PREFIX/bin 不存在），请在 Termux 里运行"

echo
cat <<EOF
${c_b}将卸载以下内容：${c_0}

  · 服务进程（如有）
  · $PREFIX/bin/qishui
  · 项目目录 $PROJ（含 config.env、日志）
  · $DBDIR（root 侧数据库副本，需要 su）

EOF

FORCE=0
[ "${1:-}" = "-y" ] && FORCE=1
if [ "$FORCE" -ne 1 ]; then
  printf '确认卸载？[Y/n]: '
  read -r ANS || ANS="y"
  case "${ANS:-y}" in
    [Nn]*) die "已取消" ;;
  esac
fi

# ---------- 停服务 ----------
if [ -x "$PREFIX/bin/qishui" ]; then
  "$PREFIX/bin/qishui" stop >/dev/null 2>&1
fi
# 兜底：命令不在时按 pid 文件停
PIDFILE="$PROJ/data/run/server.pid"
if [ -f "$PIDFILE" ]; then
  kill "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null
  rm -f "$PIDFILE"
fi
ok "服务已停止"

# ---------- 移除命令 ----------
rm -f "$PREFIX/bin/qishui"
ok "已移除 $PREFIX/bin/qishui"

# ---------- 清理 root 侧副本 ----------
if su -c "rm -rf '$DBDIR'" 2>/dev/null; then
  ok "已清理 $DBDIR"
else
  warn "没清理 $DBDIR（没有 root 或已不存在），可手动：su -c \"rm -rf $DBDIR\""
fi

# ---------- 删项目目录 ----------
ok "删除项目目录 $PROJ"
# exec 替换掉当前 shell 再删，避免 bash 还在读这个目录里的脚本
exec rm -rf "$PROJ"
