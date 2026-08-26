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
		"temari: no bundled cdylib for %s-%s (run scripts/build_platform_libs.py or rebuild the wheel)",
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
// platform. Prefer it over Load(path) when using the distributed package.
func LoadDefault() (*Library, error) {
	p, err := BundledLibraryPath()
	if err != nil {
		return nil, err
	}
	return Load(p)
}