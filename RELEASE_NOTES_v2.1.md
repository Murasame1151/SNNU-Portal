# SNNU-Portal v2.1 · 校园网自动认证（新增 Linux 支持）

在 v2.0（Windows 图形界面版）基础上，**新增 Debian / Ubuntu 支持**，
并修掉了一个无图形界面环境下会崩溃的真实缺陷。

## 下载

| 平台 | 文件 | 说明 |
| --- | --- | --- |
| Windows | `CampusNetAutoLogin-v2.1.exe` | 12 MB 单文件，双击即用，免装 Python |
| Linux | `校园网自动认证-linux-x86_64` | 13 MB 单文件 ELF，免装 Python |
| Linux | `SNNU-Portal-2.1-linux-x86_64.tar.gz` | 上面这个 + 图标 + 安装脚本 + 说明 |
| 源码 | Source code (zip/tar.gz) | 自己构建 |

Linux 首次运行前装一下 Tk（界面需要它，程序本体已自带 Python 和 requests）：

```bash
sudo apt install python3-tk
./校园网自动认证
```

安装到本用户（进开始菜单，可卸载）：

```bash
tar xzf SNNU-Portal-2.1-linux-x86_64.tar.gz
cd release && ./install_linux.sh
```

## Linux 版和 Windows 版有什么不同

功能一致（图形界面、记住密码、防掉线保活、断线重连），差异只在平台实现：

| 能力 | Windows | Linux |
| --- | --- | --- |
| 密码保存 | DPAPI（换机换用户都解不开） | 系统 keyring；**没装 keyring 时**退化为 0600 混淆文件（不是真加密，如实说明） |
| 开机自启 | `HKCU\...\Run` 注册表 | systemd 用户服务，**不需要 root** |
| 系统托盘 | 有 | 无（Linux 上用 systemd 更自然） |
| 流量统计 | `GetIfTable2` | `/proc/net/dev` |
| 单实例 | 命名互斥量 | PID 文件 + `flock` |

## 本次修掉的一个真实缺陷

构建 Linux 二进制后实测发现：**在没有图形界面的环境（纯 SSH、systemd 开机自启）
下启动会直接崩溃**，因为 `tk.Tk()` 抛 `TclError: couldn't connect to display`。

现在改成自动检测：没有 `DISPLAY` / `WAYLAND_DISPLAY` 时转入**无界面后台模式**，
只跑认证与保活，日志照常记录：

```
以无界面模式运行（没有 DISPLAY / WAYLAND_DISPLAY 环境变量）：只做后台认证与保活
认证失败：认证被拒：登录失败（账号或密码不正确，或该账号已在线）
```

顺带修掉图标绘制的一个尺寸问题：三条横杠原本用写死的 64px 坐标，
生成 16px / 256px 图标时图案会错位，已改为按比例绘制。

## 验证情况

Windows 侧：离线自检全过（DPAPI / 注册表自启 / 判定逻辑 / 单实例）。

Linux 侧（Debian 13, Python 3.13.5 + Tk 8.6，WSL2 实测）：

```
RESULT: ALL PASS
```

覆盖：`/proc/net/dev` 解析与虚拟接口过滤（合成数据断言只统计物理网卡）、
`secret.bin` 权限为 0600、systemd 服务内容含 `--silent` 与
`WantedBy=default.target`、关闭后服务文件被删除、`flock` 单实例
（第二次加锁被拒绝）、密码加解密往返。

另外用打包后的二进制实测了：`--version` 输出正常、无 `DISPLAY` 下
`--silent` 稳定运行并真的发起认证、重复启动会打印“已有实例在运行”并退出。

## 已知限制

- Linux 二进制是 **x86_64**，需要 glibc ≥ 2.36（Debian 12+ / Ubuntu 22.04+），
  且运行界面需要系统有 Tk（`python3-tk`）。
- 服务器 / 无桌面环境下程序会自动进入无界面模式；若希望开机即运行，
  勾选一次「开机静默自启」（写 systemd 用户服务），必要时执行
  `sudo loginctl enable-linger $USER` 让服务在未登录时也启动。
- 只有陕西师范大学（SNNU）的 portal 接口，地址写死在 `portal.py`。

**完整说明见 [README.md](README.md)，版本变更见 [CHANGELOG.md](CHANGELOG.md)。**
