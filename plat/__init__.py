# -*- coding: utf-8 -*-
"""按平台分发的实现模块。

    win_impl.py   Windows：DPAPI 密码保存、注册表开机自启、GetIfTable2、命名互斥量
    lin_impl.py   Linux  ：keyring/0600 密码保存、systemd 用户服务、/proc/net/dev、flock

`cfgtool.py` 与 `portal.py` 会在导入时按 `sys.platform` 选择其中一个，
所以本包在任一平台上只会用到对应那一个模块。
"""
