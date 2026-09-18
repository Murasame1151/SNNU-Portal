# -*- coding: utf-8 -*-
"""一键打包脚本

    python build.py

产出: dist/CampusNetAutoLogin.exe（同时复制一份为“校园网自动认证.exe”）
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "CampusNetAutoLogin"
CN_NAME = "校园网自动认证.exe"


def main() -> int:
    os.chdir(HERE)

    # 1) 生成图标
    try:
        import trayicon
        if trayicon.make_ico(os.path.join(HERE, "net.ico")):
            print("[1/3] 已生成 net.ico")
        else:
            print("[1/3] 图标生成失败，继续（将使用系统默认图标）")
    except Exception as e:
        print("[1/3] 图标生成异常：%r" % (e,))

    # 2) 调用 PyInstaller
    print("[2/3] 正在打包，首次可能需要 1-3 分钟…")
    cmd = [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
           "build.spec"]
    rc = subprocess.call(cmd)
    if rc != 0:
        print("打包失败，退出码 %d" % rc)
        return rc

    src = os.path.join(HERE, "dist", NAME + ".exe")
    if not os.path.exists(src):
        print("没有找到产物：%s" % src)
        return 1
    dst = os.path.join(HERE, "dist", CN_NAME)
    try:
        shutil.copyfile(src, dst)
    except OSError as e:
        print("复制中文名副本失败：%r" % (e,))

    size = os.path.getsize(src) / 1024.0 / 1024.0
    print("[3/3] 完成：%s  (%.1f MB)" % (src, size))
    print("      中文名副本：%s" % dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
