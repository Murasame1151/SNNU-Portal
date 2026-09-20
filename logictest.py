# -*- coding: utf-8 -*-
"""离线自检：不需要校园网。

    python logictest.py

覆盖 DPAPI 加解密、配置读写、在线判定逻辑、网卡流量统计、
注册表开机自启、单实例互斥量。测试数据写在临时目录，不碰真实配置。
"""
import ctypes
import os
import shutil
import stat
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# 隔离配置目录（必须在 import cfgtool 之前设好环境变量）
TEST_DIR = os.path.join(tempfile.gettempdir(), "CampusNetPortal_logictest")
shutil.rmtree(TEST_DIR, ignore_errors=True)
os.environ["CAMPUSNET_DATA_DIR"] = TEST_DIR

import cfgtool      # noqa: E402
import portal       # noqa: E402

failures = []


def check(name, cond, extra=""):
    print("%-36s %s %s" % (name, "PASS" if cond else "FAIL", extra))
    if not cond:
        failures.append(name)


# --------------------------------------------------------------------------- #
# DPAPI
# --------------------------------------------------------------------------- #
SECRET = "P@ssw0rd-中文-123"
cfgtool.save_password(SECRET)
check("DPAPI 加密后能原样解回", cfgtool.load_password() == SECRET)

raw = open(os.path.join(TEST_DIR, "secret.bin"), "rb").read()
check("密文里不含明文密码", b"P@ssw0rd" not in raw and "中文".encode() not in raw,
      "%d bytes" % len(raw))
check("配置目录被隔离到临时目录",
      os.path.abspath(cfgtool.data_dir()) == os.path.abspath(TEST_DIR))

# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
cfg = cfgtool.load()
cfg["account"] = "12345678"
cfg["carrier"] = "unicom"
cfg["remember"] = "1"
cfg["password"] = cfgtool.load_password()
cfgtool.save(cfg)

cfg2 = cfgtool.load()
check("配置能正确读回", cfg2["account"] == "12345678" and cfg2["carrier"] == "unicom")
check("remember=1 时自动带出密码", cfg2["password"] == SECRET)

cfg2["remember"] = "0"
cfgtool.save(cfg2)
check("remember=0 时不下发密码", cfgtool.load()["password"] == "")

# --------------------------------------------------------------------------- #
# 在线判定逻辑
# --------------------------------------------------------------------------- #
class FakeResp:
    def __init__(self, code, body=b"", url=portal.BASE + "/"):
        self.status_code = code
        self.content = body
        self.url = url
        self.encoding = "gb18030"


class FakeSession:
    """连续返回同一响应，并记录被调用次数。"""

    def __init__(self, resp):
        self.resp = resp
        self.calls = 0

    def get(self, url, **kw):
        self.calls += 1
        return self.resp

    def post(self, url, **kw):
        self.calls += 1
        return self.resp


REAL = portal._SESSION
client = portal.PortalClient("12345678", "pw", "mobile")

portal._SESSION = FakeSession(FakeResp(204))
check("204 -> 在线", client.probe() is True)

portal._SESSION = FakeSession(FakeResp(200, b"Microsoft Connect Test\r\n"))
check("connecttest 正确内容 -> 在线", client.probe() is True)

portal._SESSION = FakeSession(FakeResp(200, b"<html>portal login</html>"))
check("被 portal 劫持(HTML 200) -> 离线", client.probe() is False)

portal._SESSION = FakeSession(FakeResp(302, b""))
check("302 跳登录页 -> 离线", client.probe() is False)

# “当前登录账号”解析
STATUS_HTML = (
    '<td>当前登录账号：<span class="zhengwen1">12345678@mobile</span></td>'.encode("gb18030")
)
portal._SESSION = FakeSession(FakeResp(200, STATUS_HTML,
                                       portal.BASE + "/userstatus.jsp"))
check("userstatus 显示本人账号 -> 已登录", client.portal_status() is True)

OTHER_HTML = (
    '<td>当前登录账号：<span>99999999@mobile</span></td>'.encode("gb18030")
)
portal._SESSION = FakeSession(FakeResp(200, OTHER_HTML))
check("userstatus 显示他人账号 -> 未登录", client.portal_status() is False)

LOGIN_HTML = ('<form><input name="account"><input name="password"></form>'
              .encode("gb18030"))
