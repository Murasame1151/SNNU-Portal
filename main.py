# -*- coding: utf-8 -*-
"""SNNU-Portal 校园网自动认证 —— v2.0

功能：
  1. 图形界面手动输入 账号 / 密码 / 运营商，一键连接；
  2. 记住账号密码（DPAPI 加密，仅本机本用户可解密）；
  3. 开机静默自启（不显示窗口，只在托盘）；后台自动认证；
  4. 断线自动重连；
  5. 防掉线保活：检测本机是否真的长时间没有流量，空闲时才补一次极小流量，
     并定期向 portal 查询登录状态，避免“长时间无流量被强制下线”。

后台占用：常驻 1 个 Tk 主线程 + 1 个托盘线程 + 1 个网络线程，
空闲时 CPU≈0，内存≈20-30MB。
"""
from __future__ import annotations

import ctypes
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

import cfgtool
import portal
from cfgtool import as_bool, log

APP_TITLE = "校园网自动认证"
VERSION = "2.0"
CREATE_NO_WINDOW = 0x08000000


# --------------------------------------------------------------------------- #
# 网络工作线程
# --------------------------------------------------------------------------- #
class NetWorker:
    """在后台线程里完成 登录 / 探活 / 保活 / 重连。"""

    def __init__(self, cfg: dict, emit):
        self.emit = emit                      # emit(kind, *payload) -> 线程安全
        self.cfg = dict(cfg)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._force_login = False
        self._force_logout = False
        self.client = None
        self._thread = None
        self.status = "idle"                  # idle / connecting / online / offline

    # ---------------- 生命周期 ----------------
    def start(self):
        self._thread = threading.Thread(target=self._run, name="net", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def update_cfg(self, cfg: dict):
        with self._lock:
            reload = (self.cfg.get("account") != cfg.get("account")
                      or self.cfg.get("carrier") != cfg.get("carrier")
                      or self.cfg.get("password") != cfg.get("password"))
            self.cfg = dict(cfg)
        if reload:
            self.client = None

    def request_login(self, logout_first: bool = False):
        with self._lock:
            self._force_login = True
            self._force_logout = logout_first
        self._wake.set()

    def request_logout(self):
        threading.Thread(target=self._logout_now, daemon=True).start()

    # ---------------- 内部 ----------------
    def _log(self, text: str):
        log(text)
        self.emit("log", text)

    def _state(self, state: str, detail: str = ""):
        self.status = state
        self.emit("state", state, detail)

    def _client(self) -> portal.PortalClient:
        with self._lock:
            cfg = dict(self.cfg)
        if self.client is None:
            self.client = portal.PortalClient(cfg.get("account", ""),
                                              cfg.get("password", ""),
                                              cfg.get("carrier", ""))
        return self.client

    def _logout_now(self):
        c = self._client()
        c.logout()
        self._log("已断开连接")
        self._state("idle", "")

    def _do_login(self) -> bool:
        self._state("connecting", "正在认证…")
        c = self._client()
        ok = c.login()
        if ok:
            self._log("认证成功（%s）" % c.last_message)
            self._state("online", "已连接")
        else:
            self._log("认证失败：%s" % (c.last_message or "未知原因"))
            self._state("offline", c.last_message or "认证失败")
        return ok

    # ---------------- 网络线程回调 ----------------
    def _stop_check(self) -> bool:
        """网络线程在探活/保活途中调用：用户手动操作或程序要退出时立刻让路。"""
        if self._stop.is_set():
            return True
        with self._lock:
            return self._force_login

    def _run(self):
        backoff = 5
        last_portal_check = 0.0
        last_traffic = time.time()
        last_bytes = portal.net_bytes()
        fail_count = 0

        while not self._stop.is_set():
            try:
                with self._lock:
                    cfg = dict(self.cfg)
                    force_login = self._force_login
                    force_logout = self._force_logout
                    self._force_login = False
                    self._force_logout = False

                if force_login:
                    if not cfg.get("account"):
                        self._log("账号为空，无法连接")
                        self._state("idle", "请填写账号")
                        self._wake.wait(1.0)
                        self._wake.clear()
                        continue
                    if force_logout:
                        self._client().logout()
                    if self._do_login():
                        backoff = 5
                        fail_count = 0
                        last_portal_check = time.time()
                    else:
                        self._wake.wait(3.0)
                        self._wake.clear()
                    continue

                if not cfg.get("account"):
                    self._wake.wait(10.0)
                    self._wake.clear()
                    continue

                if self.status != "online":
                    # 启动或掉线后重新认证
                    if self._do_login():
                        backoff = 5
                        fail_count = 0
                        last_portal_check = time.time()
                    else:
                        fail_count += 1
                        self._log("第 %d 次重连失败，%d 秒后重试" % (fail_count, backoff))
                        self._wake.wait(backoff)
                        self._wake.clear()
                        backoff = min(backoff * 2, 60)
                        continue
                else:
                    now = time.time()
                    # ---- 1. 问 portal“我现在是谁”：最可靠的在线判据，顺便续会话 ----
                    if now - last_portal_check >= max(20, int(cfg.get("check_sec", 45))):
                        last_portal_check = now
                        if not self._client().portal_status(should_stop=self._stop_check):
                            self._log("portal 显示已掉线，开始重新认证")
                            self._state("offline", "已掉线，正在重连…")
                            continue

                    # ---- 2. 防掉线保活：只在“真的没有流量”时才补流量 ----
                    if as_bool(cfg.get("keepalive", "1")):
                        cur = portal.net_bytes()
                        if cur >= 0 and last_bytes >= 0:
                            if cur > last_bytes:
                                last_traffic = now
                            last_bytes = cur
                            idle = now - last_traffic
                            if idle >= max(30, int(cfg.get("idle_sec", 150))):
                                ok = self._client().keepalive(
                                    should_stop=self._stop_check)
                                last_traffic = time.time()
                                last_bytes = portal.net_bytes()
                                if ok:
                                    self._log("已空闲 %d 秒，补发一次保活流量" % int(idle))
                                else:
                                    self._log("保活流量发送失败，稍后重试")
                        elif now - last_traffic >= max(60, int(cfg.get("traffic_sec", 300))):
                            # 读不到网卡统计时退化为按周期补流量
                            self._client().keepalive(should_stop=self._stop_check)
                            last_traffic = now
                            self._log("已补发一次保活流量")

                self._wake.wait(5.0)
                self._wake.clear()
            except Exception as e:                       # 任何异常都不许弄死线程
                log("网络线程异常: %r" % (e,))
                time.sleep(3)

    # 供外部查询
    def is_online(self) -> bool:
        return self.status == "online"


# --------------------------------------------------------------------------- #
# 界面
# --------------------------------------------------------------------------- #
STATE_STYLE = {
    "idle": ("○ 未连接", "#6b7280"),
    "connecting": ("◌ 正在认证…", "#d97706"),
    "online": ("● 已连接", "#16a34a"),
    "offline": ("● 已断开", "#dc2626"),
}


class App:
    def __init__(self, silent: bool = False):
        self.cfg = cfgtool.load()
        self.silent = silent
        self.tray = None
        self._closing = False
        self._since = time.time()
        self.cmdq = queue.Queue()      # 托盘线程 -> Tk 主线程 的可调用对象
        self.evq = queue.Queue()       # 网络线程 -> Tk 主线程 的事件

        self.root = tk.Tk()
        self.root.title(APP_TITLE + " v" + VERSION)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._set_icon()
        self._center(430, 470)

        self._build_ui()
        self._apply_cfg_to_ui()

        self.worker = NetWorker(self.cfg, self._emit_from_worker)
        self.worker.start()

        self._pump()
        self._tick()

        self._init_tray()
        if silent:
            self.root.withdraw()
            log("静默启动")
        else:
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after(400, lambda: self.root.attributes("-topmost", False))

    # ---------------- 窗口基础 ----------------
    def _set_icon(self):
        base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
        ico = os.path.join(base, "net.ico")
        if not os.path.exists(ico):
            try:
                ico_dir = cfgtool.data_dir()
                cand = os.path.join(ico_dir, "net.ico")
                if not os.path.exists(cand):
                    from trayicon import make_ico
                    make_ico(cand)
                ico = cand
            except Exception:
                return
        try:
            self.root.iconbitmap(ico)
        except Exception:
            pass

    def _center(self, w, h):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = int((sw - w) / 2)
        y = int((sh - h) / 2)
        self.root.geometry("%dx%d+%d+%d" % (w, h, x, y))

    # ---------------- 布局 ----------------
    def _build_ui(self):
        try:
            self.root.option_add("*Font", ("Microsoft YaHei UI", 9))
        except Exception:
            pass

        bg = "#ffffff"
        self.root.configure(bg=bg)
        st = ttk.Style()
        try:
            st.theme_use("vista")
        except Exception:
            pass
        st.configure("Card.TFrame", background=bg)
        st.configure("Card.TLabel", background=bg)
        st.configure("H1.TLabel", background=bg, font=("Microsoft YaHei UI", 12, "bold"))
        st.configure("Dim.TLabel", background=bg, foreground="#6b7280")
        st.configure("Big.TButton", font=("Microsoft YaHei UI", 10, "bold"), padding=6)

        root = ttk.Frame(self.root, style="Card.TFrame", padding=(18, 14, 18, 14))
        root.pack(fill="both", expand=True)

        head = ttk.Frame(root, style="Card.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text=APP_TITLE, style="H1.TLabel").pack(side="left")
        self.lbl_state = ttk.Label(head, text="○ 未连接", style="Dim.TLabel")
        self.lbl_state.pack(side="right", pady=(4, 0))

        ttk.Separator(root, orient="horizontal").pack(fill="x", pady=(10, 12))

        form = ttk.Frame(root, style="Card.TFrame")
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="账号", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=6)
        self.var_acc = tk.StringVar()
        ttk.Entry(form, textvariable=self.var_acc, width=26).grid(row=0, column=1, sticky="ew", pady=6)

        ttk.Label(form, text="密码", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=6)
        self.var_pwd = tk.StringVar()
        self.ent_pwd = ttk.Entry(form, textvariable=self.var_pwd, show="●", width=26)
        self.ent_pwd.grid(row=1, column=1, sticky="ew", pady=6)
        self.var_show = tk.BooleanVar(value=False)
        ttk.Checkbutton(form, text="显示", variable=self.var_show,
                        command=self._toggle_show).grid(row=1, column=2, padx=(6, 0))

        ttk.Label(form, text="运营商", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=6)
        self.var_carrier = tk.StringVar()
        names = [c[0] for c in portal.CARRIERS]
        self.cmb = ttk.Combobox(form, textvariable=self.var_carrier, values=names,
                                state="readonly", width=24)
        self.cmb.grid(row=2, column=1, columnspan=2, sticky="ew", pady=6)

        ttk.Separator(root, orient="horizontal").pack(fill="x", pady=(14, 8))

        opt = ttk.Frame(root, style="Card.TFrame")
        opt.pack(fill="x")
        self.var_remember = tk.BooleanVar(value=True)
        self.var_autostart = tk.BooleanVar(value=False)
        self.var_keepalive = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text="记住账号密码", variable=self.var_remember,
                        command=self._save_prefs).pack(anchor="w")
        ttk.Checkbutton(opt, text="开机静默自启（后台运行，不显示窗口）",
                        variable=self.var_autostart,
                        command=self._toggle_autostart).pack(anchor="w")
        ttk.Checkbutton(opt, text="防掉线保活（无流量时自动补发）",
                        variable=self.var_keepalive,
                        command=self._save_prefs).pack(anchor="w")

        btns = ttk.Frame(root, style="Card.TFrame")
        btns.pack(fill="x", pady=(16, 6))
        self.btn_conn = ttk.Button(btns, text="连  接", style="Big.TButton",
                                   command=self.on_connect)
        self.btn_conn.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.btn_disc = ttk.Button(btns, text="断开", command=self.on_disconnect)
        self.btn_disc.pack(side="left", expand=True, fill="x", padx=4)
        ttk.Button(btns, text="设置", command=self.open_settings).pack(
            side="left", expand=True, fill="x", padx=(4, 0))

        self.lbl_msg = ttk.Label(root, text="就绪", style="Dim.TLabel",
                                 wraplength=390, justify="left")
        self.lbl_msg.pack(fill="x", pady=(10, 0), side="bottom")
        foot = ttk.Frame(root, style="Card.TFrame")
        foot.pack(fill="x", side="bottom", pady=(8, 0))
        self.lbl_tip = ttk.Label(foot, text="关闭窗口保持后台运行，右键托盘图标可退出",
                                 style="Dim.TLabel")
        self.lbl_tip.pack(side="left")
        self.lbl_up = ttk.Label(foot, text="", style="Dim.TLabel")
        self.lbl_up.pack(side="right")

    def _toggle_show(self):
        self.ent_pwd.configure(show="" if self.var_show.get() else "●")

    # ---------------- 配置 <-> 界面 ----------------
    def _apply_cfg_to_ui(self):
        self.var_acc.set(self.cfg.get("account", ""))
        self.var_pwd.set(self.cfg.get("password", ""))
        code = self.cfg.get("carrier", "mobile")
        name = next((n for n, c in portal.CARRIERS if c == code), "移动")
        self.var_carrier.set(name)
        self.var_remember.set(as_bool(self.cfg.get("remember", "0")) or not self.cfg.get("account"))
        real_auto = cfgtool.get_autostart()
        self.cfg["autostart"] = "1" if real_auto else "0"
        self.var_autostart.set(real_auto)
        self.var_keepalive.set(as_bool(self.cfg.get("keepalive", "1")))

    def _carrier_code(self) -> str:
        name = self.var_carrier.get()
        return next((c for n, c in portal.CARRIERS if n == name), "mobile")

    def _save_prefs(self):
        """把界面上的选择落到磁盘。

        注意：不勾“记住”时不再保存密码文件，但本次会话仍继续用界面里的密码，
        所以这里不能把密码从内存配置里抹掉（否则刚连上就会被自己的重连逻辑踢掉）。
        """
        cfg = dict(self.cfg)
        cfg["account"] = self.var_acc.get().strip()
        cfg["password"] = self.var_pwd.get()
        cfg["carrier"] = self._carrier_code()
        cfg["remember"] = "1" if self.var_remember.get() else "0"
        cfg["keepalive"] = "1" if self.var_keepalive.get() else "0"
        cfg["autostart"] = "1" if self.var_autostart.get() else "0"
        if cfg["remember"]:
            if cfg["account"] and cfg["password"]:
                try:
                    cfgtool.save_password(cfg["password"])
                except Exception as e:
                    self.set_msg("密码保存失败：%s" % e)
        else:
            cfgtool.clear_password()
        cfgtool.save(cfg)
        self.cfg = cfg
        self.worker.update_cfg(cfg)

    def collect(self) -> dict:
        cfg = dict(self.cfg)
        cfg["account"] = self.var_acc.get().strip()
        cfg["password"] = self.var_pwd.get()
        cfg["carrier"] = self._carrier_code()
        return cfg

    def _toggle_autostart(self):
        want = self.var_autostart.get()
        ok = cfgtool.set_autostart(want, silent=True)
        if not ok:
            self.var_autostart.set(not want)
            self.set_msg("设置开机自启失败（可能被安全软件拦截）")
        else:
            self.set_msg("已开启开机静默自启" if want else "已关闭开机自启")
        self.cfg["autostart"] = "1" if want else "0"
        cfgtool.save(self.cfg)

    # ---------------- 动作 ----------------
    def on_connect(self):
        self._save_prefs()
        if not self.var_acc.get().strip():
            self.set_msg("请先填写账号")
            return
        self.set_msg("正在认证…")
        self.worker.request_login(logout_first=True)

    def on_disconnect(self):
        self.set_msg("正在断开…")
        self.worker.request_logout()

    def _init_tray(self):
        try:
            from trayicon import TrayIcon
            self.tray = TrayIcon(
                APP_TITLE,
                on_show=lambda: self._ui(self.show_window),
                on_connect=lambda: self._ui(self.on_connect),
                on_toggle_autostart=lambda: self._ui(self._tray_toggle_autostart),
                on_exit=lambda: self._ui(self.quit),
                autostart_checked=cfgtool.get_autostart,
            )
            if not self.tray.start():
                self.tray = None
                log("托盘图标创建失败")
        except Exception as e:
            log("托盘初始化异常: %r" % (e,))
            self.tray = None

    def _tray_toggle_autostart(self):
        cfgtool.set_autostart(not cfgtool.get_autostart(), silent=True)
        self.var_autostart.set(cfgtool.get_autostart())
        self._save_prefs()

    def _ui(self, fn, *a):
        """把来自其它线程的调用切回 Tk 主线程（由托盘线程调用）。"""
        if self._closing:
            return
        try:
            self.cmdq.put((fn, a))
        except Exception:
            pass

    def show_window(self):
        self._apply_cfg_to_ui()
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.root.attributes("-topmost", True)
        self.root.after(300, lambda: self.root.attributes("-topmost", False))

    def open_settings(self):
        w = tk.Toplevel(self.root)
        w.title("设置")
        w.resizable(False, False)
        w.transient(self.root)
        w.configure(bg="#ffffff")
        try:
            w.iconbitmap(self.root.iconbitmap())
        except Exception:
            pass
        f = ttk.Frame(w, style="Card.TFrame", padding=16)
        f.pack(fill="both", expand=True)

        lv = {k: tk.StringVar(value=str(self.cfg.get(k, d)))
              for k, d in cfgtool.DEFAULTS.items()
              if k in ("check_sec", "idle_sec", "traffic_sec", "reconnect")}

        rows = [
            ("探活周期（秒）", "check_sec",
             "每隔多久检查一次网络是否还通，建议 45，最小 30"),
            ("空闲阈值（秒）", "idle_sec",
             "本机连续多少秒没有流量后才补发保活流量，避免多余流量"),
            ("保活周期（秒）", "traffic_sec",
             "读不到网卡统计时，按这个周期补流量"),
        ]
        for i, (label, key, tip) in enumerate(rows):
            ttk.Label(f, text=label, style="Card.TLabel").grid(row=i, column=0, sticky="w", pady=4)
            ttk.Entry(f, textvariable=lv[key], width=8).grid(row=i, column=1, sticky="w", padx=8)
            ttk.Label(f, text=tip, style="Dim.TLabel", wraplength=260,
                      justify="left").grid(row=i, column=2, sticky="w")

        self.var_startwin = tk.BooleanVar(value=not as_bool(self.cfg.get("silent_start", "1")))
        ttk.Checkbutton(f, text="开机自启时显示主窗口（不勾选＝静默后台运行）",
                        variable=self.var_startwin).grid(row=len(rows), column=0,
                                                         columnspan=3, sticky="w", pady=(8, 0))

        info = ("配置目录：%s\n配置文件里的密码只以密文存在 secret.bin，"
                "由 Windows DPAPI 按当前用户加密。" % cfgtool.data_dir())
        ttk.Label(f, text=info, style="Dim.TLabel", wraplength=400,
                  justify="left").grid(row=len(rows) + 1, column=0, columnspan=3,
                                       sticky="w", pady=(10, 0))

        def ok():
            for k, v in lv.items():
                try:
                    iv = int(v.get())
                    if k == "check_sec":
                        iv = max(30, iv)
                    elif k == "idle_sec":
                        iv = max(30, iv)
                    elif k == "traffic_sec":
                        iv = max(60, iv)
                    self.cfg[k] = str(iv)
                    v.set(str(iv))
                except ValueError:
                    v.set(str(cfgtool.DEFAULTS[k]))
                    self.cfg[k] = str(cfgtool.DEFAULTS[k])
            self.cfg["silent_start"] = "0" if self.var_startwin.get() else "1"
            cfgtool.save(self.cfg)
            self.worker.update_cfg(self.cfg)
            if cfgtool.get_autostart():
                cfgtool.set_autostart(True, silent=as_bool(self.cfg["silent_start"]))
            self.set_msg("设置已保存")
            w.destroy()

        btns = ttk.Frame(f, style="Card.TFrame")
        btns.grid(row=len(rows) + 2, column=0, columnspan=3, sticky="e", pady=(14, 0))
        ttk.Button(btns, text="打开配置目录",
                   command=lambda: os.startfile(cfgtool.data_dir())).pack(side="left", padx=4)
        ttk.Button(btns, text="保存", command=ok).pack(side="left", padx=4)
        ttk.Button(btns, text="取消", command=w.destroy).pack(side="left")
        w.update_idletasks()
        px, py = self.root.winfo_x(), self.root.winfo_y()
        w.geometry("+%d+%d" % (px + 20, py + 80))

    # ---------------- 事件泵 ----------------
    def _emit_from_worker(self, kind, *payload):
        try:
            self.evq.put((kind, payload))
        except Exception:
            pass

    def _pump(self):
        """每 250ms 取一次后台事件，避免线程直接碰 Tk。"""
        try:
            while True:
                try:
                    fn, a = self.cmdq.get_nowait()
                except queue.Empty:
                    fn = None
                if fn is not None:
                    try:
                        fn(*a)
                    except Exception as e:
                        log("托盘命令执行失败: %r" % (e,))
                    continue
                kind, payload = self.evq.get_nowait()
                if kind == "state":
                    self._render_state(payload[0], payload[1] if len(payload) > 1 else "")
                elif kind == "log":
                    self.set_msg(payload[0])
        except queue.Empty:
            pass
        except Exception:
            pass
        if not self._closing:
            self.root.after(250, self._pump)

    def _render_state(self, state, detail=""):
        text, color = STATE_STYLE.get(state, STATE_STYLE["idle"])
        try:
            self.lbl_state.configure(text=text, foreground=color)
            self.btn_conn.configure(
                state="disabled" if state == "connecting" else "normal")
        except Exception:
            pass
        if self.tray:
            self.tray.set_tooltip("%s - %s" % (APP_TITLE, text))
        if detail:
            self.set_msg(detail)

    def set_msg(self, text: str):
        try:
            self.lbl_msg.configure(text=text[:200])
        except Exception:
            pass

    def _tick(self):
        """每秒刷新一次“已连接时长”。"""
        if self._closing:
            return
        try:
            if self.worker.is_online():
                self._since = getattr(self, "_since", time.time())
                s = int(time.time() - self._since)
                self.lbl_up.configure(
                    text="在线 %02d:%02d:%02d" % (s // 3600, s % 3600 // 60, s % 60))
            else:
                self._since = time.time()
                self.lbl_up.configure(text="")
        except Exception:
            pass
        self.root.after(1000, self._tick)

    # ---------------- 生命周期 ----------------
    def on_close(self):
        """点 × 只隐藏窗口，程序继续在后台保持认证。"""
        self.root.withdraw()
        if not as_bool(self.cfg.get("close_tip_shown", "0")):
            self.cfg["close_tip_shown"] = "1"
            cfgtool.save(self.cfg)

    def quit(self):
        if self._closing:
            return
        self._closing = True
        try:
            self._save_prefs()
        except Exception:
            pass
        try:
            self.worker.stop()
        except Exception:
            pass
        try:
            if self.tray:
                self.tray.stop()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        self.root.mainloop()


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def already_running() -> bool:
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW(None, False, "Global\\CampusNetPortal_SingleInstance")
        return kernel32.GetLastError() == 183       # ERROR_ALREADY_EXISTS
    except Exception:
        return False


def main():
    args = [a.lower() for a in sys.argv[1:]]
    if "--version" in args or "-v" in args:
        print("%s v%s" % (APP_TITLE, VERSION))
        return
    silent = "--silent" in args
    if already_running():
        log("已有实例在运行，本次退出")
        return

    cfg = cfgtool.load()
    if as_bool(cfg.get("autostart", "0")):
        # 修正注册表里的启动命令（换路径 / 换静默设置后仍能生效）
        cfgtool.set_autostart(True, silent=as_bool(cfg.get("silent_start", "1")))
    if silent and not as_bool(cfg.get("silent_start", "1")):
        silent = False

    app = App(silent=silent)
    log("启动 (silent=%s, v%s)" % (silent, VERSION))
    app.run()


if __name__ == "__main__":
    main()
