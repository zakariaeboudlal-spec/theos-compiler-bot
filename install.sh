#!/usr/bin/env bash
set -e
echo "Starting installation..."

pip install --no-cache-dir -r requirements.txt

# Setup Theos
THEOS_DIR=${THEOS:-/opt/theos}
if mkdir -p "$THEOS_DIR" 2>/dev/null; then
    echo "Installing Theos to $THEOS_DIR..."
    git clone --recursive https://github.com/theos/theos.git "$THEOS_DIR" || echo "Theos already cloned or failed"
else
    echo "Fallback to user home for Theos..."
    THEOS_DIR="$HOME/theos"
    mkdir -p "$THEOS_DIR"
    git clone --recursive https://github.com/theos/theos.git "$THEOS_DIR" || echo "Theos already cloned or failed"
    export THEOS="$THEOS_DIR"
fi

echo "Installation completed successfully."
