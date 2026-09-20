#!/bin/bash
# 在 Linux（Debian/Ubuntu）上构建单文件可执行程序
#
# 用法:
#     ./build_linux.sh
#
# 依赖:
#     sudo apt install python3 python3-tk python3-venv
#     pip install pyinstaller requests
#
# 产物:
#     dist/校园网自动认证        可执行文件
#     dist/校园网自动认证.desktop  桌面快捷方式（可选）
set -e

cd "$(dirname "$0")"

echo "[1/4] 检查依赖"
if ! command -v python3 >/dev/null; then
  echo "  缺少 python3，请先 sudo apt install python3 python3-tk python3-venv"
  exit 1
fi
if ! python3 -c "import tkinter" 2>/dev/null; then
  echo "  缺少 tkinter，请先 sudo apt install python3-tk"
  exit 1
fi
if ! python3 -c "import PyInstaller" 2>/dev/null; then
  echo "  缺少 PyInstaller，请先 pip install pyinstaller"
  exit 1
fi
python3 -c "import requests" 2>/dev/null || {
  echo "  缺少 requests，请先 pip install requests"; exit 1; }

echo "[2/4] 生成图标"
python3 - <<'PY'
import iconart
for size, name in ((256, "net.png"), (64, "icon64.png")):
    ok = iconart.write_png(name, size)
    print("   %s: %s" % (name, "OK" if ok else "失败"))
PY

echo "[3/4] PyInstaller 打包（首次约 1-3 分钟）"
rm -rf build "dist/校园网自动认证" "dist/校园网自动认证.desktop" dist/CampusNetAutoLogin
python3 -m PyInstaller --clean --noconfirm build.spec

BUILT="dist/CampusNetAutoLogin"
if [ ! -f "$BUILT" ]; then
  echo "  打包失败：找不到 $BUILT"
  exit 1
fi
mv "$BUILT" "dist/校园网自动认证"
chmod +x "dist/校园网自动认证"

echo "[4/4] 生成 .desktop 与图标"
cp net.png dist/net.png
cat > "dist/校园网自动认证.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=校园网自动认证
Name[en]=SNNU Campus Net Portal
Comment=陕西师范大学校园网自动认证（图形界面 / 开机自启 / 防掉线保活）
Exec=$(pwd)/dist/校园网自动认证
Icon=$(pwd)/dist/net.png
Terminal=false
Categories=Network;Utility;
Keywords=campus;network;portal;snnu;
EOF

SIZE=$(du -h "dist/校园网自动认证" | cut -f1)
echo
echo "完成：dist/校园网自动认证  ($SIZE)"
echo "       dist/校园网自动认证.desktop"
echo "直接运行： ./dist/校园网自动认证"
echo "安装到本用户： ./install_linux.sh"
