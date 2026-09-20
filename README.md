# SNNU-Portal · 校园网自动认证

> 陕西师范大学校园网自动认证工具 · **v2.1**
> Windows / Linux 桌面版：图形界面手动认证 + 记住密码 + 开机静默自启 +
> 断线自动重连 + 防掉线保活
>
> **本项目使用了 AI 辅助创作。**

由原来的 `net.py`（一行 `requests.post` 的手动脚本）改写而来的桌面小工具，
支持 **Windows** 和 **Linux（Debian / Ubuntu）**。

认证接口与原脚本完全一致，仍是陕西师范大学 portal：

```
登录  POST http://202.117.144.205:8602/snnuportal/login
注销  POST http://202.117.144.205:8602/snnuportal/logoff
状态  GET  http://202.117.144.205:8602/snnuportal/userstatus.jsp
字段  sourceurl / account / password / yys / issave
```

---

## 下载即用（推荐）

到 [Releases](https://github.com/Murasame1151/SNNU-Portal/releases) 下载：

| 平台 | 文件 |
| --- | --- |
| Windows | `CampusNetAutoLogin-v2.1.exe` —— 双击即可，不需要装 Python |
| Linux | `校园网自动认证-linux-x86_64` —— 单文件，同样不需要装 Python |
| Linux（含脚本） | `SNNU-Portal-2.1-linux-x86_64.tar.gz` |

第一次打开：填账号 / 密码 / 运营商 → 点“连接” → 勾上“开机静默自启”。
之后每次开机它都在后台默默认证。

* Windows 上平时只占右下角一个小图标。
* Linux 上会写成 systemd 用户服务，运行前先 `sudo apt install python3-tk`
  （界面需要 Tk；程序本体已自带 Python 和 requests）。

> Windows 版未签名，首次运行 SmartScreen 可能提示“未知发布者”，
> 点“更多信息 → 仍要运行”即可。也可以从源码自己打包（见下文）。

---

## 一、Windows：直接打包

```bat
python build.py
```

产物：`dist\CampusNetAutoLogin.exe`（另有一份中文名副本 `dist\校园网自动认证.exe`）。
双击即可运行，**不依赖 Python 环境**，拷到别的电脑也能用。

首次打包需要联网安装 PyInstaller：

```bat
python -m pip install pyinstaller
```

## 二、Linux（Debian / Ubuntu）

Linux 上**不做系统托盘**，开机自启改用 **systemd 用户服务**（不需要 root，
比托盘更符合 Linux 习惯）；其余功能（图形界面、记住密码、防掉线保活、
断线重连）与 Windows 版一致。

### 安装依赖并构建

```bash
sudo apt install python3 python3-tk python3-venv zip
python3 -m venv venv && . venv/bin/activate
pip install pyinstaller requests
./build_linux.sh            # 产物: dist/校园网自动认证
```

### 安装到当前用户

```bash
./install_linux.sh          # 装到 ~/.local/bin，并添加菜单项
./install_linux.sh --uninstall
```

也可以不安装，直接运行：`./dist/校园网自动认证`

### 开机自启（systemd 用户服务）

在界面里勾选「开机静默自启」后，程序会写入
`~/.config/systemd/user/campus-net-portal.service` 并 `systemctl --user enable`。
手动管理：

```bash
systemctl --user status  campus-net-portal.service
systemctl --user restart campus-net-portal.service
journalctl --user -u campus-net-portal.service -f
```

> 想让服务在**没登录桌面时**也能跑（例如纯 SSH 环境），执行一次：
> `sudo loginctl enable-linger $USER`

### Linux 与 Windows 的实现差异

| 能力 | Windows | Linux (Debian) |
| --- | --- | --- |
| 密码保存 | DPAPI（绑定当前用户，换机/换用户都解不开） | 系统 keyring（gnome-keyring/kwallet）；**没有 keyring 时**退化为 `~/.config/CampusNetPortal/secret.bin`（权限 0600 + 混淆存储，**不是真加密**，文档如实说明） |
| 开机自启 | `HKCU\...\Run` 注册表项 | `~/.config/systemd/user/campus-net-portal.service` |
| 系统托盘 | 有（ctypes 直调 Win32） | 无 |
| 流量统计 | `GetIfTable2`（按 IF_HARDWARE 过滤物理网卡） | `/proc/net/dev`（按接口名前缀排除 lo/docker/veth 等） |
| 单实例 | 命名互斥量 | PID 文件 + `flock` |
| 图标 | 多尺寸 ICO | 256px PNG |

> `secret.bin` 在 Linux 上的混淆密钥由「machine-id + 用户名 + 固定盐」派生，
> 换句话说**同一台机器的同一个用户是能解开的**——它的作用是避免密码明文落盘，
> 而不是抗本地攻击者。要真正的加密请确保系统装了 keyring（程序的设置窗口里
> 会显示当前实际使用的是哪一种）。

### 无图形界面（纯命令行自启）

如果你只想要后台认证、完全不要 GUI，可以直接把它交给 systemd：

```bash
systemctl --user start campus-net-portal.service   # 界面里勾选自启后即可用
```

## 三、开发时直接运行

```bash
python main.py            # 正常打开界面
python main.py --silent   # 模拟开机静默启动（后台运行）
```

Windows 上对应 `python main.py` / `python main.py --silent`。

---

## 四、功能说明

### 1. 主界面（手动连接）
* **账号 / 密码 / 运营商**：运营商下拉框对应原脚本的 `yys`
  （移动 `mobile`、联通 `unicom`、电信 `telecom`、校园网不代拨 = 空）。
* **连接**：先问一次 portal 当前状态；已经在线就直接复用，否则先注销旧会话再认证。
* **断开**：调用 `logoff`。
* **设置**：调状态检查周期、空闲阈值等；可一键打开配置目录。

### 2. 记住账号密码
* Windows：密码用 **Windows DPAPI（当前用户作用域）** 加密存到
  `%APPDATA%\CampusNetPortal\secret.bin`，换机换用户都解不开。
* Linux：优先存进系统 keyring；没有 keyring 时退化为 0600 权限的混淆文件。
* 两种平台下配置文件里都不会出现明文密码，取消勾选会立刻删除该文件。


### 3. 开机静默自启
* 勾选后在 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 写入启动项，
  **不需要管理员权限**。
* 启动命令带 `--silent`：开机后只在右下角托盘出现一个小图标，
  **不显示窗口、不占任务栏**，同时后台自动认证。
* 托盘图标：左键单击打开主界面；右键菜单 → 打开主界面 / 立即重新连接 /
  开机自动启动 / 退出。
* 点窗口的 × 只是隐藏窗口，程序继续在后台保持认证；要彻底退出请用托盘右键
  → 退出。

### 4. 防掉线保活（测试功能）
校园网的“长时间无流量自动断开”有两种常见形态，本工具对两种都做了处理：

1. **会话/NAT 空闲超时**：只要一段时间没有任何报文，网关就回收会话。
2. **portal 心跳超时**：服务端要求客户端周期性活跃。

实现方式（`main.py` 的 `NetWorker._run` + `portal.py`）：

* 用 `GetIfTable2`（Windows IP Helper API，**只读、几乎零开销**）读取**真实网卡**
  累计收发字节数，判断**最近是不是真的没有流量**。
  （已按 `InterfaceAndOperStatusFlags` 的 `IF_HARDWARE` 位只取物理网卡，
  并排除 NDIS 轻量筛选器——它们和真实网卡共用同一组计数，否则流量会被重复计数。）
* 只要你在正常上网（下载、看视频、挂着网页），程序**什么都不发**，
  不会产生任何多余流量。
* 只有当本机连续空闲超过阈值（默认 **150 秒**，可在设置里改）时，
  才补发**一次极小的 HTTP GET**（几十字节级的 `generate_204` /
  `connecttest.txt`），既产生收发流量、又刷新 NAT/portal 的活跃计时。
* 同时每 **45 秒**做一次状态检查：直接 GET `userstatus.jsp`，
  看 `当前登录账号` 还在不在。一旦被踢下线立刻自动重新认证；
  重连失败按 5→10→…→60 秒指数退避，避免疯狂重试把 portal 打死。
* 认证前会先问一次 portal“我现在是谁”：**已经在线就不重复登录**，
  不会因为开机自启而白白断网重连一次。

后台开销：空闲时 1 个 Tk 主线程 +（Windows 上多 1 个托盘线程）+ 1 个网络线程
全部阻塞等待，**CPU 占用≈0%**，内存约 20–30 MB；每 45 秒一次小请求，
一天流量不到 1 MB。

> 注意：如果 `userstatus.jsp` 所在的 portal 完全连不上（例如没连校园网），
> 程序**不会**把它当成掉线去疯狂重连，只会保持现状并记录日志。

### 5. 其它细节
* 单实例：重复启动会直接退出，不会出现两个程序互相抢认证。
* 日志：Windows 在 `%APPDATA%\CampusNetPortal\app.log`，
  Linux 在 `~/.config/CampusNetPortal/app.log`，
  记录认证/掉线/保活事件，超过 128 KB 自动截断。

---

## 五、文件结构

| 文件 | 作用 |
| --- | --- |
| `main.py` | 界面 + 网络工作线程（保活/状态检查/重连） + 程序入口 |
| `portal.py` | portal 登录/注销/状态/保活 |
| `cfgtool.py` | 配置读写、密码保存、开机自启、日志（跨平台分发） |
| `trayicon.py` | ctypes 直调 Win32 的系统托盘图标（仅 Windows） |
| `build.py` / `build.spec` | PyInstaller 一键打包（Windows） |
| `build_linux.sh` | PyInstaller 一键打包（Linux） |
| `install_linux.sh` | 安装到 `~/.local`（Linux，含卸载） |
| `iconart.py` | 纯标准库生成 ICO / PNG 图标 |
| `plat/win_impl.py` | Windows 专有：DPAPI、注册表自启、GetIfTable2、命名互斥量 |
| `plat/lin_impl.py` | Linux 专有：keyring/0600、systemd 用户服务、/proc/net/dev、flock |
| `net.ico` | 程序图标（打包时自动生成，多尺寸） |
| `logictest.py` | 离线自检：密码后端 / 配置 / 判定逻辑 / 自启 / 单实例（跨平台） |
| `livetest.py` | 联调自检：跑真实 portal 全流程 |
| `net.py` | v1.0 的原脚本，保留未改动（**账号密码已换成占位符**） |

依赖：仅 `requests`（打包后已内置）+ Python 标准库。托盘图标自己用 ctypes 写，
图标自己按 ICO / PNG 格式拼，所以没有
pystray / pywin32 / Pillow / AppIndicator 这些额外依赖，体积和内存都更小。

### 自检

```bash
python logictest.py                  # 不需要校园网；Windows/Linux 都适用
python livetest.py 你的学号 你的密码    # 需要在校园网内
```

---

## 六、可调参数（设置对话框）

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| 状态检查周期 | 45 秒 | 多久问一次 portal“我还在线吗”，最小 30 |
| 空闲阈值 | 150 秒 | 连续多少秒没流量才补发保活流量 |
| 保活周期 | 300 秒 | 读不到网卡统计时的兜底补流量周期 |

若你的校园网踢线更快（例如 5 分钟），把“空闲阈值”调到 120 秒左右即可；
若想更省流量，就把它调大。

---

## 七、安全说明

* **密码存储**：勾选“记住账号密码”后，Windows 用 **DPAPI（当前用户）** 加密写入
  `secret.bin`，换电脑或换用户都解不开；Linux 优先用系统 keyring，
  没装 keyring 时退化为 0600 权限的混淆文件（**不是真加密**，见上文差异表）。
  两种平台下配置文件里都没有明文，取消勾选会立即删除该文件。
* **隐私**：工具只访问 portal 和内网/公网的几个极小探测地址，不上传任何数据。
* **源码中不含任何凭据**：v1.0 的 `net.py` 原本把学号和密码写死在源码里，
  本仓库里的那一份已换成占位符。请仍然注意：**不要把自己填好凭据的
  `net.py` 提交上来**，`.gitignore` 已忽略 `config.ini` / `secret.bin` / `app.log`。

## 八、免责声明

本工具仅用于方便自己的校园网认证，请遵守学校网络使用规定。
认证接口属于学校资产，若校方调整接口，本工具需相应更新。
作者不对误用或由此产生的任何后果负责。

