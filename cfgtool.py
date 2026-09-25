# -*- coding: utf-8 -*-
"""配置读写 + 密码保存 + 开机自启（跨平台，Windows / Linux 都可用）。

平台相关的部分都交给 plat/ 下的实现模块：
    Windows -> plat/win_impl.py（DPAPI + 注册表 + GetIfTable2）
    Linux   -> plat/lin_impl.py（keyring/0600 文件 + systemd 用户服务 + /proc/net/dev）

配置目录:
    Windows  %APPDATA%\\CampusNetPortal
    Linux    ~/.config/CampusNetPortal（遵循 XDG_CONFIG_HOME）
里面只放三样东西：
    config.ini    明文配置（不含密码）
    secret.bin    密码（Windows 为 DPAPI 密文；Linux 为 keyring 或 0600 文件）
    app.log       运行日志
"""
from __future__ import annotations

import base64
import configparser
import os
import sys
import time

APP_NAME = "CampusNetPortal"

DEFAULTS = {
    "account": "",
    "carrier": "mobile",          # mobile / unicom / telecom / ""(校园网默认)
    "remember": "0",
    "autostart": "0",
    "silent_start": "1",
    "keepalive": "1",
    "idle_sec": "150",            # 无流量多少秒后补一次流量
    "traffic_sec": "300",         # 补流量的周期
    "check_sec": "45",            # 探活周期（最小 5）
    "reconnect": "1",
    "daily_reconnect": "",        # 每天定时重连，格式 HH:MM；留空不启用
    "wake_reconnect": "1",        # 睡眠唤醒后立即重连
    "want_online": "1",           # 用户是否希望在线；手动断开后置 0，重启也不再自动连
}


# --------------------------------------------------------------------------- #
# 路径
# --------------------------------------------------------------------------- #
def _default_dir() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, APP_NAME)
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, APP_NAME)


def data_dir() -> str:
    """配置目录。

    Windows 默认 %APPDATA%\\CampusNetPortal；
    Linux   默认 ~/.config/CampusNetPortal（目录权限 0700）。
    设置环境变量 CAMPUSNET_DATA_DIR 可改写（自检脚本用它做隔离，避免
    测试数据混进真实配置；打包后的程序不会用到）。
    """
    override = os.environ.get("CAMPUSNET_DATA_DIR")
    if override:
        d = os.path.abspath(override)
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass
        return d
    d = _default_dir()
    try:
        os.makedirs(d, exist_ok=True)
        if sys.platform != "win32":
            os.chmod(d, 0o700)          # 只有本人能进这个目录
    except OSError:
        d = os.path.dirname(os.path.abspath(sys.argv[0]))
    return d


def cfg_path() -> str:
    return os.path.join(data_dir(), "config.ini")


def log_path() -> str:
    return os.path.join(data_dir(), "app.log")


