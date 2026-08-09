#!/usr/bin/env bash
# Instala Mini-IDE como app de escritorio (entrada en el menú + icono).
set -e

SRC="$(cd "$(dirname "$0")" && pwd)"
BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
ICONDIR="$HOME/.local/share/icons/hicolor/128x128/apps"

mkdir -p "$BIN" "$APPS" "$ICONDIR"

cp "$SRC/mini-ide.py" "$BIN/mini-ide.py"
chmod +x "$BIN/mini-ide.py"

cat > "$BIN/mini-ide" <<EOF
#!/usr/bin/env bash
exec python3 "$BIN/mini-ide.py" "\$@"
EOF
chmod +x "$BIN/mini-ide"

cp "$SRC/icons/mini-ide.png" "$ICONDIR/mini-ide.png"

cat > "$APPS/mini-ide.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Mini-IDE
Comment=Explorador y editor ligero para trabajar con opencode
Exec=python3 "$BIN/mini-ide.py" %F
Icon=mini-ide
Terminal=false
Categories=Development;Utility;
MimeType=inode/directory;
StartupNotify=true
EOF

echo "Instalado. Busca 'Mini-IDE' en el menú de aplicaciones."
echo "Para abrir una carpeta con Mini-IDE: clic derecho > Abrir con > Mini-IDE"
