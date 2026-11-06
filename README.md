# 汽水音乐下载器

粘贴汽水音乐分享链接，解析出音频并下载。跑在 Termux 里，一个本地网页搞定。

```
http://127.0.0.1:1314
```

## 功能

- 分享链接直接粘贴，自动解析曲目、歌手、封面、时长
- 128k AAC 下载：纯 HTTP，不需要 root，不需要登录
- 无损 FLAC：从本机汽水 App 的播放记录取无损档，本地解密
- 本机没记录时，自动让 App 播一遍再补抓
- 服务跟着 Termux 走，Termux 结束服务自动结束

## 安装

需要 Termux（F-Droid 版或 GitHub 版，不要用 Play 商店版）。

```bash
pkg install -y git
git clone https://github.com/zqf1314/qishui-dl.git
cd qishui-dl
bash install.sh
```

运行后会让你选版本：

```
1) 精简版    不需要 root，只支持 128k AAC
2) 完整版    需要 root，128k + 无损 FLAC
请输入 1 或 2 [默认 2]:
```

输入 `1` 或 `2` 回车。装完自动启动，打开 `http://127.0.0.1:1314` 就能用。

非交互安装：

```bash
bash install.sh --mode 1
bash install.sh --mode 2
```

### 完整版还需要

- 手机已 root（Magisk / KernelSU / APatch 都行）
- 已安装汽水音乐（`com.luna.music`）
- ffmpeg：安装脚本会问要不要装，也可以事后 `pkg install -y ffmpeg`

## 常用命令

```bash
qishui start       # 启动服务（后台）
qishui stop        # 停止服务
qishui restart     # 重启
qishui run         # 前台运行，看实时输出，Ctrl+C 结束
qishui status      # 运行状态
qishui logs        # 看服务日志
qishui open        # 浏览器打开
qishui doctor      # 环境自检
qishui update      # git pull 后重启
qishui uninstall   # 停止并移除命令
```

## 服务生命周期

服务不是常驻守护进程，它绑定 Termux：

- Termux 在，服务在
- Termux 被关掉（包括从最近任务划掉），服务自动结束
- 下次要用，重新打开 Termux，执行 `qishui start`

实现方式：启动服务时刻意不用 `nohup`、不用 `setsid`，进程留在 Termux 的会话里。
服务内部还有一层守护：顺着父进程链找到 Termux 主进程，那个进程一旦消失，服务立刻退出。

## 无损是怎么来的

汽水 App 播歌时会把各档音质的播放信息写进自己的数据库：

```
/data/data/com.luna.music/databases/player_<uid>.db
```

其中 `player_info.videoModelString` 里有 `lossless` 档的 `main_url`、`spade_a`、`kid`。
`main_url` 指向 CENC 加密文件，`spade_a` 解出的 32 位 hex 就是解密密钥，
拿到这两个用 ffmpeg 解密成普通 FLAC。

这些数据在 App 私有目录里，Termux 读不到，所以完整版需要 root。但**不是**在后台养一个 root 进程：

1. 需要时临时执行一条 `su -c` 命令，把数据库拷到 `/data/local/tmp/qishui_db`
   （root 可写、Termux 可读，权限 644）
2. 命令执行完立刻退出，手机上不会留下任何常驻 root 进程
3. 服务只从那个副本目录只读，不碰 App 的原始文件

同步是按需触发的：打开网页解析、点下载无损时各同步一次，两次之间有时间节流，
不会频繁打扰。

## 目录

```
qishui-dl/
  install.sh        安装脚本
  qishui            管理命令
  config.env        安装后生成（模式、地址、端口）
  app/
    server.py       本地 HTTP 服务
    qishui.py       分享链接解析
    lossless.py     从数据库副本取无损档
    trackvid.py     track_id → 实际播放 vid
    spade.py        解密密钥还原
    index.html      网页界面
  logs/             日志
  data/run/         运行期 pid
```

运行时数据（数据库副本）在 `/data/local/tmp/qishui_db`，不在项目目录里。

## 限制

- 无损只对“本机 App 播过、且音质标签为无损”的歌有效。没播过的会自动补抓，但受版权、会员、地区限制影响。
- 精简版只有 128k，换设备、换网络都能用。
- 128k 直链有时效，服务端做代理下载，点下载时实时拉取。

## 卸载

```bash
qishui uninstall
rm -rf ~/qishui-dl
```

## License

MIT
