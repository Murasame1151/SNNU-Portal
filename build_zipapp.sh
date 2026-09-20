#!/bin/bash
# 构建“便携版” Linux 分发包（.pyz）
#
# 与 build_linux.sh（PyInstaller 单文件）的区别：
#   * 不需要 PyInstaller，甚至可以在任何平台打包；
#   * 体积只有几十 KB；
#   * 运行需要系统里有 python3 和 python3-tk（Debian 上一条 apt 命令）。
#
# 用法:
#     ./build_zipapp.sh
# 产物:
#     dist/校园网自动认证.pyz     zipapp 本体（自带 shebang，可直接执行）
#     dist/校园网自动认证         启动器脚本（兼容任何 python3 版本）
#     dist/校园网自动认证.desktop 桌面菜单项
set -e

cd "$(dirname "$0")"
OUT="dist"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

echo "[1/3] 收集源码"
for f in main.py portal.py cfgtool.py trayicon.py iconart.py; do
  cp "$f" "$STAGE/"
done
mkdir -p "$STAGE/plat"
cp plat/__init__.py plat/win_impl.py plat/lin_impl.py "$STAGE/plat/"
printf 'from main import main\n\nmain()\n' > "$STAGE/__main__.py"
ls -1 "$STAGE" "$STAGE/plat" | sed 's/^/   /'

echo "[2/3] 打包 zipapp"
mkdir -p "$OUT"
python3 -m zipapp "$STAGE" -o "$OUT/校园网自动认证.pyz" -p "/usr/bin/env python3"
chmod +x "$OUT/校园网自动认证.pyz"

echo "[3/3] 生成启动器与桌面项"
cat > "$OUT/校园网自动认证" <<'EOF'
#!/bin/bash
# 启动器：明确用 python3 解释 zipapp，避免 shebang 与环境不一致
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
exec python3 "$DIR/校园网自动认证.pyz" "$@"
EOF
chmod +x "$OUT/校园网自动认证"

# 桌面文件里 Icon 用程序自带的图标（运行时生成到配置目录）
cat > "$OUT/校园网自动认证.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=校园网自动认证
Name[en]=SNNU Campus Net Portal
Comment=陕西师范大学校园网自动认证（图形界面 / 开机自启 / 防掉线保活）
Exec=$(pwd)/$OUT/校园网自动认证
Terminal=false
Categories=Network;Utility;
Keywords=campus;network;portal;snnu;
EOF

python3 -c "
import sys; sys.path.insert(0, '.')
import iconart; iconart.write_png('$OUT/net.png', 256)
print('   图标已生成')
" 2>/dev/null || echo "   （图标稍后由程序自己生成）"

echo
echo "完成："
ls -la "$OUT" | sed 's/^/   /'
echo
echo "运行： ./$OUT/校园网自动认证"
echo "依赖： sudo apt install python3 python3-tk"
