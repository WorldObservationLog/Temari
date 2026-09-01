//go:build !wasm

// Bundled dynamic-library loading.
//
// scripts/build_platform_libs.py (and the GitHub Actions release workflow)
// compile the Temari cdylib for each platform and place it under
// bindings/go/lib/<platform>/<lib>, committed to the repo so `go get` ships
// it together with this package. LoadDefault resolves that bundled library
// for the current GOOS/GOARCH.

package temari

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime"
)

// BundledLibraryPath returns the path of the cdylib bundled with this module
// for the current platform, or an error if none is present.
func BundledLibraryPath() (string, error) {
	_, file, _, ok := runtime.Caller(0) // this source file -> <mod>/bindings/go
	if !ok {
		return "", fmt.Errorf("temari: cannot resolve package directory")
	}
	dir := filepath.Dir(file)
	names := []string{"temari.dll", "libtemari.dll"}
	switch runtime.GOOS {
	case "darwin":
		names = []string{"libtemari.dylib"}
	case "windows":
		// keep the default list
	default:
		names = []string{"libtemari.so"}
	}
	for _, name := range names {
		p := filepath.Join(dir, "lib", platformKey(), name)
		if fi, err := os.Stat(p); err == nil && !fi.IsDir() {
			return p, nil
		}
	}
	return "", fmt.Errorf(
		"temari: no bundled cdylib for %s-%s (bundled: android arm64, "+
			"linux x86_64/arm64, windows x86_64/arm64, macos x86_64/arm64). "+
			"To use this platform, build the cdylib yourself (`cargo build "+
			"--release` in the temari repo, Rust required) and point "+
			"Load()/TEMARI_LIB at the artifact, or add the platform to "+
			"scripts/build_platform_libs.py and the release matrix.",
		runtime.GOOS, runtime.GOARCH,
	)
}

// platformKey mirrors the directory naming used by scripts/build_platform_libs.py.
func platformKey() string {
	arch := "x86_64"
	if runtime.GOARCH == "arm64" || runtime.GOARCH == "aarch64" {
		arch = "arm64"
	}
	return runtime.GOOS + "-" + arch
}

// LoadDefault loads the cdylib bundled with this module for the current
// platform. For un-precompiled platforms it falls back to compiling the
// embedded Rust source with `cargo` (cached under the user cache dir).
// Prefer it over Load(path) when using the distributed package.
func LoadDefault() (*Library, error) {
	if p, err := BundledLibraryPath(); err == nil {
		return Load(p)
	}
	if p, err := selfBuildLibrary(); err == nil {
		return Load(p)
	}
	// report the "no bundled lib" error, which includes full instructions
	if _, err := BundledLibraryPath(); err != nil {
		return nil, err
	}
	return nil, fmt.Errorf("temari: no usable cdylib for %s-%s", runtime.GOOS, runtime.GOARCH)
}