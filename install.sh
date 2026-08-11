#!/usr/bin/env bash
set -e
echo "Starting installation..."

pip install --no-cache-dir -r requirements.txt

THEOS_DIR="${THEOS:-$HOME/theos}"
echo "Installing Theos to $THEOS_DIR..."
mkdir -p "$(dirname "$THEOS_DIR")"
if [ -d "$THEOS_DIR" ]; then
    cd "$THEOS_DIR" && git pull || true
else
    git clone --recursive https://github.com/theos/theos.git "$THEOS_DIR" || echo "Theos clone failed"
fi

echo "Installation completed successfully."
