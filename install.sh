#!/usr/bin/env bash
set -euo pipefail

echo "Starting installation..."

# Install python dependencies
pip install --no-cache-dir -r requirements.txt

THEOS_DIR="${THEOS:-$(pwd)/theos}"
export THEOS="$THEOS_DIR"

echo "THEOS=$THEOS"

# 1. Clone Theos
if [ ! -d "$THEOS/.git" ]; then
    rm -rf "$THEOS"
    git clone --depth 1 --recurse-submodules https://github.com/theos/theos.git "$THEOS"
fi

# 2. Download and install Toolchain
TOOLCHAIN_DIR="$THEOS/toolchain"
if [ ! -d "$TOOLCHAIN_DIR" ]; then
    echo "Downloading Toolchain..."
    mkdir -p "$TOOLCHAIN_DIR"
    # Using a reliable link for sbingner toolchain
    curl -L https://github.com/sbingner/llvm-project/releases/download/v10.0.0-1/linux-ios-arm64e-clang-toolchain.tar.lzma -o /tmp/toolchain.tar.lzma
    tar --lzma -xf /tmp/toolchain.tar.lzma -C "$TOOLCHAIN_DIR" --strip-components=1
    rm /tmp/toolchain.tar.lzma
    
    # Fix toolchain path for Theos
    mkdir -p "$TOOLCHAIN_DIR/linux/iphone"
    ln -sf "$TOOLCHAIN_DIR/bin" "$TOOLCHAIN_DIR/linux/iphone/bin"
fi

# 3. Download and extract missing libraries (libtinfo5, libssl1.1)
LIB_DIR="$(pwd)/lib"
mkdir -p "$LIB_DIR"
if [ ! -f "$LIB_DIR/libtinfo.so.5" ]; then
    echo "Downloading libtinfo5..."
    curl -LO http://archive.ubuntu.com/ubuntu/pool/universe/n/ncurses/libtinfo5_6.3-2_amd64.deb
    dpkg-deb -x libtinfo5_6.3-2_amd64.deb /tmp/libtinfo
    cp /tmp/libtinfo/lib/x86_64-linux-gnu/libtinfo.so.5* "$LIB_DIR/"
    rm -rf libtinfo5_6.3-2_amd64.deb /tmp/libtinfo
fi

if [ ! -f "$LIB_DIR/libssl.so.1.1" ]; then
    echo "Downloading libssl1.1..."
    curl -LO http://nz2.archive.ubuntu.com/ubuntu/pool/main/o/openssl/libssl1.1_1.1.1f-1ubuntu2.22_amd64.deb
    dpkg-deb -x libssl1.1_1.1.1f-1ubuntu2.22_amd64.deb /tmp/libssl
    cp /tmp/libssl/usr/lib/x86_64-linux-gnu/libssl.so.1.1 "$LIB_DIR/"
    cp /tmp/libssl/usr/lib/x86_64-linux-gnu/libcrypto.so.1.1 "$LIB_DIR/"
    rm -rf libssl1.1_1.1.1f-1ubuntu2.22_amd64.deb /tmp/libssl
fi

# 4. Handle SDKs
mkdir -p "$THEOS/sdks"
if ! find "$THEOS/sdks" -maxdepth 1 -type d -name 'iPhoneOS14.5.sdk' -print -quit | grep -q .; then
    echo "Downloading iOS 14.5 SDK..."
    curl -L https://github.com/theos/sdks/raw/master/iPhoneOS14.5.sdk.tar.xz -o /tmp/sdk.tar.xz
    tar -xf /tmp/sdk.tar.xz -C "$THEOS/sdks/"
    rm /tmp/sdk.tar.xz
fi

echo "=== THEOS CHECK ==="
echo "THEOS=$THEOS"
ls -l "$THEOS/makefiles/tweak.mk"
ls -l "$TOOLCHAIN_DIR/bin/clang"
ls -l "$LIB_DIR/libtinfo.so.5"

echo "Installation completed successfully."