portal._SESSION = FakeSession(FakeResp(200, LOGIN_HTML, portal.LOGIN_URL))
check("返回登录表单 -> 判定为未登录", client.portal_status() is False)

# 认证被拒：错误密码 / 账号不存在，都应返回 False 并给出人话提示
REJECT_HTML = ('<form><input name="account"><input name="password"></form>'
               '<script>alert("登录失败")</script>').encode("gb18030")
portal._SESSION = FakeSession(FakeResp(200, REJECT_HTML, portal.LOGIN_URL))
check("错误密码 -> login() 返回 False", client.login() is False)
check("错误密码 -> 提示“登录失败”", "登录失败" in client.last_message,
      client.last_message)

WRONGPWD_HTML = ('<form><input name="account"><input name="password"></form>'
                 '密码错误').encode("gb18030")
portal._SESSION = FakeSession(FakeResp(200, WRONGPWD_HTML, portal.LOGIN_URL))
check("密码错误 -> 提示“密码错误”", client.login() is False
      and client.last_message == "认证被拒：密码错误", client.last_message)

NOUSER_HTML = ('<form><input name="account"></form>用户不存在').encode("gb18030")
portal._SESSION = FakeSession(FakeResp(200, NOUSER_HTML, portal.LOGIN_URL))
check("账号不存在 -> 提示“账号不存在”", client.login() is False
      and "账号不存在" in client.last_message, client.last_message)

# 成功：响应里带本账号
OK_HTML = ('<td>当前登录账号：<span>12345678@mobile</span></td>'
           ).encode("gb18030")
portal._SESSION = FakeSession(FakeResp(200, OK_HTML,
                                       portal.BASE + "/userstatus.jsp"))
check("密码正确 -> login() 返回 True", client.login() is True)
check("密码正确 -> 带出登录账号", client.last_message == "当前登录账号：12345678@mobile",
      client.last_message)

# 编码：GB2312 页面必须能正确解出中文
gb = '<span>当前登录账号：<span>12345678@unicom</span></span>'.encode("gb18030")
portal._SESSION = FakeSession(FakeResp(200, gb))
c2 = portal.PortalClient("12345678", "pw", "unicom")
check("GB2312 页面中文解码正确", c2.portal_status() is True, c2.last_message)

# should_stop：用户点了“连接”时应立刻让路，不再发请求
s = FakeSession(FakeResp(200, b"x"))
portal._SESSION = s
client.connected = False        # 起始状态明确为“未知/离线”，避免依赖上一步结果
check("should_stop 立刻返回", client.probe(should_stop=lambda: True) is False)
check("should_stop 时没有发请求", s.calls == 0)

portal._SESSION = FakeSession(FakeResp(200, b"ok"))
check("keepalive 成功", client.keepalive() is True)

# --------------------------------------------------------------------------- #
# 网卡流量统计
# --------------------------------------------------------------------------- #
b1 = portal.net_bytes()
check("net_bytes 可读", b1 >= 0, str(b1))

if sys.platform == "win32":
    import plat.win_impl as netimpl
    check("MIB_IF_ROW2 结构体尺寸正确", netimpl._MIB_IF_ROW2_SIZE == 1352,
          str(netimpl._MIB_IF_ROW2_SIZE))
    check("InOctets 偏移正确", netimpl._MIB_IF_ROW2.InOctets.offset == 1208)
else:
    # Linux：用一份合成的 /proc/net/dev 验证解析与虚拟接口过滤
    import unittest.mock as mock

    import plat.lin_impl as netimpl
    check("物理接口识别", netimpl._is_physical("eth0")
          and netimpl._is_physical("wlan0"))
    check("虚拟接口被排除", not any(netimpl._is_physical(x) for x in
                                    ("lo", "docker0", "veth123", "br-abc")))

    fake_dev = (
        "Inter-|   Receive                                                "
        "|  Transmit\n"
        " face |bytes    packets errs drop fifo frame compressed multicast"
        "|bytes    packets\n"
        "    lo: 1000000    1000    0    0    0     0          0         0"
        "  1000000    1000\n"
        "docker0:  999999     999    0    0    0     0          0         0"
        "   999999     999\n"
        "  eth0:    5000      50    0    0    0     0          0         0"
        "     7000      70\n"
        " wlan0:    3000      30    0    0    0     0          0         0"
        "     4000      40\n"
    )
    with mock.patch("builtins.open", mock.mock_open(read_data=fake_dev)):
        got = netimpl.net_bytes()
    # 只应统计 eth0(5000+7000) 与 wlan0(3000+4000) = 19000
    check("Linux 流量统计只算物理网卡", got == 19000, "得到 %s" % got)