def log(msg: str) -> None:
    """极简日志：单文件，超过 128KB 自动截断，避免长期占用磁盘。"""
    try:
        p = log_path()
        if os.path.exists(p) and os.path.getsize(p) > 128 * 1024:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                tail = f.read()[-32768:]
            with open(p, "w", encoding="utf-8") as f:
                f.write(tail)
        line = time.strftime("[%Y-%m-%d %H:%M:%S] ") + msg + "\n"
        with open(p, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# 平台相关实现的分发
#
# 密码状态检查不需要特别处理：Windows 交给 DPAPI，Linux 交给 keyring 或
# 0600 混淆文件，两边都由各自的 impl 模块负责。
# --------------------------------------------------------------------------- #
if sys.platform == "win32":
    import plat.win_impl as _impl
    IS_WINDOWS = True
    _impl_name = "win_impl"
else:
    import plat.lin_impl as _impl
    IS_WINDOWS = False
    _impl_name = "lin_impl"

# 兼容旧名字：win_impl 里的常量
RUN_KEY = getattr(_impl, "RUN_KEY", "")
RUN_NAME = getattr(_impl, "RUN_NAME", "campus-net-portal")


def _secret_path() -> str:
    return os.path.join(data_dir(), "secret.bin")


def save_password(pwd: str) -> None:
    data = _impl.protect(pwd)
    if IS_WINDOWS:
        # Windows 的 DPAPI 密文用 base64 存，避免二进制脏数据
        data = base64.b64encode(data)
    with open(_secret_path(), "wb") as f:
        f.write(data)
    if not IS_WINDOWS:
        try:
            os.chmod(_secret_path(), 0o600)          # 只有本人可读
        except OSError:
            pass


def load_password() -> str:
    try:
        with open(_secret_path(), "rb") as f:
            data = f.read()
    except OSError:
        return ""
    try:
        if IS_WINDOWS:
            data = base64.b64decode(data)
        return _impl.unprotect(data)
    except Exception:
        return ""


def clear_password() -> None:
    try:
        os.remove(_secret_path())
    except OSError:
        pass


def secret_backend_name() -> str:
    """给设置界面显示：密码到底存在哪、怎么保护的。"""
    try:
        return _impl.secret_backend_name()
    except Exception:
        return "未知"


def autostart_backend_name() -> str:
    try:
        return _impl.autostart_backend_name()
    except Exception:
        return "未知"


def single_instance_lock() -> bool:
    """单实例保护。Windows 用命名互斥量，Linux 用 PID 文件 flock。"""
    try:
        if IS_WINDOWS:
            return _impl.single_instance_lock(
                "Global\\CampusNetPortal_SingleInstance")
        return _impl.single_instance_lock(os.path.join(data_dir(), "app.lock"))
    except Exception:
        return True


def open_in_file_manager(path: str) -> bool:
    try:
        return _impl.open_in_file_manager(path)
    except Exception:
        return False


def headless_reason():
    """判断是不是没有图形界面的环境（纯 SSH / systemd 开机自启时）。

    返回 None 表示有图形界面；返回字符串表示原因（用于写日志）。
    Linux 下没有 DISPLAY 也没有 WAYLAND_DISPLAY 就没法建 Tk 窗口；
    Windows 上桌面总是可用的。
    """
    if IS_WINDOWS:
        return None
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return None
    return "没有 DISPLAY / WAYLAND_DISPLAY 环境变量"


# --------------------------------------------------------------------------- #
# config.ini
# --------------------------------------------------------------------------- #
def load() -> dict:
    cfg = dict(DEFAULTS)
    p = cfg_path()
    if os.path.exists(p):
        cp = configparser.ConfigParser()
        try:
            cp.read(p, encoding="utf-8")
            if cp.has_section("app"):
                for k in DEFAULTS:
                    v = cp.get("app", k, fallback=None)
                    if v is not None:
                        cfg[k] = v
        except Exception as e:
            log("读取配置失败: %r" % (e,))
    cfg["password"] = load_password() if cfg.get("remember") == "1" else ""
    return cfg


def save(cfg: dict) -> None:
    cp = configparser.ConfigParser()
    cp.add_section("app")
    for k, v in DEFAULTS.items():
        cp.set("app", k, str(cfg.get(k, v)))
    tmp = cfg_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        cp.write(f)
    os.replace(tmp, cfg_path())


def as_bool(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


# --------------------------------------------------------------------------- #
# 开机自启（Windows: HKCU 注册表；Linux: systemd 用户服务）
# --------------------------------------------------------------------------- #
def exe_command(silent: bool) -> str:
    """拼出开机要执行的命令（含 --silent）。

    Windows 用双引号包路径（反斜杠路径必须加引号）。
    Linux 下用 shlex.quote，避免路径里有空格/特殊字符时被拆开。
    """
    if getattr(sys, "frozen", False):
        exe = sys.executable
        args = " --silent" if silent else ""
        if IS_WINDOWS:
            return '"%s"%s' % (exe, args)
        import shlex
        return shlex.quote(exe) + args
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
    if IS_WINDOWS:
        return '"%s" "%s"%s' % (sys.executable, script,
                                " --silent" if silent else "")
    import shlex
    return "%s %s%s" % (shlex.quote(sys.executable), shlex.quote(script),
                        " --silent" if silent else "")


def set_autostart(enable: bool, silent: bool = True) -> bool:
    try:
        return _impl.set_autostart(enable, silent, exe_command(silent))
    except Exception as e:
        log("设置自启失败: %r" % (e,))
        return False


def get_autostart() -> bool:
    try:
        return _impl.get_autostart()
    except Exception:
        return False
