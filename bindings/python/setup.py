"""setuptools build hooks for the temari Python package.

`python -m build` automatically compiles the Temari cdylib for the host
platform (scripts/build_platform_libs.py) and bundles it inside the wheel
under temari/lib/<platform>/, so a pip-installed package works out of the box
without a Rust toolchain on the target machine.

The wheel also carries the Rust source under temari/_src/ so an un-precompiled
platform can self-compile at install time (pip install --no-binary :all:) or
on first use (runtime fallback), provided `cargo` is installed.
"""

import os
import shutil
import subprocess
import sys

from setuptools import setup
from setuptools.command.build_py import build_py
from wheel.bdist_wheel import bdist_wheel

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SCRIPT = os.path.join(REPO, "scripts", "build_platform_libs.py")
LIB_DIR = os.path.join(HERE, "temari", "lib")
SRC_DIR = os.path.join(HERE, "temari", "_src")

# platform key (lib directory name) -> wheel platform tag.
# Used only for single-platform local/dev builds; the CI release assembles all
# platforms into one `py3-none-any` wheel (bundled_platform_key() -> None),
# so these tags do not affect the published wheel.
PLAT_TAGS = {
    "linux-x86_64": "manylinux_2_34_x86_64",
    "linux-arm64": "manylinux_2_34_aarch64",
    "windows-x86_64": "win_amd64",
    "windows-arm64": "win_arm64",
    "macos-x86_64": "macosx_10_12_x86_64",
    "macos-arm64": "macosx_11_0_arm64",
    # PEP 738 Android wheel tag (Android 5.0+ / min API 21)
    "android-arm64": "21_arm64_v8a_android",
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


def _copy_rust_source():
    """Copy the Rust crate source into temari/_src/ so un-precompiled platforms
    can self-compile. Called from both build_py and sdist: `python -m build`
    builds the wheel from the sdist in a temp dir where the repo root is not
    reachable, so the source must already be present in the packaged tree."""
    if os.path.isdir(os.path.join(REPO, "src")):
        shutil.rmtree(SRC_DIR, ignore_errors=True)
        shutil.copytree(os.path.join(REPO, "src"), os.path.join(SRC_DIR, "src"))
        # Cargo.toml only — deliberately NOT rust-toolchain.toml, so the
        # self-build uses whatever stable toolchain the user has.
        p = os.path.join(REPO, "Cargo.toml")
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(SRC_DIR, "Cargo.toml"))


def _cargo_build_from(src_dir, out_dir, name):
    """cargo build --release from src_dir (a crate root), copy the cdylib
    `name` into out_dir. Returns the artifact path or None."""
    cargo = shutil.which("cargo")
    if not cargo:
        return None
    manifest = os.path.join(src_dir, "Cargo.toml")
    if not os.path.isfile(manifest):
        return None
    subprocess.check_call(
        [cargo, "build", "--release", "--manifest-path", manifest],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    artifact = os.path.join(src_dir, "target", "release", name)
    if not os.path.isfile(artifact):
        return None
    os.makedirs(out_dir, exist_ok=True)
    shutil.copy2(artifact, os.path.join(out_dir, name))
    return artifact


def _bundled_lib_name():
    import platform as _pl
    import sys as _sys

    p = _sys.platform
    osname = "linux" if p.startswith("linux") else "macos" if p == "darwin" else \
        "windows" if p in ("win32", "cygwin") else None
    if not osname:
        return None
    return {"windows": "temari.dll", "macos": "libtemari.dylib"}.get(osname, "libtemari.so")


class BuildPy(build_py):
    """Compile the host cdylib and bundle it before building the package.

    Skips the (expensive, Rust-toolchain-dependent) build when a bundled lib
    for this platform already exists — e.g. pre-built by the CI runner or a
    prior scripts/build_platform_libs.py run. This also avoids running cargo
    inside cibuildwheel's manylinux container.
    """

    def run(self):
        # bundle the Rust source so un-precompiled platforms can self-compile
        _copy_rust_source()
        if not _bundled_platform_present():
            name = _bundled_lib_name()
            if os.path.exists(SCRIPT):
                print("temari: building bundled cdylib (host platform)...")
                subprocess.check_call([sys.executable, SCRIPT], cwd=REPO)
            elif name and os.path.isdir(SRC_DIR):
                # sdist install on an un-precompiled platform: build from the
                # bundled source (install-time self-compile, needs cargo)
                print("temari: compiling bundled Rust source for this platform...")
                try:
                    _cargo_build_from(SRC_DIR, LIB_DIR, name)
                except (subprocess.CalledProcessError, OSError):
                    raise RuntimeError(
                        "temari: this platform has no bundled cdylib and the "
                        "self-compile failed — install Rust (cargo) and retry, "
                        "or use the standard wheel."
                    ) from None
            else:
                raise RuntimeError(
                    "temari: no bundled cdylib, no build script and no bundled "
                    "Rust source — build the cdylib first (cargo build --release)"
                )
        super().run()


from setuptools.command.sdist import sdist  # noqa: E402


class Sdist(sdist):
    """Make sure the Rust source is present before archiving the sdist."""

    def run(self):
        _copy_rust_source()
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


setup(cmdclass={"build_py": BuildPy, "bdist_wheel": PlatformWheel, "sdist": Sdist})