# --------------------------------------------------------------------------- #
# 密码保存后端
# --------------------------------------------------------------------------- #
if sys.platform != "win32":
    cfgtool.save_password("linux-roundtrip-中文")
    check("Linux 密码可往返", cfgtool.load_password() == "linux-roundtrip-中文",
          cfgtool.secret_backend_name())
    if not cfgtool.secret_backend_name().startswith("系统 keyring"):
        mode = stat.S_IMODE(os.stat(cfgtool._secret_path()).st_mode)
        check("secret.bin 权限为 0600", mode == 0o600, oct(mode))

# --------------------------------------------------------------------------- #
# 开机自启：Windows 查注册表，Linux 查 systemd 用户服务
# --------------------------------------------------------------------------- #
if sys.platform == "win32":
    import winreg       # noqa: E402

    def read_run_value():
        """读当前 Run 项的值，不存在返回 None（用于测试后还原现场）。"""
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, cfgtool.RUN_KEY)
        except OSError:
            return None
        try:
            return winreg.QueryValueEx(k, cfgtool.RUN_NAME)[0]
        except OSError:
            return None
        finally:
            winreg.CloseKey(k)

    original = read_run_value()
    try:
        check("开启自启成功", cfgtool.set_autostart(True, silent=True)
              and cfgtool.get_autostart())
        check("启动命令带 --silent",
              "--silent" in (read_run_value() or ""), read_run_value() or "")
        check("关闭自启成功", cfgtool.set_autostart(False)
              and not cfgtool.get_autostart())
    finally:
        # 还原测试前的状态：原来有就写回原值，原来没有就保持删除
        if original is not None:
            cfgtool.set_autostart(True, silent=False)
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, cfgtool.RUN_KEY, 0,
                                 winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, cfgtool.RUN_NAME, 0, winreg.REG_SZ, original)
            winreg.CloseKey(key)
        else:
            cfgtool.set_autostart(False)
    check("自启状态已还原到测试前", read_run_value() == original,
          repr(original)[:60])

    # 单实例：Windows 用命名互斥量
    ctypes.windll.kernel32.CreateMutexW(
        None, False, "Global\\CampusNetPortal_SingleInstance")
    ctypes.windll.kernel32.CreateMutexW(
        None, False, "Global\\CampusNetPortal_SingleInstance")
    check("单实例互斥量生效", ctypes.windll.kernel32.GetLastError() == 183)
else:
    # Linux：自启写 systemd 用户服务，单实例用 flock
    import plat.lin_impl as lin
    unit = lin._unit_path()
    existed = os.path.exists(unit)
    original_unit = open(unit, encoding="utf-8").read() if existed else None
    try:
        cfgtool.set_autostart(True, silent=True)
        check("写入 systemd 服务文件", os.path.exists(unit), unit)
        body = open(unit, encoding="utf-8").read()
        check("服务含 --silent", "--silent" in body)
        check("服务含 WantedBy=default.target",
              "WantedBy=default.target" in body)
        cfgtool.set_autostart(False)
        check("关闭后服务文件被删除", not os.path.exists(unit))
    finally:
        if original_unit is not None:
            os.makedirs(os.path.dirname(unit), exist_ok=True)
            with open(unit, "w", encoding="utf-8") as f:
                f.write(original_unit)
        elif os.path.exists(unit):
            os.remove(unit)
    check("自启现场已还原", os.path.exists(unit) == existed)

    lockpath = os.path.join(TEST_DIR, "lock.test")
    check("首次加锁成功", lin.single_instance_lock(lockpath) is True)
    check("再次加锁被拒绝", lin.single_instance_lock(lockpath) is False)
    check("密码后端名称可读", bool(cfgtool.secret_backend_name()),
          cfgtool.secret_backend_name())

portal._SESSION = REAL
shutil.rmtree(TEST_DIR, ignore_errors=True)

print()
if failures:
    print("RESULT: %d 项失败 -> %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("RESULT: ALL PASS")
