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

# platform key (lib directory name) -> wheel platform tag.
# Used only for single-platform local/dev builds; the CI release assembles all
# platforms into one `py3-none-any` wheel (bundled_platform_key() -> None),
# so these tags do not affect the published wheel.
PLAT_TAGS = {
    "linux-x86_64": "manylinux_2_34_x86_64",
    "linux-aarch64": "manylinux_2_34_aarch64",
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


def _bundled_platform_present():
    """True if a bundled lib for the current platform already exists (pre-built
    by scripts/build_platform_libs.py on the host runner)."""
    import platform
    import sys

    p = sys.platform
    osname = "linux" if p.startswith("linux") else "macos" if p == "darwin" else \
        "windows" if p in ("win32", "cygwin") else None
    if not osname:
        return False
    m = platform.machine().lower()
    arch = "x86_64" if m in ("x86_64", "amd64", "intel64") else \
        "arm64" if m in ("arm64", "aarch64") else None
    if not arch:
        return False
    key = f"{osname}-{arch}"
    for name in ("temari.dll", "libtemari.dll", "libtemari.dylib", "libtemari.so"):
        if os.path.exists(os.path.join(LIB_DIR, key, name)):
            return True
    return False


class BuildPy(build_py):
    """Compile the host cdylib and bundle it before building the package.

    Skips the (expensive, Rust-toolchain-dependent) build when a bundled lib
    for this platform already exists — e.g. pre-built by the CI runner or a
    prior scripts/build_platform_libs.py run. This also avoids running cargo
    inside cibuildwheel's manylinux container.
    """

    def run(self):
        if not _bundled_platform_present():
            if os.path.exists(SCRIPT):
                print("temari: building bundled cdylib (host platform)...")
                subprocess.check_call([sys.executable, SCRIPT], cwd=REPO)
            else:
                raise RuntimeError(
                    "temari: no bundled cdylib and scripts/build_platform_libs.py "
                    "not found — build the cdylib first (cargo build --release)"
                )
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