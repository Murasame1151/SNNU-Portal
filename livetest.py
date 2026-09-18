# -*- coding: utf-8 -*-
"""真实 portal 联调自检：注销 / 错误账号 / 正确登录 / 状态 / 保活 / 重连。

用法:
    python livetest.py <账号> [密码] [运营商]

运营商可选 mobile / unicom / telecom，留空表示校园网不代拨。
**需要在校园网内运行**，且会真实地把你当前这条连接注销再重新认证。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import portal

if len(sys.argv) < 2:
    print(__doc__)
    print("错误：必须提供账号，例如  python livetest.py 你的学号 你的密码 mobile")
    sys.exit(2)

ACC = sys.argv[1]
PWD = sys.argv[2] if len(sys.argv) > 2 else ""
CARRIER = sys.argv[3] if len(sys.argv) > 3 else "mobile"

failures = []


def show(text):
    print("   " + text)


def check(name, cond):
    print("%-34s %s" % (name, "PASS" if cond else "FAIL"))
    if not cond:
        failures.append(name)


show("账号 %s / 运营商 %s（密码不回显）" % (ACC, CARRIER or "校园网"))

print("== 1. 注销到未登录状态")
c0 = portal.PortalClient(ACC, PWD, CARRIER)
c0.logout()
time.sleep(1)
check("注销后 portal_status 为 False", c0.portal_status() is False)

print("== 2. 用不存在的账号登录（应失败）")
bad = portal.PortalClient("00000000", "x", CARRIER)
ok = bad.login()
show("login=%s  msg=%s" % (ok, bad.last_message))
check("不存在的账号登录失败", ok is False)

print("== 3. 用真实账号登录（应成功）")
c = portal.PortalClient(ACC, PWD, CARRIER)
t0 = time.time()
ok = c.login()
show("login=%s  %.2fs  msg=%s" % (ok, time.time() - t0, c.last_message))
check("真实账号登录成功", ok is True)

print("== 4. portal_status（应 True，且账号对得上）")
check("portal_status 为 True", c.portal_status() is True)
show("msg=%s" % c.last_message)

print("== 5. 重复登录（应幂等）")
check("重复登录仍成功", c.login() is True)

print("== 6. 保活流量")
check("keepalive 成功", c.keepalive() is True)

print("== 7. 注销（应回到未登录）")
c.logout()
time.sleep(1)
check("注销后状态为 False", c.portal_status() is False)

print("== 8. 注销后再登录（模拟掉线重连）")
ok = c.login()
show("relogin=%s  msg=%s" % (ok, c.last_message))
check("重连成功", ok is True)

print()
if failures:
    print("LIVE TEST: %d 项失败 -> %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("LIVE TEST: ALL PASS")
