# -*- coding: utf-8 -*-
"""配置读写 + Windows DPAPI 加解密（仅依赖标准库 ctypes）。

配置目录: %APPDATA%\\CampusNetPortal
    config.ini    明文配置（不含密码）
    secret.bin    DPAPI 加密后的密码（绑定当前 Windows 用户）
    app.log       运行日志
"""
from __future__ import annotations

import base64
import configparser
import ctypes
import ctypes.wintypes as wt
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
    "check_sec": "45",            # 探活周期
    "reconnect": "1",
}


# --------------------------------------------------------------------------- #
# 路径
# --------------------------------------------------------------------------- #
def data_dir() -> str:
    """配置目录。

    默认 %APPDATA%\\CampusNetPortal。
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
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, APP_NAME)
    try:
        os.makedirs(d, exist_ok=True)
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
# DPAPI（当前用户作用域）
# --------------------------------------------------------------------------- #
class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _crypt(protect: bool, raw: bytes) -> bytes:
    buf = ctypes.create_string_buffer(raw, len(raw))
    blob_in = _BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _BLOB()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else \
        ctypes.windll.crypt32.CryptUnprotectData
    args = (ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
    if not fn(*args):
        raise OSError("DPAPI call failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _secret_path() -> str:
    return os.path.join(data_dir(), "secret.bin")


def save_password(pwd: str) -> None:
    data = _crypt(True, pwd.encode("utf-8"))
    with open(_secret_path(), "wb") as f:
        f.write(base64.b64encode(data))


def load_password() -> str:
    try:
        with open(_secret_path(), "rb") as f:
            data = base64.b64decode(f.read())
        return _crypt(False, data).decode("utf-8")
    except Exception:
        return ""


def clear_password() -> None:
    try:
        os.remove(_secret_path())
    except OSError:
        pass


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
# 开机自启（当前用户注册表，不需要管理员权限）
# --------------------------------------------------------------------------- #
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "CampusNetPortal"

_adv = ctypes.windll.advapi32
_HKEY = ctypes.c_void_p          # 64 位下句柄必须按指针声明，否则会被截断
_HKEY_CURRENT_USER = ctypes.c_void_p(0x80000001)
_REG_SZ = 1

# 显式声明 argtypes：不声明的话 ctypes 会把 64 位句柄当 32 位 int 传，注册表操作必然失败
_adv.RegOpenKeyExW.argtypes = [_HKEY, wt.LPCWSTR, wt.DWORD, wt.DWORD,
                               ctypes.POINTER(_HKEY)]
_adv.RegSetValueExW.argtypes = [_HKEY, wt.LPCWSTR, wt.DWORD, wt.DWORD,
                                ctypes.c_void_p, wt.DWORD]
_adv.RegDeleteValueW.argtypes = [_HKEY, wt.LPCWSTR]
_adv.RegQueryValueExW.argtypes = [_HKEY, wt.LPCWSTR, ctypes.POINTER(wt.DWORD),
                                  ctypes.POINTER(wt.DWORD), ctypes.c_void_p,
                                  ctypes.POINTER(wt.DWORD)]
_adv.RegCloseKey.argtypes = [_HKEY]
_adv.RegQueryValueExW.restype = ctypes.c_long
_adv.RegSetValueExW.restype = ctypes.c_long
_adv.RegDeleteValueW.restype = ctypes.c_long
_adv.RegOpenKeyExW.restype = ctypes.c_long

# 只申请读/写值所需的权限，不要 KEY_ALL_ACCESS（Run 键上会因权限过大被拒）
_KEY_QUERY_VALUE = 0x0001
_KEY_SET_VALUE = 0x0002


def exe_command(silent: bool) -> str:
    if getattr(sys, "frozen", False):
        exe = sys.executable
        args = " --silent" if silent else ""
    else:
        py = sys.executable
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
        exe = sys.executable
        args = ' "%s"%s' % (script, " --silent" if silent else "")
    return '"%s"%s' % (exe, args)


def set_autostart(enable: bool, silent: bool = True) -> bool:
    try:
        hkey = _HKEY()
        if _adv.RegOpenKeyExW(_HKEY_CURRENT_USER, RUN_KEY, 0,
                              _KEY_QUERY_VALUE | _KEY_SET_VALUE,
                              ctypes.byref(hkey)) != 0:
            return False
        try:
            if enable:
                cmd = exe_command(silent)
                rc = _adv.RegSetValueExW(hkey, RUN_NAME, 0, _REG_SZ,
                                         ctypes.c_wchar_p(cmd),
                                         (len(cmd) + 1) * ctypes.sizeof(ctypes.c_wchar))
                return rc == 0
            # 关闭：删掉整条键，不存在也算成功
            return _adv.RegDeleteValueW(hkey, RUN_NAME) in (0, 2)
        finally:
            _adv.RegCloseKey(hkey)
    except Exception as e:
        log("设置自启失败: %r" % (e,))
        return False


def get_autostart() -> bool:
    try:
        hkey = _HKEY()
        if _adv.RegOpenKeyExW(_HKEY_CURRENT_USER, RUN_KEY, 0, _KEY_QUERY_VALUE,
                              ctypes.byref(hkey)) != 0:
            return False
        try:
            return _adv.RegQueryValueExW(hkey, RUN_NAME, None, None, None, None) == 0
        finally:
            _adv.RegCloseKey(hkey)
    except Exception:
        return False
