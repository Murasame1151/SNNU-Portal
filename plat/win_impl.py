# -*- coding: utf-8 -*-
"""Windows 专有实现：DPAPI 加解密、注册表开机自启、网卡流量统计。

Linux 上这些都不会被导入（见同目录的 lin_*.py），所以本模块可以放心用
`ctypes.windll`，在非 Windows 上导入即报错。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os

IS_WINDOWS = True

# --------------------------------------------------------------------------- #
# DPAPI（当前用户作用域）
# --------------------------------------------------------------------------- #
class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _crypt(protect: bool, raw: bytes) -> bytes:
    buf = ctypes.create_string_buffer(raw, len(raw))
    blob_in = _BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _BLOB()
    fn = (ctypes.windll.crypt32.CryptProtectData if protect
          else ctypes.windll.crypt32.CryptUnprotectData)
    args = (ctypes.byref(blob_in), None, None, None, None, 0,
            ctypes.byref(blob_out))
    if not fn(*args):
        raise OSError("DPAPI call failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def protect(plain: str) -> bytes:
    """加密。返回的字节由当前 Windows 用户绑定，换机换用户都解不开。"""
    return _crypt(True, plain.encode("utf-8"))


def unprotect(data: bytes) -> str:
    return _crypt(False, data).decode("utf-8")


def secret_backend_name() -> str:
    return "Windows DPAPI（当前用户）"


# --------------------------------------------------------------------------- #
# 注册表开机自启（HKCU，无需管理员）
# --------------------------------------------------------------------------- #
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "CampusNetPortal"

_adv = ctypes.windll.advapi32
_HKEY = ctypes.c_void_p
_HKEY_CURRENT_USER = ctypes.c_void_p(0x80000001)
_REG_SZ = 1
_KEY_QUERY_VALUE = 0x0001
_KEY_SET_VALUE = 0x0002

# 不声明 argtypes 的话，ctypes 会把 64 位句柄当 32 位 int 传，注册表操作必然失败
_adv.RegOpenKeyExW.argtypes = [_HKEY, wt.LPCWSTR, wt.DWORD, wt.DWORD,
                               ctypes.POINTER(_HKEY)]
_adv.RegSetValueExW.argtypes = [_HKEY, wt.LPCWSTR, wt.DWORD, wt.DWORD,
                                ctypes.c_void_p, wt.DWORD]
_adv.RegDeleteValueW.argtypes = [_HKEY, wt.LPCWSTR]
_adv.RegQueryValueExW.argtypes = [_HKEY, wt.LPCWSTR, ctypes.POINTER(wt.DWORD),
                                  ctypes.POINTER(wt.DWORD), ctypes.c_void_p,
                                  ctypes.POINTER(wt.DWORD)]
_adv.RegCloseKey.argtypes = [_HKEY]
for _f in ("RegOpenKeyExW", "RegSetValueExW", "RegDeleteValueW",
           "RegQueryValueExW"):
    getattr(_adv, _f).restype = ctypes.c_long


def set_autostart(enable: bool, silent: bool, command: str) -> bool:
    try:
        hkey = _HKEY()
        if _adv.RegOpenKeyExW(_HKEY_CURRENT_USER, RUN_KEY, 0,
                              _KEY_QUERY_VALUE | _KEY_SET_VALUE,
                              ctypes.byref(hkey)) != 0:
            return False
        try:
            if enable:
                rc = _adv.RegSetValueExW(
                    hkey, RUN_NAME, 0, _REG_SZ, ctypes.c_wchar_p(command),
                    (len(command) + 1) * ctypes.sizeof(ctypes.c_wchar))
                return rc == 0
            return _adv.RegDeleteValueW(hkey, RUN_NAME) in (0, 2)
        finally:
            _adv.RegCloseKey(hkey)
    except Exception:
        return False


def get_autostart() -> bool:
    try:
        hkey = _HKEY()
        if _adv.RegOpenKeyExW(_HKEY_CURRENT_USER, RUN_KEY, 0, _KEY_QUERY_VALUE,
                              ctypes.byref(hkey)) != 0:
            return False
        try:
            return _adv.RegQueryValueExW(hkey, RUN_NAME, None, None, None,
                                         None) == 0
        finally:
            _adv.RegCloseKey(hkey)
    except Exception:
        return False


def autostart_backend_name() -> str:
    return "注册表 HKCU\\...\\Run"


# --------------------------------------------------------------------------- #
# 网卡流量统计（IP Helper API，只读、开销极低）
# --------------------------------------------------------------------------- #
class _MIB_IF_ROW2(ctypes.Structure):
    """与 Windows MIB_IF_ROW2 严格对齐（sizeof = 1352，64 位）。

    字段偏移必须和系统一致：多一个字节都会让 Table[i] 的步长错位，
    读出来的计数器就是垃圾数据（表现为“流量永远是 0”）。
    """
    _fields_ = [
        ("InterfaceLuid", ctypes.c_uint64),          # 0
        ("InterfaceIndex", ctypes.c_uint32),         # 8
        ("InterfaceGuid", ctypes.c_byte * 16),       # 12
        ("Alias", ctypes.c_wchar * 257),             # 28
        ("Description", ctypes.c_wchar * 257),       # 542
        ("PhysicalAddressLength", ctypes.c_uint32),  # 1056
        ("PhysicalAddress", ctypes.c_byte * 32),     # 1060
        ("PermanentPhysicalAddress", ctypes.c_byte * 32),  # 1092
        ("Mtu", ctypes.c_uint32),                    # 1124
        ("Type", ctypes.c_uint32),                   # 1128
        ("TunnelType", ctypes.c_uint32),             # 1132
        ("MediaType", ctypes.c_uint32),              # 1136
        ("PhysicalMediumType", ctypes.c_uint32),     # 1140
        ("AccessType", ctypes.c_uint32),             # 1144
        ("DirectionType", ctypes.c_uint32),          # 1148
        ("InterfaceAndOperStatusFlags", ctypes.c_byte),  # 1152
        ("_pad1", ctypes.c_byte * 3),                # 1153
        ("OperStatus", ctypes.c_uint32),             # 1156
        ("AdminStatus", ctypes.c_uint32),            # 1160
        ("MediaConnectState", ctypes.c_uint32),      # 1164
        ("NetworkGuid", ctypes.c_byte * 16),         # 1168
        ("ConnectionType", ctypes.c_uint32),         # 1184
        ("_pad2", ctypes.c_uint32),                  # 1188
        ("TransmitLinkSpeed", ctypes.c_uint64),      # 1192
        ("ReceiveLinkSpeed", ctypes.c_uint64),       # 1200
        ("InOctets", ctypes.c_uint64),               # 1208
        ("InUcastPkts", ctypes.c_uint64),            # 1216
        ("InNUcastPkts", ctypes.c_uint64),           # 1224
        ("InDiscards", ctypes.c_uint64),             # 1232
        ("InErrors", ctypes.c_uint64),               # 1240
        ("InUnknownProtos", ctypes.c_uint64),        # 1248
        ("InUcastOctets", ctypes.c_uint64),          # 1256
        ("InMulticastOctets", ctypes.c_uint64),      # 1264
        ("InBroadcastOctets", ctypes.c_uint64),      # 1272
        ("OutOctets", ctypes.c_uint64),              # 1280
        ("OutUcastPkts", ctypes.c_uint64),           # 1288
        ("OutNUcastPkts", ctypes.c_uint64),          # 1296
        ("OutDiscards", ctypes.c_uint64),            # 1304
        ("OutErrors", ctypes.c_uint64),              # 1312
        ("OutUcastOctets", ctypes.c_uint64),         # 1320
        ("OutMulticastOctets", ctypes.c_uint64),     # 1328
        ("OutBroadcastOctets", ctypes.c_uint64),     # 1336
        ("OutQLen", ctypes.c_uint64),                # 1344
    ]                                                # 合计 1352


class _MIB_IF_TABLE2(ctypes.Structure):
    _fields_ = [("NumEntries", ctypes.c_uint32),
                ("_pad", ctypes.c_uint32),
                ("Table", _MIB_IF_ROW2 * 1)]


_MIB_IF_ROW2_SIZE = ctypes.sizeof(_MIB_IF_ROW2)
_TABLE_OFFSET = 8

# InterfaceAndOperStatusFlags 的位定义（MSDN）
_IF_HARDWARE = 0x01
_IF_FILTER = 0x04
_IF_TYPE_ETHERNET = 6
_IF_TYPE_WIFI = 71

_get_if_table2 = getattr(ctypes.windll.iphlpapi, "GetIfTable2", None)
_free_mib_table = getattr(ctypes.windll.iphlpapi, "FreeMibTable", None)


def net_bytes() -> int:
    """本机真实网卡累计收发字节数；读不到返回 -1。

    只统计物理网卡：NDIS 轻量筛选器与真实网卡共用同一组计数器，
    不加 IF_HARDWARE 过滤会把同一份流量重复累加（实测能虚高 6 倍）。
    """
    if _get_if_table2 is None:
        return -1
    ptr = ctypes.c_void_p()
    try:
        if _get_if_table2(ctypes.byref(ptr)) != 0 or not ptr:
            return -1
        num = ctypes.c_uint32.from_address(ptr.value).value
        base = ptr.value + _TABLE_OFFSET
        total = 0
        counted = 0
        fallback = 0
        for i in range(num):
            row = _MIB_IF_ROW2.from_address(base + i * _MIB_IF_ROW2_SIZE)
            if row.Type not in (_IF_TYPE_ETHERNET, _IF_TYPE_WIFI) or row.OperStatus != 1:
                continue
            flags = ctypes.c_ubyte(row.InterfaceAndOperStatusFlags).value
            octets = row.InOctets + row.OutOctets
            if flags & _IF_HARDWARE and not flags & _IF_FILTER:
                total += octets
                counted += 1
            fallback = max(fallback, octets)
        # flags 布局万一变了，就退回“取流量最大的那块网卡”
        return total if counted else (fallback if fallback else 0)
    except Exception:
        return -1
    finally:
        if ptr and _free_mib_table is not None:
            try:
                _free_mib_table(ptr)
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# 单实例：命名互斥量（进程退出自动释放）
# --------------------------------------------------------------------------- #
_kernel32 = ctypes.windll.kernel32
_mutex_handle = None


def single_instance_lock(name: str) -> bool:
    """第一个实例拿到互斥量返回 True；已有实例在跑返回 False。"""
    global _mutex_handle
    try:
        _kernel32.CreateMutexW(None, False, name)
        _mutex_handle = True
        return _kernel32.GetLastError() != 183      # ERROR_ALREADY_EXISTS
    except Exception:
        return True


def open_in_file_manager(path: str) -> bool:
    try:
        os.startfile(path)          # noqa: S606  Windows 专用
        return True
    except Exception:
        return False
