#!/bin/bash
set -e

PYTHON=/opt/anaconda3/bin/python3
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== CASSN Field Data Manager — Build Script ==="
echo "Project: $PROJECT_DIR"
echo ""

# 1. Install PyInstaller if needed
echo "[1/4] Checking PyInstaller..."
if ! $PYTHON -m PyInstaller --version &>/dev/null; then
    echo "  Installing PyInstaller..."
    $PYTHON -m pip install pyinstaller
else
    echo "  PyInstaller found: $($PYTHON -m PyInstaller --version)"
fi

# 2. Convert icon PNG -> ICNS (uses built-in macOS tools, no extra installs)
echo "[2/4] Converting icon to .icns..."
ICONSET="$PROJECT_DIR/assets/cassn_icon.iconset"
mkdir -p "$ICONSET"
sips -z 16   16   "$PROJECT_DIR/assets/cassn_icon.png" --out "$ICONSET/icon_16x16.png"    &>/dev/null
sips -z 32   32   "$PROJECT_DIR/assets/cassn_icon.png" --out "$ICONSET/icon_16x16@2x.png" &>/dev/null
sips -z 32   32   "$PROJECT_DIR/assets/cassn_icon.png" --out "$ICONSET/icon_32x32.png"    &>/dev/null
sips -z 64   64   "$PROJECT_DIR/assets/cassn_icon.png" --out "$ICONSET/icon_32x32@2x.png" &>/dev/null
sips -z 128  128  "$PROJECT_DIR/assets/cassn_icon.png" --out "$ICONSET/icon_128x128.png"  &>/dev/null
sips -z 256  256  "$PROJECT_DIR/assets/cassn_icon.png" --out "$ICONSET/icon_128x128@2x.png" &>/dev/null
sips -z 256  256  "$PROJECT_DIR/assets/cassn_icon.png" --out "$ICONSET/icon_256x256.png"  &>/dev/null
sips -z 512  512  "$PROJECT_DIR/assets/cassn_icon.png" --out "$ICONSET/icon_256x256@2x.png" &>/dev/null
sips -z 512  512  "$PROJECT_DIR/assets/cassn_icon.png" --out "$ICONSET/icon_512x512.png"  &>/dev/null
sips -z 1024 1024 "$PROJECT_DIR/assets/cassn_icon.png" --out "$ICONSET/icon_512x512@2x.png" &>/dev/null
iconutil -c icns "$ICONSET" -o "$PROJECT_DIR/assets/cassn_icon.icns"
rm -rf "$ICONSET"
echo "  Icon saved: assets/cassn_icon.icns"

# 3. Run PyInstaller
echo "[3/4] Building .app bundle..."
cd "$PROJECT_DIR"
$PYTHON -m PyInstaller cassn_field_data_manager.spec --noconfirm

# 4. Done — show result
APP="$PROJECT_DIR/dist/CASSN Field Data Manager.app"
if [ -d "$APP" ]; then
    SIZE=$(du -sh "$APP" | cut -f1)
    echo ""
    echo "[4/4] Build complete!"
    echo "  App:  dist/CASSN Field Data Manager.app  ($SIZE)"
    echo ""
    echo "=== Next steps ==="
    echo "  1. Create a launcher folder:   mkdir -p ~/Applications/CASSN"
    echo "  2. Copy the app:               cp -r \"dist/CASSN Field Data Manager.app\" ~/Applications/CASSN/"
    echo "  3. Copy your config files:     cp config.json box_tokens.json ~/Applications/CASSN/"
    echo "  4. First launch:               Right-click the .app → Open  (one-time Gatekeeper bypass)"
    echo "  5. Pin to Dock:                Drag the .app to the Dock, or right-click its Dock icon → Options → Keep in Dock"
    echo ""
    echo "  To rebuild after code changes: bash build.sh"
else
    echo ""
    echo "ERROR: Build failed — .app not found in dist/"
    exit 1
fi
