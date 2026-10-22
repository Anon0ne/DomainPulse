#!/usr/bin/env bash
# Wrap the PyInstaller output in an AppImage. Expects dist/DomainPulse and build/domain-pulse.png.
set -euo pipefail
VERSION="${1:-dev}"
APPDIR=build/DomainPulse.AppDir

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr"
cp -r dist/DomainPulse "$APPDIR/usr/bin"
cp build/domain-pulse.png "$APPDIR/domain-pulse.png"

cat > "$APPDIR/domain-pulse.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Domain Pulse
Comment=Domain registration and expiry monitor by BizHostNC
Exec=DomainPulse
Icon=domain-pulse
Categories=Network;Utility;
DESKTOP

cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/DomainPulse" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

if [ ! -x build/appimagetool ]; then
  curl -fsSL -o build/appimagetool \
    https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
  chmod +x build/appimagetool
fi
ARCH=x86_64 build/appimagetool --appimage-extract-and-run "$APPDIR" "dist/DomainPulse-${VERSION}-x86_64.AppImage"
