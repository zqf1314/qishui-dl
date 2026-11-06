#!/data/data/com.termux/files/usr/bin/bash
# 汽水音乐下载器 · 安装脚本
# 用法：bash install.sh            交互选择版本
#       bash install.sh --mode 1   直接装精简版（无 root）
#       bash install.sh --mode 2   直接装完整版（需要 root）
set -u

c_g=$'\033[32m'; c_r=$'\033[31m'; c_y=$'\033[33m'; c_b=$'\033[1m'; c_d=$'\033[2m'; c_0=$'\033[0m'
ok()   { printf '%s✓%s %s\n' "$c_g" "$c_0" "$*"; }
warn() { printf '%s!%s %s\n' "$c_y" "$c_0" "$*"; }
err()  { printf '%s✗%s %s\n' "$c_r" "$c_0" "$*"; }
die()  { err "$*"; exit 1; }
step() { printf '\n%s▶%s %s\n' "$c_b" "$c_0" "$*"; }

PROJ="$(cd "$(dirname "$0")" && pwd)"

# ---------- 环境 ----------
[ -n "${PREFIX:-}" ] || die "没检测到 Termux 环境变量 PREFIX，请在 Termux 里运行"
[ -d "$PREFIX/bin" ] || die "这不是 Termux（$PREFIX/bin 不存在）"
[ -d "/data/data/com.termux" ] || die "这不是 Termux"

# ---------- 参数 ----------
MODE_ARG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --mode) MODE_ARG="${2:-}"; shift 2 ;;
    --mode=*) MODE_ARG="${1#*=}"; shift ;;
    -h|--help)
      cat <<EOF
用法: bash install.sh [--mode 1|2]

  1  精简版   不需要 root，仅 128k AAC
  2  完整版   需要 root，128k + 无损 FLAC
EOF
      exit 0 ;;
    *) shift ;;
  esac
done

clear 2>/dev/null || true
cat <<EOF
${c_b}汽水音乐 · 链接解析下载器${c_0}
粘贴汽水分享链接 → 解析 → 下载音频

${c_d}安装目录：$PROJ${c_0}

请选择要安装的版本：

  ${c_b}1${c_0}) 精简版    不需要 root
             只支持 128k AAC，纯 HTTP 解析，装完即用

  ${c_b}2${c_0}) 完整版    需要 root
             128k AAC + 无损 FLAC，自动补抓任意歌曲
             需要已 root 的手机，并且装了汽水音乐

EOF

if [ -n "$MODE_ARG" ]; then
  CHOICE="$MODE_ARG"
  printf '已按参数选择：%s\n' "$CHOICE"
else
  CHOICE=""
  while :; do
    printf '请输入 1 或 2 [默认 2]: '
    read -r ANSWER || die "读不到输入，请用 bash install.sh 交互运行"
    ANSWER="${ANSWER:-2}"
    case "$ANSWER" in
      1|2) CHOICE="$ANSWER"; break ;;
      *) err "只能输入 1 或 2" ;;
    esac
  done
fi
case "$CHOICE" in 1|2) ;; *) die "版本只能是 1 或 2" ;; esac

# ---------- 已有安装 ----------
if [ -f "$PROJ/config.env" ]; then
  echo
  warn "检测到已有安装，会保留端口等配置并重装"
  # shellcheck disable=SC1090
  . "$PROJ/config.env"
  [ -x "$PREFIX/bin/qishui" ] && "$PREFIX/bin/qishui" stop >/dev/null 2>&1
fi

# ---------- 依赖 ----------
step "检查运行环境"
if command -v python3 >/dev/null 2>&1; then
  ok "python3 $(python3 -V 2>&1 | awk '{print $2}')"
else
  warn "缺 python3，开始安装"
  pkg install -y python || die "python3 安装失败"
  ok "python3 已安装"
fi

if [ "$CHOICE" = "2" ]; then
  step "检查 root"
  if su -c id 2>/dev/null | grep -q 'uid=0'; then
    ok "root 可用"
  else
    echo
    err "没有检测到 root"
    echo "  完整版需要 root 才能读取汽水 App 的数据库。"
    printf '  改用精简版（仅 128k）继续？[Y/n]: '
    read -r FB || FB="y"
    case "${FB:-y}" in
      [Nn]*) die "已取消安装" ;;
      *) CHOICE=1; MODE_ARG=""; warn "已切换为精简版" ;;
    esac
  fi
fi

