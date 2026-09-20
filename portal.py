# -*- coding: utf-8 -*-
"""校园网 Portal 认证核心（纯 requests，无其它依赖）。

由原 net.py 改写：
    登录  POST http://202.117.144.205:8602/snnuportal/login
    注销  POST http://202.117.144.205:8602/snnuportal/logoff
表单字段 sourceurl / account / password / yys / issave 保持不变。
"""
from __future__ import annotations

import re
import sys
import time

import requests

PORTAL_IP = "202.117.144.205:8602"
BASE = "http://" + PORTAL_IP + "/snnuportal"
LOGIN_URL = BASE + "/login"
LOGOFF_URL = BASE + "/logoff"

CARRIERS = [
    ("移动", "mobile"),
    ("联通", "unicom"),
    ("电信", "telecom"),
    ("校园网（不代拨）", ""),
]

# 探活目标：国内可达、响应极小
PROBE_URLS = (
    "http://www.msftconnecttest.com/connecttest.txt",
    "http://connect.rom.miui.com/generate_204",
    "http://www.baidu.com/robots.txt",
)

TIMEOUT = 6

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 Edg/134.0.0.0")

# 出现这些词说明这次认证被 portal 拒了（密码错 / 账号错 / 欠费等）
_FAIL_WORDS = ("登录失败", "认证失败", "密码错误", "密码不正确",
               "用户不存在", "账号不存在", "已欠费", "停机")

# 该 portal 的“已认证”标志：userstatus.jsp 会输出
#   当前登录账号： <span ...>学号@mobile</span>
_RE_LOGGED_ACCOUNT = re.compile(r"当前登录账号[^0-9A-Za-z]{0,40}([0-9A-Za-z@._\-]{3,})")
_RE_LOGGED_SPAN = re.compile(r"当前登录账号：\s*<span[^>]*>\s*([^<]*)</span>")


