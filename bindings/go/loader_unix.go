//go:build !windows

package temari

import (
	"fmt"

	"github.com/ebitengine/purego"
)

// load opens the cdylib with purego's cgo-free dlopen.
func (l *Library) load() error {
	h, err := purego.Dlopen(l.path, purego.RTLD_NOW|purego.RTLD_GLOBAL)
	if err != nil {
		return fmt.Errorf("temari: dlopen %s: %w (run `cargo build --release` first?)", l.path, err)
	}
	l.handle = h
	return nil
}

// registerFunc binds `name` on the dlopen handle via purego.RegisterLibFunc.
func (l *Library) registerFunc(fn any, name string) error {
	return registerLibFuncSafe(fn, l.handle, name)
}