if [ "$CHOICE" = "2" ]; then
  step "检查汽水音乐"
  if [ "$(su -c 'pm list packages' 2>/dev/null | grep -c 'com.luna.music')" -gt 0 ]; then
    ok "已安装汽水音乐"
  else
    warn "没检测到汽水音乐，无损功能会不可用（装上后重启服务即可）"
  fi

  step "检查 ffmpeg"
  if command -v ffmpeg >/dev/null 2>&1; then
    ok "ffmpeg 已安装"
  else
    warn "缺 ffmpeg，无损解密要用，大概 45MB"
    printf '  现在安装？[Y/n]: '
    read -r DOFF || DOFF="y"
    case "${DOFF:-y}" in
      [Nn]*) warn "跳过；之后可手动 pkg install ffmpeg" ;;
      *) pkg install -y ffmpeg && ok "ffmpeg 已安装" || warn "ffmpeg 装失败了，无损暂不可用" ;;
    esac
  fi
fi

# ---------- 端口 ----------
step "监听地址"
QISHUI_HOST="${QISHUI_HOST:-127.0.0.1}"
QISHUI_PORT="${QISHUI_PORT:-1314}"

port_open() {
  if netstat -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$QISHUI_PORT\$"; then
    return 0
  fi
  curl -s -o /dev/null -m 1 "http://$QISHUI_HOST:$QISHUI_PORT/" 2>/dev/null
}

if port_open; then
  warn "端口 $QISHUI_PORT 已被占用"
  printf '  换一个端口 [回车用 1316]: '
  read -r ALT || ALT=""
  QISHUI_PORT="${ALT:-1316}"
fi
ok "http://$QISHUI_HOST:$QISHUI_PORT"

# ---------- 配置 ----------
step "写入配置"
mkdir -p "$PROJ/data/run" "$PROJ/logs"
QISHUI_DB_DIR="/data/local/tmp/qishui_db"
cat > "$PROJ/config.env" <<EOF
# 由 install.sh 生成；改端口后执行 qishui restart
QISHUI_MODE=$CHOICE
QISHUI_HOST=$QISHUI_HOST
QISHUI_PORT=$QISHUI_PORT
QISHUI_PKG=com.luna.music
QISHUI_DB_DIR=$QISHUI_DB_DIR
EOF
chmod 600 "$PROJ/config.env"
ok "config.env 已生成（模式 $CHOICE）"

# ---------- 无损数据通道 ----------
if [ "$CHOICE" = "2" ]; then
  step "准备无损数据通道"
  # root 把 App 数据库拷到 /data/local/tmp（root 可写、Termux 可读），
  # 服务只从那里只读。全程没有常驻 root 进程。
  if [ -r /data/local/tmp ] && [ -x /data/local/tmp ]; then
    ok "/data/local/tmp 可读，root 侧会往这里放数据库副本"
  else
    warn "/data/local/tmp 不可读，无损可能取不到数据"
  fi
  if [ "$(su -c 'ls /data_mirror/data_ce/null/0/com.luna.music/databases /data/data/com.luna.music/databases /data/user/0/com.luna.music/databases 2>/dev/null | grep -c "player_.*\.db$"' 2>/dev/null)" -gt 0 ]; then
    ok "汽水音乐数据库能找到"
  else
    warn "没找到汽水音乐的数据库，先打开 App 播一首歌"
  fi
  ok "数据库副本目录：$QISHUI_DB_DIR"
fi

# ---------- 管理命令 ----------
step "安装管理命令 qishui"
sed -e "s|@@PROJ@@|$PROJ|g" "$PROJ/qishui" > "$PREFIX/bin/qishui.tmp" \
  || die "写入 qishui 失败"
chmod 755 "$PREFIX/bin/qishui.tmp"
mv -f "$PREFIX/bin/qishui.tmp" "$PREFIX/bin/qishui"
ok "$PREFIX/bin/qishui"

step "设置权限"
chmod 755 "$PROJ/app"/*.py 2>/dev/null
chmod 644 "$PROJ/app/index.html" 2>/dev/null
chmod 755 "$PROJ/install.sh" "$PROJ/uninstall.sh" 2>/dev/null
ok "完成"

# ---------- 启动 ----------
step "启动服务"
if "$PREFIX/bin/qishui" start; then
  :
else
  warn "自动启动失败，手动执行：qishui start"
fi

# ---------- 完成 ----------
URL="http://$QISHUI_HOST:$QISHUI_PORT/"
echo
printf '%s安装完成%s\n' "$c_g$c_b" "$c_0"
cat <<EOF

  打开网页    $URL
  命令打开    qishui open

  常用命令
    qishui start      启动服务
    qishui stop       停止服务
    qishui restart    重启
    qishui status     运行状态
    qishui logs       看日志
    qishui doctor     环境自检
    qishui help       全部命令

${c_d}服务跟着 Termux 走：Termux 被关掉，服务自动结束。
下次要用，重新打开 Termux，执行 qishui start。${c_0}

EOF
