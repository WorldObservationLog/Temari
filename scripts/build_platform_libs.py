#!/usr/bin/env python3
"""Build the Temari cdylib for the host (and any installed cross targets) and
bundle the artifacts into both language bindings:

    bindings/python/temari/lib/<platform>/<libname>   (shipped in the PyPI wheel)
    bindings/go/lib/<platform>/<libname>              (shipped in the Go module)

The Rust crate is pure std, so the host target builds natively; additional
targets (e.g. x86_64-pc-windows-gnu via rust-lld) are built when their std is
installed and a linker is available. macOS / other targets must be built on
that platform (or in CI) — running this script there bundles them too.
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
    "aarch64-unknown-linux-gnu": ("linux-aarch64", "libtemari.so"),
    "x86_64-pc-windows-gnu": ("windows-x86_64", "temari.dll"),
    "x86_64-pc-windows-msvc": ("windows-x86_64", "temari.dll"),
    "aarch64-pc-windows-msvc": ("windows-arm64", "temari.dll"),
    "x86_64-apple-darwin": ("macos-x86_64", "libtemari.dylib"),
    "aarch64-apple-darwin": ("macos-arm64", "libtemari.dylib"),
}

PY_LIB = os.path.join(REPO, "bindings", "python", "temari", "lib")
GO_LIB = os.path.join(REPO, "bindings", "go", "lib")


def host_target():
    system, machine = os.uname().sysname.lower(), os.uname().machine.lower()
    if system == "linux":
        return "x86_64-unknown-linux-gnu" if machine in ("x86_64", "amd64") else \
            "aarch64-unknown-linux-gnu" if machine == "aarch64" else None
    if system == "darwin":
        return "aarch64-apple-darwin" if machine in ("arm64", "aarch64") else "x86_64-apple-darwin"
    if system == "windows":
        return "x86_64-pc-windows-gnu"  # best-effort default
    return None


def installed_targets():
    out = subprocess.run(["rustup", "target", "list", "--installed"],
                         capture_output=True, text=True).stdout
    return {t.strip() for t in out.splitlines() if t.strip()}


def build_one(triple):
    key, fname = TARGETS[triple]
    flags = []
    if "windows" in triple:
        # pure-std crate: link with the toolchain's rust-lld + self-contained CRT
        flags = ["-C", "linker=rust-lld", "-C", "link-self-contained=yes"]
    print(f"[build] {triple} ...", flush=True)
    env = dict(os.environ)
    if flags:
        env["RUSTFLAGS"] = " ".join(flags)
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
    for dest in (os.path.join(PY_LIB, key), os.path.join(GO_LIB, key)):
        os.makedirs(dest, exist_ok=True)
        shutil.copy2(src, os.path.join(dest, fname))
    print(f"[bundle] {key}/{fname}", flush=True)


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
    print(f"\nDone: attempted {built} target(s). "
          f"Libs -> bindings/python/temari/lib/ and bindings/go/lib/")
    print("Reminder: macOS/other targets must be built on that platform or in CI.")


if __name__ == "__main__":
    main()