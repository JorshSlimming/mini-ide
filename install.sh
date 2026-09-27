#!/usr/bin/env bash
# Install PanelIDE with its runtime assets, desktop entry, and icons.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
BIN="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/panelide"
APPS="$HOME/.local/share/applications"
ICON_ROOT="$HOME/.local/share/icons/hicolor"

mkdir -p "$BIN" "$APP_DIR" "$APP_DIR/mini_ide" "$APP_DIR/theme" \
    "$APP_DIR/ui-icons" "$APP_DIR/app-icon" "$APPS"

install -m 755 "$SRC/panelide.py" "$APP_DIR/panelide.py"
cp -R "$SRC/mini_ide/." "$APP_DIR/mini_ide/"
cp -R "$SRC/theme/." "$APP_DIR/theme/"
cp -R "$SRC/ui-icons/." "$APP_DIR/ui-icons/"
cp -R "$SRC/app-icon/." "$APP_DIR/app-icon/"
install -m 755 "$SRC/scripts/limit-cpu.sh" "$BIN/limit-cpu.sh"

cat > "$BIN/panelide" <<EOF
#!/usr/bin/env bash
exec python3 "$APP_DIR/panelide.py" "\$@"
EOF
chmod 755 "$BIN/panelide"

launcher_exec="$BIN/panelide"
launcher_exec=${launcher_exec//\\/\\\\}
launcher_exec=${launcher_exec//\"/\\\"}
launcher_exec=${launcher_exec//|/\\|}
launcher_exec=${launcher_exec//&/\\&}
sed "s|^Exec=panelide %F$|Exec=\"$launcher_exec\" %F|" \
    "$SRC/packaging/panelide.desktop.template" > "$APPS/panelide.desktop"
for size in 16 24 32 48 64 128 256 512; do
    icon_dir="$ICON_ROOT/${size}x${size}/apps"
    mkdir -p "$icon_dir"
    install -m 644 "$SRC/app-icon/png/panelide-${size}.png" \
        "$icon_dir/panelide.png"
done
mkdir -p "$ICON_ROOT/scalable/apps"
install -m 644 "$SRC/app-icon/svg/panelide.svg" \
    "$ICON_ROOT/scalable/apps/panelide.svg"

# Remove only artifacts created by the former Mini-IDE installer.
rm -f "$BIN/mini-ide" "$BIN/mini-ide.py"
rm -rf "$BIN/mini_ide"
rm -f "$APPS/mini-ide.desktop"
rm -f "$ICON_ROOT/scalable/apps/mini-ide.svg"
rm -f "$ICON_ROOT/128x128/apps/mini-ide.png"

printf '%s\n' "Installed PanelIDE in $APP_DIR." \
    "Launch with: panelide [project-folder]" \
    "Configure the embedded terminal with PANELIDE_HARNESS=/path/to/executable." \
    "Legacy MINI_IDE_OMP and ~/.config/mini-ide state remain supported." \
    "Optional CPU profiles: sudo $BIN/limit-cpu.sh mild (or fresh/full/cycle/status)." \
    "Do not create a passwordless sudo rule for scripts in your home directory."
