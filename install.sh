#!/usr/bin/env bash
# Installs Mini-IDE as a desktop app (menu entry + icon).
set -e

SRC="$(cd "$(dirname "$0")" && pwd)"
BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
ICONDIR="$HOME/.local/share/icons/hicolor/128x128/apps"

mkdir -p "$BIN" "$APPS" "$ICONDIR"

cp "$SRC/mini-ide.py" "$BIN/mini-ide.py"
chmod +x "$BIN/mini-ide.py"
rm -rf "$BIN/mini_ide"
cp -r "$SRC/mini_ide" "$BIN/mini_ide"
cp "$SRC/scripts/limit-cpu.sh" "$BIN/limit-cpu.sh"
chmod +x "$BIN/limit-cpu.sh"

cat > "$BIN/mini-ide" <<EOF
#!/usr/bin/env bash
exec python3 "$BIN/mini-ide.py" "\$@"
EOF
chmod +x "$BIN/mini-ide"

rm -f "$HOME/.config/autostart/limit-cpu.desktop"
rm -f "$HOME/.local/share/icons/hicolor/scalable/apps/mini-ide.svg"
cp "$SRC/icons/mini-ide.png" "$ICONDIR/mini-ide.png"

cat > "$APPS/mini-ide.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Mini-IDE
Comment=Lightweight browser and editor for working with opencode
Exec=python3 "$BIN/mini-ide.py" %F
Icon=mini-ide
Terminal=false
Categories=Development;Utility;
MimeType=inode/directory;
StartupNotify=true
EOF

echo "Installed. Look for 'Mini-IDE' in the application menu."
echo "To open a folder with Mini-IDE: right-click > Open with > Mini-IDE"
echo ""
echo "CPU power profiles (optional, manual):"
echo "  The installer no longer applies a power profile at login."
echo "  Run it yourself when desired:  sudo $BIN/limit-cpu.sh mild"
echo "  (or 'fresh' / 'full' / 'cycle' / 'status')."
echo ""
echo "Security note: do NOT create a passwordless (NOPASSWD) sudo rule for scripts in"
echo "your home directory. Anyone with your user account could replace the script and"
echo "run arbitrary commands as root."