def _session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False           # 忽略系统代理，避免认证请求被代理吞掉
    s.headers.update({
        "accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                   "image/avif,image/webp,image/apng,*/*;q=0.8"),
        "accept-encoding": "gzip, deflate",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "connection": "keep-alive",
        "content-type": "application/x-www-form-urlencoded",
        "host": PORTAL_IP,
        "origin": "http://" + PORTAL_IP,
        "referer": LOGOFF_URL,
        "upgrade-insecure-requests": "1",
        "user-agent": UA,
    })
    return s


_SESSION = _session()


def _text(resp: requests.Response) -> str:
    """按响应头里的 charset 解码；该 portal 用的是 GB2312。"""
    try:
        raw = resp.content
    except Exception:
        return ""
    charset = ""
    try:
        charset = (resp.encoding or "")
    except Exception:
        pass
    order = []
    if charset:
        order.append(charset)
    order += ["utf-8", "gb18030", "gbk"]
    for enc in order:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("gb18030", "replace")


def _extract_account(body: str) -> str:
    """从 userstatus.jsp 里取出“当前登录账号”，未登录返回空串。"""
    m = _RE_LOGGED_SPAN.search(body)
    if m:
        return m.group(1).strip()
    m = _RE_LOGGED_ACCOUNT.search(body)
    return m.group(1).strip() if m else ""


def _has_login_form(body: str) -> bool:
    low = body.lower()
    return ("name=\"password\"" in low or "name='password'" in low
            or "name=password" in low or "name=\"account\"" in low
            or "name='account'" in low)


class PortalClient:
    """一次实例对应一个账号，内部复用一个 HTTP 连接池。"""

    def __init__(self, account: str, password: str, carrier: str = "mobile"):
        self.account = account
        self.password = password
        self.carrier = carrier or ""
        self.last_message = ""
        self.connected = False

    # ---------------- 认证 ----------------
    def login(self) -> bool:
        """提交认证。

        判定规则（在真实 portal 上反复实测确认，2026-09）：
          * 本 portal **会校验密码**。用错误密码登录会返回登录页并提示
            “登录失败”，且事后 `userstatus.jsp` 里没有登录账号；
          * 账号不存在同样是“登录失败”；
          * 密码正确时才返回 `userstatus.jsp`，并显示
            “当前登录账号：<账号>@<运营商>”。
        因此成功判据是“响应里出现与本账号一致的登录账号”。

        注意两个坑：
          1. 这个字段是**绑定在本机 IP 上**的，不是绑定在客户端 cookie 上。
             所以只要这台机器当前在线，随便访问一个页面都会看到它——
             不能只看“页面里有没有账号”，必须结合本次 POST 的响应判断。
          2. 不能用外部网站连通性判断是否认证成功：认证成功前外部探测
             往往全是失败的，用它会把成功误判成失败。
        """
        if not self.account:
            self.last_message = "账号为空"
            self.connected = False
            return False

        # 已经用这个账号在线就不要折腾：先问 portal 一句。
        # （每次开机都先注销再登录会在已经在线时白白断一次网。）
        if self.portal_status():
            return True

        # 再注销，清掉 portal 里可能残留的旧会话（沿用原脚本行为）
        try:
            _SESSION.post(LOGOFF_URL, timeout=TIMEOUT)
        except requests.RequestException:
            pass

        return self._submit()

    def _submit(self) -> bool:
        data = {
            "sourceurl": "null",
            "account": self.account,
            "password": self.password,
            "yys": self.carrier,
            "issave": "",
        }
        try:
            resp = _SESSION.post(LOGIN_URL, data=data, timeout=TIMEOUT,
                                 allow_redirects=True)
        except requests.RequestException as e:
            self.last_message = ("无法连接认证服务器（%s）- 请确认已连上校园网"
                                 % type(e).__name__)
            self.connected = False
            return False

        body = _text(resp)
        shown = _extract_account(body)
        rejected = _has_login_form(body) or any(w in body for w in _FAIL_WORDS)

        # 1) 明确被拒：返回了登录表单 / 提示登录失败
        if rejected:
            self.connected = False
            self.last_message = self._reject_reason(body)
            return False

        # 2) 成功：页面里出现了本账号
        if shown and self._account_matches(shown):
            self.connected = True
            self.last_message = "当前登录账号：%s" % shown
            return True

        # 3) 没被拒，但也没看到本账号
        self.connected = False
        if shown:
            self.last_message = "本机 IP 当前绑定的是 %s，未认证为 %s" % (shown, self.account)
        else:
            page = (resp.url or "").rsplit("/", 1)[-1] or "?"
            self.last_message = ("portal 返回 %s（HTTP %d），未看到已登录信息"
                                 % (page, resp.status_code))
        return False

    def _account_matches(self, shown: str) -> bool:
        shown_id = shown.split("@", 1)[0].strip().lower()
        want = self.account.strip().lower()
        return bool(shown_id) and shown_id == want

    @staticmethod
    def _reject_reason(body: str) -> str:
        """把 portal 的拒绝原因翻译成人话，方便用户判断是密码错还是账号错。"""
        for w in ("密码错误", "密码不正确"):
            if w in body:
                return "认证被拒：密码错误"
        for w in ("用户不存在", "账号不存在", "无此用户"):
            if w in body:
                return "认证被拒：账号不存在"
        for w in ("已欠费", "停机", "余额不足"):
            if w in body:
                return "认证被拒：账号已欠费/停机"
        if "登录失败" in body:
            return "认证被拒：登录失败（账号或密码不正确，或该账号已在线）"
        return "认证被拒：portal 返回了登录页"

    def logout(self) -> bool:
        try:
            _SESSION.post(LOGOFF_URL, timeout=TIMEOUT)
            self.connected = False
            self.last_message = "已断开连接"
            return True
        except requests.RequestException as e:
            self.last_message = "断开失败 (%s)" % type(e).__name__
            return False

    # ---------------- portal 状态探活 ----------------
    def portal_status(self, should_stop=None) -> bool:
        """向 portal 自己问一次“我现在是谁”——这是判断掉线最可靠的办法。

        顺便这也是极小的一次 HTTP 交互，等价于给 portal 会话续期。
        """
        if should_stop is not None and should_stop():
            return self.connected
        try:
            resp = _SESSION.get(BASE + "/userstatus.jsp", timeout=TIMEOUT,
                                allow_redirects=True)
        except requests.RequestException:
            # portal 都连不上，保持现状，避免误判为掉线后疯狂重连
            return self.connected
        body = _text(resp)
        shown = _extract_account(body)
        ok = bool(shown) and self._account_matches(shown)
        self.connected = ok
        if shown:
            self.last_message = "当前登录账号：%s" % shown
        return ok

    # ---------------- 外网探活（判断“有没有真正放行外网”） ----------------
    def probe(self, should_stop=None) -> bool:
        """请求一个极小文件；被 portal 劫持时返回 200 但内容不符，判为离线。

        判定原则：只有拿到“预期内容”才算通，其余一律当被劫持，
        因为很多 portal 不返回 302，而是直接返回登录页（HTTP 200）。
        should_stop: 每试一个地址前调用，返回 True 立即放弃（例如用户点了“连接”）。
        """
        for url in PROBE_URLS:
            if should_stop is not None and should_stop():
                return self.connected
            try:
                r = _SESSION.get(url, timeout=TIMEOUT, allow_redirects=False)
            except requests.RequestException:
                continue
            if r.status_code == 204:
                return True
            if r.status_code != 200:
                continue          # 302 到登录页 = 被劫持
            body = _text(r).strip()
            low = body[:2048].lower()
            if "connecttest.txt" in url:
                if "microsoft connect test" in low:
                    return True
                continue
            if "generate_204" in url:
                if not low or low == "ok":
                    return True
                continue
            if "baidu" in url:
                if "baidu" in low:
                    return True
                continue
            # 未知目标：空响应体视为通，HTML 一律视为被劫持
            if low and ("<html" in low or "<script" in low or "portal" in low):
                continue
            return True
        return False

    # ---------------- 保活 ----------------
    def keepalive(self, should_stop=None) -> bool:
        """补一次极小的应用层流量，防止“长时间无流量”被踢。

        流量本身就是一次普通 HTTP GET：既产生收发字节，也让 NAT / portal
        的会话计时器看到活跃连接。失败不代表掉线，交给探活去判断。
        """
        for url in PROBE_URLS:
            if should_stop is not None and should_stop():
                return True
            try:
                r = _SESSION.get(url, timeout=TIMEOUT, allow_redirects=False)
                if r.status_code < 500:
                    return True
            except requests.RequestException:
                continue
        # 外网全不通时，至少和 portal 本身保持一次交互
        try:
            _SESSION.get(BASE + "/", timeout=TIMEOUT)
            return True
        except requests.RequestException:
            return False


# --------------------------------------------------------------------------- #
# 本机网卡流量统计（判断“是否真的长时间没流量”，只读，几乎零开销）
#
# 实现按平台放在 plat/ 下：
#   Windows -> GetIfTable2（按 IF_HARDWARE 位只取物理网卡）
#   Linux   -> /proc/net/dev（跳过 lo / docker / veth 等虚拟接口）
# 这里只做转发，方便测试时替换。
# --------------------------------------------------------------------------- #
if sys.platform == "win32":
    import plat.win_impl as _netimpl
else:
    import plat.lin_impl as _netimpl


def net_bytes() -> int:
    """返回本机物理网卡累计收发的字节数；读取失败返回 -1。

    用来判断“最近是否真的没有网络流量”——有流量就不必补流量，
    从而把保活开销降到接近 0。
    """
    try:
        return _netimpl.net_bytes()
    except Exception:
        return -1
