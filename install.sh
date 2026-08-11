#!/usr/bin/env bash
set -euo pipefail

echo "Starting installation..."

# Install python dependencies
pip install --no-cache-dir -r requirements.txt

# Determine THEOS path
THEOS_DIR="${THEOS:-$(pwd)/theos}"
export THEOS="$THEOS_DIR"

echo "Setting THEOS to: $THEOS"

# Clone Theos if not exists
if [ ! -d "$THEOS/.git" ]; then
    echo "Cloning Theos..."
    rm -rf "$THEOS"
    git clone --depth 1 --recurse-submodules https://github.com/theos/theos.git "$THEOS"
fi

# Verify critical files exist
echo "Verifying Theos structure..."
test -f "$THEOS/makefiles/common.mk" || (echo "Error: common.mk missing" && exit 1)
test -f "$THEOS/makefiles/tweak.mk" || (echo "Error: tweak.mk missing" && exit 1)

# Handle SDKs
mkdir -p "$THEOS/sdks"
if ! find "$THEOS/sdks" -maxdepth 1 -type d -name '*.sdk' -print -quit | grep -q .; then
    echo "Downloading iOS SDKs..."
    rm -rf /tmp/theos_sdks
    git clone --depth 1 https://github.com/theos/sdks.git /tmp/theos_sdks
    find /tmp/theos_sdks -maxdepth 1 -type d -name '*.sdk' -exec cp -R {} "$THEOS/sdks/" \;
    rm -rf /tmp/theos_sdks
fi

# Final verification report
echo "=== THEOS CHECK ==="
echo "THEOS=$THEOS"
echo "THEOS_MAKE_PATH=$THEOS/makefiles"
ls -l "$THEOS/makefiles/tweak.mk"
echo "Available SDKs:"
find "$THEOS/sdks" -maxdepth 1 -type d -name '*.sdk'

echo "Installation completed successfully."
