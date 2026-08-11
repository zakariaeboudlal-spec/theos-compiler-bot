import os
import re
import subprocess

THEOS_PATH = "/home/ubuntu/dylib_bot/theos"
PROJECT_DIR = "/tmp/test_project"
os.makedirs(PROJECT_DIR, exist_ok=True)

# 1. Create a dummy Makefile that would normally fail
makefile_content = """
DEBUG = 0
FINALPACKAGE = 1
include $(THEOS)/makefiles/common.mk

TWEAK_NAME = TestTweak
TestTweak_FILES = Tweak.x
TestTweak_CFLAGS = -fobjc-arc

include $(THEOS_MAKE_PATH)/tweak.mk
"""

makefile_path = os.path.join(PROJECT_DIR, "Makefile")
with open(makefile_path, "w") as f:
    f.write(makefile_content)

with open(os.path.join(PROJECT_DIR, "Tweak.x"), "w") as f:
    f.write("%hook UIView\n- (void)layoutSubviews { %orig; }\n%end\n")

print("--- Original Makefile ---")
print(makefile_content)

# 2. Apply the patching logic from bot.py
def patch_makefile(path):
    with open(path, 'r') as f:
        content = f.read()
    
    # Robust Makefile patching for Theos paths
    content = re.sub(r'include\s+/opt/theos/makefiles/', f'include {THEOS_PATH}/makefiles/', content)
    content = re.sub(r'include\s+/opt/render/project/src/theos/makefiles/', f'include {THEOS_PATH}/makefiles/', content)
    
    lines = content.splitlines()
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("export THEOS") or stripped.startswith("THEOS="):
            continue
        if stripped in ["include /tweak.mk", "include /common.mk", "include /aggregate.mk"]:
            continue
        cleaned_lines.append(line)
    
    new_lines = [
        f"THEOS = {THEOS_PATH}",
        f"export THEOS = {THEOS_PATH}",
        f"THEOS_MAKE_PATH = $(THEOS)/makefiles",
        f"export THEOS_MAKE_PATH = $(THEOS)/makefiles"
    ] + cleaned_lines
    
    patched_content = "\n".join(new_lines)
    with open(path, 'w') as f:
        f.write(patched_content)
    return patched_content

patched = patch_makefile(makefile_path)
print("\n--- Patched Makefile ---")
print(patched)

# 3. Simulate build environment
build_env = os.environ.copy()
build_env['THEOS'] = THEOS_PATH
build_env['THEOS_MAKE_PATH'] = os.path.join(THEOS_PATH, "makefiles")
build_env['PATH'] = f"{THEOS_PATH}/bin:{build_env.get('PATH', '')}"

print("\n--- Running Make Check ---")
# Just run 'make -n' (dry run) to see if it resolves all includes
result = subprocess.run(
    ["make", "-n", f"THEOS={THEOS_PATH}", f"THEOS_MAKE_PATH={build_env['THEOS_MAKE_PATH']}"],
    cwd=PROJECT_DIR,
    env=build_env,
    capture_output=True,
    text=True
)

if result.returncode == 0:
    print("✅ SUCCESS: Makefile resolved all dependencies correctly!")
else:
    print("❌ FAILED: Makefile still has issues.")
    print(result.stdout)
    print(result.stderr)
