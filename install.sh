#!/usr/bin/env bash
set -euo pipefail

echo "🚀 Starting Light Installation for Render..."

# 1. Install Python dependencies
pip install --no-cache-dir flask python-telegram-bot patool

# 2. Setup THEOS Path
THEOS_DIR="/opt/render/project/src/theos"
mkdir -p "$THEOS_DIR"
export THEOS="$THEOS_DIR"

# 3. Clone Theos (Lightweight)
if [ ! -d "$THEOS/.git" ]; then
    echo "📥 Cloning Theos Lite..."
    git clone --depth 1 --recurse-submodules https://github.com/theos/theos.git "$THEOS"
fi

# 4. Install Toolchain (Sbingner - Linux)
if [ ! -d "$THEOS/toolchain" ]; then
    echo "📥 Downloading Toolchain..."
    mkdir -p "$THEOS/toolchain"
    curl -L https://github.com/sbingner/llvm-project/releases/download/v10.0.0-1/linux-ios-arm64e-clang-toolchain.tar.lzma -o /tmp/toolchain.tar.lzma
    tar --lzma -xf /tmp/toolchain.tar.lzma -C "$THEOS/toolchain" --strip-components=1
    rm /tmp/toolchain.tar.lzma
fi

# 5. Download iOS 14.5 SDK (Only what's needed)
if [ ! -d "$THEOS/sdks/iPhoneOS14.5.sdk" ]; then
    echo "📥 Downloading SDK 14.5..."
    mkdir -p "$THEOS/sdks"
    curl -L https://github.com/theos/sdks/raw/master/iPhoneOS14.5.sdk.tar.xz -o /tmp/sdk.tar.xz
    tar -xf /tmp/sdk.tar.xz -C "$THEOS/sdks/"
    rm /tmp/sdk.tar.xz
fi

# 6. Install Missing Libs for Toolchain (libtinfo5)
LIB_DIR="/opt/render/project/src/lib"
mkdir -p "$LIB_DIR"
if [ ! -f "$LIB_DIR/libtinfo.so.5" ]; then
    echo "📥 Installing compatibility libs..."
    curl -LO http://archive.ubuntu.com/ubuntu/pool/universe/n/ncurses/libtinfo5_6.3-2_amd64.deb
    dpkg-deb -x libtinfo5_6.3-2_amd64.deb /tmp/libtinfo
    cp /tmp/libtinfo/lib/x86_64-linux-gnu/libtinfo.so.5* "$LIB_DIR/"
    rm -rf libtinfo5_6.3-2_amd64.deb /tmp/libtinfo
fi

echo "✅ Installation Finished Successfully!"
