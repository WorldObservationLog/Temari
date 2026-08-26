"""setuptools build hooks for the temari Python package.

`python -m build` automatically compiles the Temari cdylib for the host
platform (scripts/build_platform_libs.py) and bundles it inside the wheel
under temari/lib/<platform>/, so a pip-installed package works out of the box
without a Rust toolchain on the target machine.

Each wheel is tagged for the platform whose lib it bundles
(scripts/build_platform_libs.py places exactly one platform's lib per build;
GitHub Actions builds one wheel per native runner). On Linux CI, cibuildwheel
+ auditwheel further refine the manylinux tag.
"""

import os
import subprocess
import sys

from setuptools import setup
from setuptools.command.build_py import build_py
from wheel.bdist_wheel import bdist_wheel

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SCRIPT = os.path.join(REPO, "scripts", "build_platform_libs.py")
LIB_DIR = os.path.join(HERE, "temari", "lib")

# platform key (lib directory name) -> wheel platform tag
PLAT_TAGS = {
    "linux-x86_64": "manylinux_2_17_x86_64",
    "linux-aarch64": "manylinux_2_17_aarch64",
    "windows-x86_64": "win_amd64",
    "macos-x86_64": "macosx_10_12_x86_64",
    "macos-arm64": "macosx_11_0_arm64",
}


def bundled_platform_key():
    """Return the platform key if exactly one platform's lib is bundled,
    else None (no libs yet, or a multi-platform bundle)."""
    if not os.path.isdir(LIB_DIR):
        return None
    keys = [d for d in os.listdir(LIB_DIR) if os.path.isdir(os.path.join(LIB_DIR, d))]
    return keys[0] if len(keys) == 1 else None


class BuildPy(build_py):
    """Compile the host cdylib and bundle it before building the package."""

    def run(self):
        if os.path.exists(SCRIPT):
            print("temari: building bundled cdylib (host platform)...")
            subprocess.check_call([sys.executable, SCRIPT], cwd=REPO)
        super().run()


class PlatformWheel(bdist_wheel):
    """Tag the wheel for the bundled platform so PyPI serves the right binary
    per platform."""

    def finalize_options(self):
        super().finalize_options()
        key = bundled_platform_key()
        if key and key in PLAT_TAGS:
            self.root_is_pure = False
            self.plat_name = PLAT_TAGS[key]

    def get_tag(self):
        py, abi, plat = super().get_tag()
        key = bundled_platform_key()
        if key and key in PLAT_TAGS:
            plat = PLAT_TAGS[key]
        # the wrapper is pure Python (the native lib is bundled data), so the
        # wheel is py3-none-<platform>
        return ("py3", "none", plat)


setup(cmdclass={"build_py": BuildPy, "bdist_wheel": PlatformWheel})