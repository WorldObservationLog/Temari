//go:build windows

package temari

import (
	"fmt"

	"golang.org/x/sys/windows"
)

// load opens the cdylib on Windows via LoadLibrary (golang.org/x/sys/windows).
// purego itself supports Windows (RegisterLibFunc's loadSymbol is GetProcAddress
// on Windows), but it does not provide a Windows Dlopen — so we obtain the
// module handle here and hand it to purego.RegisterLibFunc just like on unix.
// The native DLL stays loaded for the process lifetime.
func (l *Library) load() error {
	dll, err := windows.LoadDLL(l.path)
	if err != nil {
		return fmt.Errorf("temari: LoadLibrary %s: %w (run `cargo build --release` first?)", l.path, err)
	}
	l.handle = uintptr(dll.Handle)
	return nil
}

// registerFunc binds `name` on the Windows module handle via
// purego.RegisterLibFunc (identical path to the unix loader).
func (l *Library) registerFunc(fn any, name string) error {
	return registerLibFuncSafe(fn, l.handle, name)
}
