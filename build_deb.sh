#!/bin/bash
set -e

APP_NAME="bada"
VERSION="0.1.0"
ARCH="amd64"

# 1. Build Binary with PyInstaller
echo "Building binary..."
pyinstaller --onefile --name $APP_NAME --hidden-import=telegram src/bada/main.py

# 2. Prepare Deb Package Structure
echo "Creating deb package structure..."
mkdir -p package/DEBIAN
mkdir -p package/usr/local/bin
mkdir -p package/usr/share/applications

# Copy binary
cp dist/$APP_NAME package/usr/local/bin/
chmod 755 package/usr/local/bin/$APP_NAME

# Copy desktop shortcut
cp bada-community.desktop package/usr/share/applications/

# Create control file
cat > package/DEBIAN/control << EOL
Package: $APP_NAME
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Maintainer: User <user@example.com>
Description: bada
 Allows LLMs to execute code on your local machine.
EOL

# 3. Build .deb
echo "Building .deb..."
dpkg-deb --build package ${APP_NAME}_${VERSION}_${ARCH}.deb

echo "Done: ${APP_NAME}_${VERSION}_${ARCH}.deb"
