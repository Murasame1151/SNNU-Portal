# -*- coding: utf-8 -*-
"""Windows 系统托盘图标（ctypes 直接调用 Win32，不引入 pystray / pywin32）。

只在 Windows 上使用；Linux 版不做托盘（开机自启用 systemd 用户服务实现）。

设计要点：
* 托盘窗口消息循环跑在独立线程，UI 线程（Tk）完全不被阻塞；
* 左键单击 / 双击 -> 打开主界面；右键 -> 弹出菜单；
* 所有回调都通过 post 一个可调用对象给 Tk，由 Tk 主线程执行。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import sys
import threading

# 图标绘制放在 iconart 里，Windows 用 ICO，Linux 用 PNG，共用同一套图形
from iconart import icon_pixels, make_ico, to_png   # noqa: F401

WM_APP = 0x8000
WM_TRAYICON = WM_APP + 1
WM_DESTROY = 0x0002
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_COMMAND = 0x0111
WM_CLOSE = 0x0010

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x01, 0x02, 0x04

IDM_SHOW, IDM_CONNECT, IDM_AUTOSTART, IDM_EXIT = 1001, 1002, 1003, 1004

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32
kernel32 = ctypes.windll.kernel32

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

user32.CreateWindowExW.restype = wt.HWND
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE,
                                   ctypes.c_void_p]
user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.CreatePopupMenu.restype = wt.HMENU
user32.CreatePopupMenu.argtypes = []
user32.LoadIconW.restype = wt.HICON
user32.LoadIconW.argtypes = [wt.HINSTANCE, ctypes.c_void_p]
user32.LoadImageW.restype = wt.HANDLE
user32.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT,
                              ctypes.c_int, ctypes.c_int, wt.UINT]
user32.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
user32.TrackPopupMenu.restype = ctypes.c_int
user32.TrackPopupMenu.argtypes = [wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, wt.HWND, ctypes.c_void_p]
user32.DestroyMenu.argtypes = [wt.HMENU]
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.DestroyWindow.argtypes = [wt.HWND]
user32.RegisterClassW.argtypes = [ctypes.c_void_p]
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
user32.PostQuitMessage.argtypes = [ctypes.c_int]
kernel32.GetModuleHandleW.restype = wt.HMODULE
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
shell32.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.c_void_p]


# --------------------------------------------------------------------------- #
# 图标绘制已移到 iconart.py（Windows 用 ICO，Linux 用 PNG，共用同一套图形）
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
class TrayIcon:
    def __init__(self, tooltip: str, on_show, on_connect, on_toggle_autostart,
                 on_exit, autostart_checked=lambda: False):
        self.tooltip = tooltip
        self.on_show = on_show
        self.on_connect = on_connect
        self.on_toggle_autostart = on_toggle_autostart
        self.on_exit = on_exit
        self.autostart_checked = autostart_checked
        self.hwnd = None
        self.icon = None
        self._thread = None
        self._ready = threading.Event()
        self._wndproc = WNDPROC(self._proc)   # 必须保留引用，否则会被 GC

    # ---- 线程入口 ----
    def start(self) -> bool:
        self._thread = threading.Thread(target=self._run, name="tray", daemon=True)
        self._thread.start()
        self._ready.wait(3.0)
        return self.hwnd is not None

    def _run(self):
        try:
            hinst = kernel32.GetModuleHandleW(None)
            cls_name = "CampusNetPortalTrayWnd"
            wc = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
            wndclass = type("WNDCLASSW", (ctypes.Structure,), {"_fields_": [
                ("style", wt.UINT), ("lpfnWndProc", wc),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH),
                ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR)]})()
            wndclass.lpfnWndProc = self._wndproc
            wndclass.hInstance = hinst
            wndclass.lpszClassName = cls_name
            user32.RegisterClassW(ctypes.byref(wndclass))

            self.hwnd = user32.CreateWindowExW(
                0, cls_name, "CampusNetPortalTray", 0, 0, 0, 0, 0,
                None, None, hinst, None)
            if not self.hwnd:
                return

            self.icon = self._load_icon()
            nid = self._nid()
            shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))

            self._ready.set()
            msg = wt.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception:
            pass
        finally:
            self._ready.set()
            try:
                if self.hwnd:
                    nid = self._nid()
                    shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
            except Exception:
                pass

    def _load_icon(self):
        # 优先用同目录下的 net.ico（打包时一起带上），保证托盘/任务栏图标一致
        for cand in self._icon_candidates():
            try:
                h = user32.LoadImageW(None, cand, 1, 0, 0, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
                if h:
                    return h
            except Exception:
                continue
        return user32.LoadIconW(None, 32512)  # IDI_APPLICATION

    @staticmethod
    def _icon_candidates():
        base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
        out = [os.path.join(base, "net.ico")]
        if getattr(sys, "frozen", False):
            out.append(os.path.join(os.path.dirname(sys.executable), "net.ico"))
        return out

    def set_tooltip(self, text: str):
        self.tooltip = text[:120]
        if self.hwnd:
            try:
                nid = self._nid()
                shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
            except Exception:
                pass

    def _nid(self):
        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uID", wt.UINT),
                        ("uFlags", wt.UINT), ("uCallbackMessage", wt.UINT),
                        ("hIcon", wt.HICON), ("szTip", ctypes.c_wchar * 128),
                        ("dwState", wt.DWORD), ("dwStateMask", wt.DWORD),
                        ("szInfo", ctypes.c_wchar * 256), ("uVersion", wt.UINT),
                        ("szInfoTitle", ctypes.c_wchar * 64),
                        ("dwInfoFlags", wt.DWORD)]
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAYICON
        nid.hIcon = self.icon
        nid.szTip = self.tooltip
        return nid

    # ---- 消息处理 ----
    def _proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAYICON:
            ev = lparam & 0xFFFF
            if ev in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                self._safe(self.on_show)
            elif ev == WM_RBUTTONUP:
                self._menu()
            return 0
        if msg == WM_COMMAND:
            cmd = wparam & 0xFFFF
            if cmd == IDM_SHOW:
                self._safe(self.on_show)
            elif cmd == IDM_CONNECT:
                self._safe(self.on_connect)
            elif cmd == IDM_AUTOSTART:
                self._safe(self.on_toggle_autostart)
            elif cmd == IDM_EXIT:
                self._safe(self.on_exit)
            return 0
        if msg == WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _menu(self):
        try:
            user32.SetForegroundWindow(self.hwnd)
            menu = user32.CreatePopupMenu()
            mf_string = 0x0000
            mf_checked = 0x0008
            mf_sep = 0x0800
            tpm_rightbutton = 0x0002
            tpm_returncmd = 0x0100
            user32.AppendMenuW(menu, mf_string, IDM_SHOW, "打开主界面")
            user32.AppendMenuW(menu, mf_string, IDM_CONNECT, "立即重新连接")
            user32.AppendMenuW(menu, mf_string | (mf_checked if self.autostart_checked() else 0),
                               IDM_AUTOSTART, "开机自动启动")
            user32.AppendMenuW(menu, mf_sep, 0, None)
            user32.AppendMenuW(menu, mf_string, IDM_EXIT, "退出")
            pt = wt.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            cmd = user32.TrackPopupMenu(menu, tpm_rightbutton | tpm_returncmd,
                                        pt.x, pt.y, 0, self.hwnd, None)
            user32.PostMessageW(self.hwnd, 0x0000, 0, 0)   # WM_NULL
            user32.DestroyMenu(menu)
            if cmd:
                self._proc(self.hwnd, WM_COMMAND, cmd, 0)
        except Exception:
            pass

    @staticmethod
    def _safe(fn):
        try:
            fn()
        except Exception:
            pass

    def stop(self):
        if self.hwnd:
            try:
                user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
            except Exception:
                pass
