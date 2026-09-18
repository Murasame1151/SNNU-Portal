# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：单文件、无控制台窗口、带图标。

    pyinstaller --clean --noconfirm build.spec
"""
import os

block_cipher = None

# 排除用不到的大模块，显著减小体积。
# 注意：不要排除 ssl / http / email / base64 等，requests 会用到。
EXCLUDES = [
    "numpy", "pandas", "scipy", "matplotlib", "PyQt5", "PySide2", "PySide6",
    "IPython", "jupyter", "notebook", "setuptools", "pip", "wheel",
    "pydoc", "doctest", "unittest", "pdb", "lib2to3", "distutils",
    "curses", "sqlite3", "tkinter.test", "test",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("net.ico", ".")] if os.path.exists("net.ico") else [],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="CampusNetAutoLogin",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # UPX 压缩容易被杀软误报，关闭
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,             # 无黑色控制台窗口
    disable_windowed_traceback=False,
    icon="net.ico" if os.path.exists("net.ico") else None,
    version=None,
)
