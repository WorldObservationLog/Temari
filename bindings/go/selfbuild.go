//go:build !wasm

// On-demand self-build for un-precompiled platforms.
//
// The Rust crate source is embedded into this package (crate/), so a platform
// without a bundled cdylib can compile one itself on first use, provided a
// `cargo` toolchain is installed. The built library is cached under the user
// cache dir (~/Library/Caches on macOS, %LOCALAPPDATA% on Windows,
// ~/.cache on Linux). Go has no install-time hook, so this is the practical
// equivalent: build once, on first use, then reuse.

package temari

import (
	"embed"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
)

//go:embed crate/Cargo.toml crate/src/*.rs
var crateFS embed.FS

// libNameForGOOS returns the cdylib file name for the current platform.
func libNameForGOOS() string {
	switch runtime.GOOS {
	case "windows":
		return "temari.dll"
	case "darwin":
		return "libtemari.dylib"
	default:
		return "libtemari.so"
	}
}

// writeEmbeddedCrate materialises the embedded Rust source into dir.
func writeEmbeddedCrate(dir string) error {
	if err := os.MkdirAll(filepath.Join(dir, "src"), 0o755); err != nil {
		return err
	}
	manifest, err := crateFS.ReadFile("crate/Cargo.toml")
	if err != nil {
		return fmt.Errorf("temari: read embedded Cargo.toml: %w", err)
	}
	if err := os.WriteFile(filepath.Join(dir, "Cargo.toml"), manifest, 0o644); err != nil {
		return err
	}
	entries, err := crateFS.ReadDir("crate/src")
	if err != nil {
		return fmt.Errorf("temari: read embedded src: %w", err)
	}
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		b, err := crateFS.ReadFile("crate/src/" + e.Name())
		if err != nil {
			return err
		}
		if err := os.WriteFile(filepath.Join(dir, "src", e.Name()), b, 0o644); err != nil {
			return err
		}
	}
	return nil
}

// selfBuildLibrary compiles the embedded Rust crate into the user cache dir
// and returns the built cdylib path, or an error (no cargo / build failure).
func selfBuildLibrary() (string, error) {
	cargo, err := exec.LookPath("cargo")
	if err != nil {
		return "", fmt.Errorf("temari: self-build requires the Rust toolchain (cargo not found)")
	}
	cacheRoot, err := os.UserCacheDir()
	if err != nil {
		cacheRoot = os.TempDir()
	}
	out := filepath.Join(cacheRoot, "temari", "lib", platformKey(), libNameForGOOS())
	if fi, err := os.Stat(out); err == nil && !fi.IsDir() {
		return out, nil // already built
	}
	buildDir := filepath.Join(cacheRoot, "temari", "src")
	if err := os.RemoveAll(buildDir); err != nil {
		return "", err
	}
	if err := writeEmbeddedCrate(buildDir); err != nil {
		return "", err
	}
	cmd := exec.Command(cargo, "build", "--release",
		"--manifest-path", filepath.Join(buildDir, "Cargo.toml"))
	cmd.Env = append(os.Environ(), "CARGO_TARGET_DIR="+filepath.Join(buildDir, "target"))
	if outBytes, err := cmd.CombinedOutput(); err != nil {
		return "", fmt.Errorf("temari: cargo build failed: %v\n%s", err, tail(outBytes, 1200))
	}
	artifact := filepath.Join(buildDir, "target", "release", libNameForGOOS())
	if _, err := os.Stat(artifact); err != nil {
		return "", fmt.Errorf("temari: build produced no %s", libNameForGOOS())
	}
	if err := os.MkdirAll(filepath.Dir(out), 0o755); err != nil {
		return "", err
	}
	if err := os.Rename(artifact, out); err != nil {
		return "", err
	}
	return out, nil
}

func tail(b []byte, n int) []byte {
	if len(b) > n {
		return b[len(b)-n:]
	}
	return b
}