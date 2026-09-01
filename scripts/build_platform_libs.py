#!/usr/bin/env python3
"""Build the Temari cdylib for the host (and any installed cross targets) and
bundle the artifacts into both language bindings:

    bindings/python/temari/lib/<platform>/<libname>   (shipped in the PyPI wheel)
    bindings/go/lib/<platform>/<libname>              (shipped in the Go module)

The Rust crate is pure std, so the host target builds natively; additional
targets (e.g. x86_64-pc-windows-gnu via rust-lld, aarch64-linux-android via
the Android NDK) are built when their std is installed and a linker is
available. macOS / other targets must be built on that platform (or in CI) —
running this script there bundles them too.
"""

import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # <repo>
CARGO = shutil.which("cargo")
if not CARGO:
    sys.exit("cargo not found on PATH")

# target-triple -> (platform key, artifact filename)
TARGETS = {
    "x86_64-unknown-linux-gnu": ("linux-x86_64", "libtemari.so"),
    "aarch64-unknown-linux-gnu": ("linux-arm64", "libtemari.so"),
    "aarch64-linux-android": ("android-arm64", "libtemari.so"),
    "x86_64-pc-windows-gnu": ("windows-x86_64", "temari.dll"),
    "x86_64-pc-windows-msvc": ("windows-x86_64", "temari.dll"),
    "aarch64-pc-windows-msvc": ("windows-arm64", "temari.dll"),
    "x86_64-apple-darwin": ("macos-x86_64", "libtemari.dylib"),
    "aarch64-apple-darwin": ("macos-arm64", "libtemari.dylib"),
}

PY_LIB = os.path.join(REPO, "bindings", "python", "temari", "lib")
GO_LIB = os.path.join(REPO, "bindings", "go", "lib")


def host_target():
    """Return the exact host target triple (e.g. x86_64-unknown-linux-gnu,
    x86_64-pc-windows-msvc, aarch64-apple-darwin) from `rustc -vV`."""
    out = subprocess.run(["rustc", "-vV"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith("host:"):
            return line.split(":", 1)[1].strip()
    return None


def installed_targets():
    out = subprocess.run(["rustup", "target", "list", "--installed"],
                         capture_output=True, text=True).stdout
    return {t.strip() for t in out.splitlines() if t.strip()}


def android_ndk_clang(api):
    """Path of the NDK's aarch64-linux-android<api>-clang wrapper for the
    current host, or None. honours ANDROID_NDK_HOME / ANDROID_HOME
    (either may point at the NDK root or its parent) plus the typical
    /opt/android-sdk/ndk-bundle location."""
    candidates = []
    for var in ("ANDROID_NDK_HOME", "ANDROID_HOME"):
        base = os.environ.get(var)
        if base:
            candidates += [base, os.path.join(base, "ndk-bundle")]
    candidates += ["/opt/android-sdk/ndk-bundle", os.path.expanduser(
        "~/Android/Sdk/ndk-bundle")]
    host_dir = "linux-x86_64" if sys.platform.startswith("linux") else \
        "darwin-x86_64" if sys.platform == "darwin" else "windows-x86_64"
    for ndk in candidates:
        clang = os.path.join(ndk, "toolchains", "llvm", "prebuilt", host_dir,
                             "bin", f"aarch64-linux-android{api}-clang")
        if os.path.exists(clang):
            return clang
    return None


def build_one(triple):
    key, fname = TARGETS[triple]
    env = dict(os.environ)
    flags = []
    if triple == "aarch64-linux-android":
        # Cross-compiling for Android needs the NDK's clang wrapper as the
        # linker (NDK r19+ has a single wrapper per API level, any host OS).
        api = os.environ.get("TEMARI_ANDROID_API", "21")
        clang = android_ndk_clang(api)
        if clang:
            flags = ["-C", f"linker={clang}"]
        else:
            print(f"[warn] {triple}: Android NDK clang not found "
                  f"(set ANDROID_NDK_HOME); skipping", flush=True)
            return
    elif "windows" in triple and not sys.platform.startswith("win"):
        # cross-compiling a pure-std crate from a non-Windows host: link with
        # the toolchain's rust-lld + self-contained CRT (no MinGW needed).
        # On a native Windows runner we build with the default MSVC toolchain.
        flags = ["-C", "linker=rust-lld", "-C", "link-self-contained=yes"]
    if flags:
        env["RUSTFLAGS"] = " ".join(flags)
    print(f"[build] {triple} ...", flush=True)
    r = subprocess.run(
        [CARGO, "build", "--release", "--target", triple],
        cwd=REPO, env=env, capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"[build] {triple} FAILED:\n{r.stderr[-1200:]}", flush=True)
        return
    src = os.path.join(REPO, "target", triple, "release", fname)
    if not os.path.exists(src):
        print(f"[build] {triple}: artifact not found ({src})", flush=True)
        return
    if "android" in triple:
        # strip debug info to keep the bundle small; use the NDK's llvm-strip
        # when on PATH so the triple matches the artifact (best-effort).
        strip = shutil.which("llvm-strip")
        if not strip and clang:
            cand = os.path.join(os.path.dirname(clang), "llvm-strip")
            if os.path.exists(cand):
                strip = cand
        if strip:
            subprocess.run([strip, "--strip-unneeded", src],
                           capture_output=True)
    for dest in (os.path.join(PY_LIB, key), os.path.join(GO_LIB, key)):
        os.makedirs(dest, exist_ok=True)
        shutil.copy2(src, os.path.join(dest, fname))
    print(f"[bundle] {key}/{fname}", flush=True)


def sync_go_crate():
    """Keep bindings/go/crate/ (embedded Rust source for Go self-build) in sync
    with the repo crate source."""
    dest = os.path.join(REPO, "bindings", "go", "crate")
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(os.path.join(REPO, "src"), os.path.join(dest, "src"))
    shutil.copy2(os.path.join(REPO, "Cargo.toml"), os.path.join(dest, "Cargo.toml"))
    print("[bundle] go crate source -> bindings/go/crate/", flush=True)


def main():
    targets = list(installed_targets()) or [host_target()]
    ht = host_target()
    if ht and ht not in targets:
        print(f"[warn] host target {ht} not installed, trying anyway")
        targets.append(ht)
    built = 0
    for triple in targets:
        if triple in TARGETS:
            build_one(triple)
            built += 1
    sync_go_crate()
    print(f"\nDone: attempted {built} target(s). "
          f"Libs -> bindings/python/temari/lib/ and bindings/go/lib/")
    print("Reminder: macOS/other targets must be built on that platform or in CI.")


if __name__ == "__main__":
    main()