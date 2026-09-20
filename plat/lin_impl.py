# -*- coding: utf-8 -*-
"""Linux（Debian）实现：密码保存、systemd 开机自启、网卡流量统计。

只引用标准库，桌面托盘不做（Linux 上用 systemd 用户服务更自然）。
"""
from __future__ import annotations

import base64
import getpass
import hashlib
import os
import shutil
import subprocess

IS_WINDOWS = False

# --------------------------------------------------------------------------- #
# 密码保存
#
# 诚实说明：Linux 没有 DPAPI 这种“绑定当前用户”的内核级加密。这里优先级从高到低：
#   1. 系统 keyring（gnome-keyring / kwallet 等，由 python3-keyring 提供）
#   2. 本机文件，权限 0600 + 用 机器/用户/盐 派生密钥做异或混淆
# 第 2 种**不是真正的加密**（密钥就在同一台机器上），只是为了不让明文躺在磁盘上，
# 并且用 0600 + 目录 0700 保证只有本人可读。文档里也如实写明。
# --------------------------------------------------------------------------- #
_SALT = b"SNNU-Portal-v2"


def _key(salt: bytes) -> bytes:
    """由 机器标识 + 用户名 + 固定盐 派生一个流密钥。"""
    parts = [salt, getpass.getuser().encode("utf-8", "replace")]
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(path, "rb") as f:
                parts.append(f.read().strip())
            break
        except OSError:
            continue
    seed = hashlib.sha256(b"|".join(parts)).digest()
    out = bytearray()
    block = seed
    while len(out) < 4096:
        block = hashlib.sha256(block).digest()
        out += block
    return bytes(out)


def _xor(data: bytes, salt: bytes) -> bytes:
    key = _key(salt)
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def _keyring():
    """返回可用的 keyring 模块的 set/get 函数，不可用则 None。"""
    try:
        import keyring            # noqa: F401
        from keyring.errors import KeyringError
    except Exception:
        return None
    try:
        # 有些环境装了 keyring 但没有后端守护进程，先探测一次
        keyring.get_password("snnu-portal-probe", "probe")
    except Exception:
        return None
    return keyring


def protect(plain: str) -> bytes:
    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password("snnu-portal", "campus-password", plain)
            return b"KEYRING:1"
        except Exception:
            pass
    blob = base64.b64encode(_xor(plain.encode("utf-8"), _SALT))
    return b"FILE1:" + blob


def unprotect(data: bytes) -> str:
    if data.startswith(b"KEYRING:1"):
        kr = _keyring()
        if kr is None:
            return ""
        try:
            return kr.get_password("snnu-portal", "campus-password") or ""
        except Exception:
            return ""
    if data.startswith(b"FILE1:"):
        try:
            raw = base64.b64decode(data[6:])
            return _xor(raw, _SALT).decode("utf-8")
        except Exception:
            return ""
    # 兼容可能的旧格式
    try:
        return data.decode("utf-8")
    except Exception:
        return ""


def secret_backend_name() -> str:
    if _keyring() is not None:
        return "系统 keyring（gnome-keyring / kwallet）"
    return "本机文件 0600（混淆存储，非加密）"


# --------------------------------------------------------------------------- #
# 开机自启：systemd 用户服务
#
# 不写 /etc/systemd/system（需要 root），而是写 ~/.config/systemd/user/ 下的
# 用户级服务，用 `systemctl --user` 管理，完全不需要管理员权限。
# --------------------------------------------------------------------------- #
UNIT_NAME = "campus-net-portal.service"


def _unit_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "systemd", "user")


def _unit_path() -> str:
    return os.path.join(_unit_dir(), UNIT_NAME)


def _systemctl(*args) -> tuple:
    exe = shutil.which("systemctl")
    if not exe:
        return (1, "systemctl 不存在")
    try:
        p = subprocess.run([exe, "--user", *args], capture_output=True,
                           text=True, timeout=30)
        return (p.returncode, (p.stdout + p.stderr).strip())
    except Exception as e:
        return (1, repr(e))


def set_autostart(enable: bool, silent: bool, command: str) -> bool:
    """写入/删除 systemd 用户服务，并 enable/disable。"""
    path = _unit_path()
    if not enable:
        _systemctl("disable", UNIT_NAME)
        try:
            os.remove(path)
        except OSError:
            pass
        _systemctl("daemon-reload")
        return True

    # command 形如 '/path/to/app --silent'，直接当 ExecStart
    unit = (
        "[Unit]\n"
        "Description=SNNU Campus Network Auto Login\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        "ExecStart={cmd}\n"
        "Restart=on-failure\n"
        "RestartSec=10\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    ).format(cmd=command)
    try:
        os.makedirs(_unit_dir(), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(unit)
    except OSError:
        return False

    _systemctl("daemon-reload")
    rc, _ = _systemctl("enable", UNIT_NAME)
    return rc == 0


def get_autostart() -> bool:
    try:
        if os.path.exists(_unit_path()):
            return True
    except OSError:
        pass
    rc, out = _systemctl("is-enabled", UNIT_NAME)
    return rc == 0 and out.strip() in ("enabled", "enabled-runtime", "static")


def autostart_backend_name() -> str:
    return "systemd 用户服务（~/.config/systemd/user）"


# --------------------------------------------------------------------------- #
# 网卡流量统计：读 /proc/net/dev
# --------------------------------------------------------------------------- #
# 只统计物理网卡，跳过 lo / docker / veth / br- 等虚拟接口
_SKIP_PREFIX = ("lo", "docker", "veth", "br-", "virbr", "tun", "tap", "wg",
                "vmnet", "vboxnet")


def _is_physical(name: str) -> bool:
    return not name.startswith(_SKIP_PREFIX)


def net_bytes() -> int:
    """本机物理网卡累计收发字节数；读不到返回 -1。"""
    try:
        total = 0
        with open("/proc/net/dev", "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[2:]        # 跳过两行表头
        for line in lines:
            if ":" not in line:
                continue
            name, rest = line.split(":", 1)
            name = name.strip()
            if not _is_physical(name):
                continue
            cols = rest.split()
            if len(cols) < 9:
                continue
            rx = int(cols[0])                # 接收字节
            tx = int(cols[8])                # 发送字节
            total += rx + tx
        return total
    except Exception:
        return -1


# --------------------------------------------------------------------------- #
# 单实例：对 PID 文件加 flock，进程退出即自动释放
# --------------------------------------------------------------------------- #
_lock_handle = None


def single_instance_lock(path: str) -> bool:
    """拿到独占锁返回 True；已被别的实例占用返回 False。"""
    global _lock_handle
    try:
        import fcntl
    except Exception:
        return True                     # 拿不到 fcntl 就不做限制
    try:
        fh = open(path, "a+")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        fh.seek(0)
        fh.truncate()
        fh.write(str(os.getpid()))
        fh.flush()
        _lock_handle = fh               # 必须留着，句柄一关锁就没了
        return True
    except OSError:
        return True


def open_in_file_manager(path: str) -> bool:
    """用桌面默认文件管理器打开目录（用于“打开配置目录”按钮）。"""
    import shutil as _sh
    for cmd in (["xdg-open", path], ["gio", "open", path], ["nautilus", path]):
        if _sh.which(cmd[0]):
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
                return True
            except Exception:
                continue
    return False
