#!/bin/bash
# 把 Linux 版装到当前用户（不需要 root）
#
# 用法:
#     ./install_linux.sh            # 安装
#     ./install_linux.sh --uninstall
#
# 做的事:
#     1. 可执行文件 -> ~/.local/bin/校园网自动认证
#     2. 图标       -> ~/.local/share/icons/hicolor/256x256/apps/campus-net-portal.png
#     3. 菜单项     -> ~/.local/share/applications/campus-net-portal.desktop
#     4. 若程序尚未配置自启，提示你运行一次并在界面里勾选
set -e

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_SRC="$APP_DIR/dist/校园网自动认证"
BIN_DST="$HOME/.local/bin/校园网自动认证"
ICON_DST="$HOME/.local/share/icons/hicolor/256x256/apps/campus-net-portal.png"
DESKTOP_DST="$HOME/.local/share/applications/campus-net-portal.desktop"
SERVICE="$HOME/.config/systemd/user/campus-net-portal.service"

if [ "$1" = "--uninstall" ]; then
  echo "卸载中..."
  # 先关掉自启服务，避免卸载后 systemd 还在重启它
  systemctl --user disable --now campus-net-portal.service 2>/dev/null || true
  rm -f "$SERVICE" "$BIN_DST" "$ICON_DST" "$DESKTOP_DST"
  systemctl --user daemon-reload 2>/dev/null || true
  rm -rf "$HOME/.config/CampusNetPortal"
  echo "已卸载（配置目录 ~/.config/CampusNetPortal 也已删除）"
  exit 0
fi

if [ ! -f "$BIN_SRC" ]; then
  echo "找不到 $BIN_SRC，请先运行 ./build_linux.sh"
  exit 1
fi

echo "[1/3] 安装可执行文件"
mkdir -p "$HOME/.local/bin"
install -m 755 "$BIN_SRC" "$BIN_DST"
echo "   -> $BIN_DST"

echo "[2/3] 安装图标"
mkdir -p "$(dirname "$ICON_DST")"
if [ -f "$APP_DIR/net.png" ]; then
  install -m 644 "$APP_DIR/net.png" "$ICON_DST"
elif [ -f "$APP_DIR/dist/net.png" ]; then
  install -m 644 "$APP_DIR/dist/net.png" "$ICON_DST"
else
  python3 -c "import sys; sys.path.insert(0,'$APP_DIR'); import iconart; iconart.write_png('$ICON_DST', 256)"
fi
echo "   -> $ICON_DST"

echo "[3/3] 安装菜单项"
mkdir -p "$(dirname "$DESKTOP_DST")"
cat > "$DESKTOP_DST" <<EOF
[Desktop Entry]
Type=Application
Name=校园网自动认证
Name[en]=SNNU Campus Net Portal
Comment=陕西师范大学校园网自动认证（图形界面 / 开机自启 / 防掉线保活）
Exec=$BIN_DST
Icon=campus-net-portal
Terminal=false
Categories=Network;Utility;
Keywords=campus;network;portal;snnu;
EOF
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
echo "   -> $DESKTOP_DST"

echo
echo "安装完成。"
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) echo "注意：$HOME/.local/bin 不在 PATH 里，建议把下面这行加进 ~/.bashrc："
     echo '    export PATH="$HOME/.local/bin:$PATH"' ;;
esac
echo
echo "接下来："
echo "  1) 运行一次「校园网自动认证」，填账号/密码/运营商并点连接"
echo "  2) 在界面里勾选「开机静默自启」（Linux 上会写成 systemd 用户服务）"
echo
echo "手动管理自启服务："
echo "  systemctl --user status  campus-net-portal.service"
echo "  systemctl --user stop    campus-net-portal.service"
echo "  journalctl --user -u campus-net-portal.service -f"
