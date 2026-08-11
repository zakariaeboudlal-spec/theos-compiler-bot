#!/usr/bin/env bash
set -euo pipefail

echo "Starting installation..."

pip install --no-cache-dir -r requirements.txt

THEOS_DIR="${THEOS:-$(pwd)/theos}"
export THEOS="$THEOS_DIR"

echo "THEOS=$THEOS"

if [ ! -d "$THEOS/.git" ]; then
    rm -rf "$THEOS"
    git clone --depth 1 --recurse-submodules https://github.com/theos/theos.git "$THEOS"
fi

test -f "$THEOS/makefiles/common.mk"
test -f "$THEOS/makefiles/tweak.mk"

mkdir -p "$THEOS/sdks"

if ! find "$THEOS/sdks" -maxdepth 1 -type d -name '*.sdk' -print -quit | grep -q .; then
    rm -rf /tmp/theos_sdks
    git clone --depth 1 https://github.com/theos/sdks.git /tmp/theos_sdks
    find /tmp/theos_sdks -maxdepth 1 -type d -name '*.sdk' -exec cp -R {} "$THEOS/sdks/" \;
fi

echo "=== THEOS CHECK ==="
echo "THEOS=$THEOS"
echo "THEOS_MAKE_PATH=$THEOS/makefiles"
ls -l "$THEOS/makefiles/tweak.mk"
find "$THEOS/sdks" -maxdepth 1 -type d -name '*.sdk' -print

echo "Installation completed successfully."
