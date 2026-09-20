# -*- coding: utf-8 -*-
"""程序图标：纯标准库生成 PNG / ICO，不依赖 Pillow。

Windows 用 ICO（exe 图标 + 托盘），Linux 用 PNG（.desktop 图标）。
图形按“相对尺寸”绘制，所以 16px 到 256px 都是同一套比例，
不会出现小尺寸图案错位的问题。
"""
from __future__ import annotations

import struct
import zlib

# 图形比例（相对图标边长）
_BAR_Y = (0.36, 0.52, 0.68)      # 三条横杠的纵向位置
_BAR_FRAC = (0.95, 0.70, 0.45)   # 各自的长度
_BAR_H = 0.085                   # 粗细
_BAR_X = 0.20                    # 起点（左边距）


def icon_pixels(size: int = 64):
    """返回 size×size 的 RGBA 行列表：蓝色圆底 + 白色三条横杠。"""
    size = max(8, int(size))
    cx = cy = (size - 1) / 2.0
    r = size / 2.0 - 1
    bar_h = max(1.0, size * _BAR_H)
    bar_x0 = size * _BAR_X
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            dx, dy = x - cx, y - cy
            d = (dx * dx + dy * dy) ** 0.5
            if d > r:
                row += b"\x00\x00\x00\x00"
                continue
            # 圆内：自上而下的蓝色渐变
            t = y / max(size - 1, 1)
            rr = int(0x2E + t * 0x0A)
            gg = int(0x86 + t * 0x30)
            bb = int(0xF0 + t * 0x0F)
            a = 255
            if d > r - max(1.0, size / 40.0):      # 边缘一圈抗锯齿
                a = int(255 * (r - d) / max(1.0, size / 40.0))
            # 中部三条白色横杠，长度递减，像信号/网速
            for i, by in enumerate(_BAR_Y):
                if abs(y - by * size) < bar_h / 2:
                    if bar_x0 <= x <= bar_x0 + (size - 2 * bar_x0) * _BAR_FRAC[i]:
                        rr = gg = bb = 0xFF
                        break
            row += bytes((rr, gg, bb, max(0, min(255, a))))
        rows.append(row)
    return rows


def to_png(px) -> bytes:
    """把 icon_pixels() 的结果编码成 PNG 字节。"""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    h = len(px)
    w = len(px[0]) // 4
    raw = b"".join(bytes([0]) + bytes(px[y]) for y in range(h))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def write_png(path: str, size: int = 256) -> bool:
    try:
        with open(path, "wb") as f:
            f.write(to_png(icon_pixels(size)))
        return True
    except Exception:
        return False


def _bmp_entry(px) -> bytes:
    """ICO 里的 32bpp BMP 条目：BITMAPINFOHEADER(高度×2) + BGRA 倒序 + AND 掩码。"""
    h = len(px)
    w = len(px[0]) // 4
    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    xor = bytearray()
    for y in range(h - 1, -1, -1):          # BMP 自下而上
        row = px[y]
        for x in range(w):
            r, g, b, a = row[x * 4], row[x * 4 + 1], row[x * 4 + 2], row[x * 4 + 3]
            xor += bytes((b, g, r, a))
    and_stride = ((w + 31) // 32) * 4
    return header + bytes(xor) + b"\x00" * (and_stride * h)


def make_ico(path: str) -> bool:
    """生成多尺寸 ICO（16/24/32/48/64 用 BMP，256 用 PNG）。"""
    try:
        sizes = (16, 24, 32, 48, 64, 256)
        entries = []
        for s in sizes:
            px = icon_pixels(s)
            entries.append((s, to_png(px) if s >= 256 else _bmp_entry(px)))

        header = struct.pack("<HHH", 0, 1, len(entries))
        offset = 6 + 16 * len(entries)
        dirs = bytearray()
        for (s, data) in entries:
            dim = 0 if s >= 256 else s
            dirs += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32,
                                len(data), offset)
            offset += len(data)
        with open(path, "wb") as f:
            f.write(header + bytes(dirs) + b"".join(d for _, d in entries))
        return True
    except Exception:
        return False
