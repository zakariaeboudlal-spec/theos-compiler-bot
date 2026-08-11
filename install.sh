#!/usr/bin/env bash
set -e
echo "Starting installation..."

pip install --no-cache-dir -r requirements.txt

# تثبيت Theos مباشرة داخل مجلد المشروع لضمان توفر tweak.mk دائماً
THEOS_DIR="$(pwd)/theos"
echo "Installing Theos to $THEOS_DIR..."
mkdir -p "$THEOS_DIR"
if [ -d "$THEOS_DIR/.git" ]; then
    cd "$THEOS_DIR" && git pull || true
else
    git clone --recursive https://github.com/theos/theos.git "$THEOS_DIR" || echo "Theos clone failed"
fi

# تحميل الـ SDKs
SDK_DIR="$THEOS_DIR/sdks"
mkdir -p "$SDK_DIR"
if [ -z "$(ls -A $SDK_DIR)" ]; then
    echo "Downloading iOS SDKs..."
    git clone --recursive https://github.com/theos/sdks.git /tmp/theos_sdks || true
    cp -r /tmp/theos_sdks/*.sdk "$SDK_DIR/" 2>/dev/null || true
    rm -rf /tmp/theos_sdks
fi

echo "Installation completed successfully."
