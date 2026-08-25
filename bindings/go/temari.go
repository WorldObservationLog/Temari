// Package temari wraps the Temari cdylib (libtemari.so / .dylib / temari.dll)
// with a cgo-free FFI. No C toolchain is required: the package builds and runs
// with CGO_ENABLED=0, for static binaries and cross-compilation.
//
// The library performs **no network requests**: construct a template from a
// 40020-style key-server JSON response body with FromJSON — fetch the JSON
// yourself (own HTTP client) and pass it here.
//
// Loading is platform-specific (see loader_unix.go / loader_windows.go):
//   - Linux / macOS / FreeBSD: purego `Dlopen` to open the library
//   - Windows: `golang.org/x/sys/windows` `LoadDLL` to open the library
//     (purego supports Windows, but has no `Dlopen` there)
//
// On every platform symbols are bound with purego `RegisterLibFunc` (its
// loadSymbol is dlopen/dlsym on unix, GetProcAddress on Windows), and all
// calls go through purego's cgo-free calling convention.
//
// Build the library first:
//
//	cd <temari repo> && cargo build --release   # -> libtemari.so / temari.dll
//
// Then load it once:
//
//	lib, err := temari.Load("/path/to/libtemari.so")   // or temari.dll on Windows
//	t, err := lib.FromJSON(jsonBody)                    // caller fetched the JSON
//	plain, err := t.Decrypt(sample)
package temari

import (
	"errors"
	"fmt"
	"unsafe"

	"github.com/ebitengine/purego"
)

// Library is the loaded temari cdylib. Call Load once and reuse the returned
// Library. `handle` is the module handle (dlopen on unix; LoadLibrary on
// Windows).
type Library struct {
	path   string
	handle uintptr

	tmplFromJSON             func(unsafe.Pointer, uintptr) uintptr
	tmplDestroy              func(uintptr)
	decryptSampleFfi         func(uintptr, unsafe.Pointer, uintptr, unsafe.Pointer) uintptr
	decryptSamplesParScatter func(uintptr, *unsafe.Pointer, *uintptr, uintptr, unsafe.Pointer) uintptr
	streamNew                func(uintptr, uintptr) uintptr
	streamSubmit             func(uintptr, unsafe.Pointer, uintptr)
	streamNext               func(uintptr, unsafe.Pointer, uintptr) uintptr
	streamTryNext            func(uintptr, unsafe.Pointer, uintptr, *uintptr) int32
	streamFinish             func(uintptr)
	streamDestroy            func(uintptr)
}

// Temari is an opaque decryption template handle. Thread-safe for concurrent
// Decrypt calls; free with Close.
type Temari struct {
	h   uintptr
	lib *Library
}

// Load opens the temari cdylib from path. Returns an error if the library or
// any required symbol is missing.
func Load(path string) (*Library, error) {
	l := &Library{path: path}
	if err := l.load(); err != nil {
		return nil, err
	}
	if err := l.bindSymbols(); err != nil {
		return nil, err
	}
	return l, nil
}

func (l *Library) bindSymbols() error {
	syms := []struct {
		name string
		fn   any
	}{
		{"tmpl_from_json", &l.tmplFromJSON},
		{"tmpl_destroy", &l.tmplDestroy},
		{"decrypt_sample_ffi", &l.decryptSampleFfi},
		{"decrypt_samples_par", &l.decryptSamplesParScatter},
		{"stream_new", &l.streamNew},
		{"stream_submit", &l.streamSubmit},
		{"stream_next", &l.streamNext},
		{"stream_try_next", &l.streamTryNext},
		{"stream_finish", &l.streamFinish},
		{"stream_destroy", &l.streamDestroy},
	}
	for _, s := range syms {
		if err := l.registerFunc(s.fn, s.name); err != nil {
			return fmt.Errorf("temari: resolve %s: %w", s.name, err)
		}
	}
	return nil
}

// registerLibFuncSafe binds fn to the exported symbol `name` of `handle` via
// purego.RegisterLibFunc (which panics on a missing symbol / bad signature),
// converting the panic into an error. Works on unix (Dlsym) and Windows
// (GetProcAddress) alike — purego supports both.
func registerLibFuncSafe(fn any, handle uintptr, name string) (err error) {
	defer func() {
		if r := recover(); r != nil {
			err = fmt.Errorf("%v", r)
		}
	}()
	purego.RegisterLibFunc(fn, handle, name)
	return nil
}

// FromJSON builds a template handle from a 40020-style key-server JSON response
// body. The library performs no network requests — fetch the JSON yourself
// (e.g. with net/http) and pass the raw body here.
func (l *Library) FromJSON(json []byte) (*Temari, error) {
	if len(json) == 0 {
		return nil, errors.New("temari: empty JSON template")
	}
	ptr := l.tmplFromJSON(unsafe.Pointer(&json[0]), uintptr(len(json)))
	if ptr == 0 {
		return nil, errors.New("temari: tmpl_from_json failed (bad JSON template?)")
	}
	return &Temari{h: ptr, lib: l}, nil
}

// Close frees the template handle (nil-safe, idempotent).
func (t *Temari) Close() {
	if t == nil || t.h == 0 {
		return
	}
	t.lib.tmplDestroy(t.h)
	t.h = 0
}

// Decrypt decrypts one sample, returning equal-length plaintext.
func (t *Temari) Decrypt(sample []byte) ([]byte, error) {
	if t == nil || t.h == 0 {
		return nil, errors.New("temari: closed handle")
	}
	if len(sample) == 0 {
		return nil, nil
	}
	out := make([]byte, len(sample))
	n := t.lib.decryptSampleFfi(
		t.h,
		unsafe.Pointer(&sample[0]),
		uintptr(len(sample)),
		unsafe.Pointer(&out[0]),
	)
	if int(n) != len(sample) {
		return nil, fmt.Errorf("temari: decrypt_sample_ffi returned %d (expected %d)", n, len(sample))
	}
	return out, nil
}

// DecryptPar decrypts a batch of independent samples in parallel, preserving
// order. Each sample is an independent SAMPLE-AES unit (state resets per
// sample), so a whole stream can be split at fragment boundaries and decrypted
// across all cores.
//
// Default fast path: samples are read via scattered pointers (no input join
// memcpy) by decrypt_samples_par; plaintexts land in one flat
// buffer which is sliced into the returned views.
func (t *Temari) DecryptPar(samples [][]byte) ([][]byte, error) {
	if t == nil || t.h == 0 {
		return nil, errors.New("temari: closed handle")
	}
	n := len(samples)
	if n == 0 {
		return [][]byte{}, nil
	}
	ptrs := make([]unsafe.Pointer, n)
	lens := make([]uintptr, n)
	total := 0
	for i, s := range samples {
		if len(s) == 0 {
			continue
		}
		ptrs[i] = unsafe.Pointer(&s[0])
		lens[i] = uintptr(len(s))
		total += len(s)
	}
	outbuf := make([]byte, total)
	got := t.lib.decryptSamplesParScatter(
		t.h,
		&ptrs[0],
		&lens[0],
		uintptr(n),
		unsafe.Pointer(&outbuf[0]),
	)
	if int(got) != total {
		return nil, fmt.Errorf("temari: decrypt_samples_par returned %d (expected %d)", got, total)
	}
	results := make([][]byte, n)
	off := 0
	for i, s := range samples {
		results[i] = outbuf[off : off+len(s)]
		off += len(s)
	}
	return results, nil
}

// StreamState is the result of a non-blocking Stream.TryNext.
type StreamState int

const (
	// StreamData: a plaintext is ready.
	StreamData StreamState = iota
	// StreamEmpty: no plaintext pending yet (stream still open).
	StreamEmpty
	// StreamClosed: the stream is closed and consumed.
	StreamClosed
)

// Stream is an incremental parallel decryptor with in-order results.
//
// Submit encrypted samples as they arrive, then receive plaintexts in
// submission order. Blocking at the library level; wrap with C() for
// asynchronous consumption (goroutine + channel).
type Stream struct {
	h   uintptr
	lib *Library
}

// NewStream creates a streaming decryptor over this template. The stream
// clones the template, so the Temari handle may be closed afterwards.
// batchSize <= 0 selects a default of 256.
func (t *Temari) NewStream(batchSize int) (*Stream, error) {
	if t == nil || t.h == 0 {
		return nil, errors.New("temari: closed handle")
	}
	if batchSize <= 0 {
		batchSize = 256
	}
	h := t.lib.streamNew(t.h, uintptr(batchSize))
	if h == 0 {
		return nil, errors.New("temari: stream_new failed")
	}
	return &Stream{h: h, lib: t.lib}, nil
}

// Submit queues one encrypted sample (blocks on internal backpressure).
func (s *Stream) Submit(sample []byte) error {
	if s == nil || s.h == 0 {
		return errors.New("temari: closed stream")
	}
	if len(sample) == 0 {
		return nil
	}
	s.lib.streamSubmit(s.h, unsafe.Pointer(&sample[0]), uintptr(len(sample)))
	return nil
}

// Next blocks for the next plaintext (in order). ok=false once the stream is
// closed and everything is consumed.
func (s *Stream) Next() (plain []byte, ok bool) {
	if s == nil || s.h == 0 {
		return nil, false
	}
	cap := uintptr(4096) // typical sample size; grows on overflow
	for {
		out := make([]byte, cap)
		n := s.lib.streamNext(s.h, unsafe.Pointer(&out[0]), cap)
		if n == 0 {
			return nil, false
		}
		if n < cap {
			return out[:n], true
		}
		cap *= 2 // sample larger than guessed capacity
	}
}

// TryNext is a non-blocking probe.
func (s *Stream) TryNext() (plain []byte, state StreamState) {
	if s == nil || s.h == 0 {
		return nil, StreamClosed
	}
	cap := uintptr(4096) // typical sample size; grows on overflow
	for {
		out := make([]byte, cap)
		var got uintptr
		r := s.lib.streamTryNext(s.h, unsafe.Pointer(&out[0]), cap, &got)
		switch r {
		case 1:
			if got < cap {
				return out[:got], StreamData
			}
			cap *= 2
			continue
		case 0:
			return nil, StreamEmpty
		default:
			return nil, StreamClosed
		}
	}
}

// Finish closes the input side; already-submitted samples still drain.
func (s *Stream) Finish() {
	if s == nil || s.h == 0 {
		return
	}
	s.lib.streamFinish(s.h)
}

// Close destroys the stream handle (idempotent).
func (s *Stream) Close() {
	if s == nil || s.h == 0 {
		return
	}
	s.lib.streamDestroy(s.h)
	s.h = 0
}

// C returns a channel that receives plaintexts in order until the stream is
// closed (the channel is then closed). A pump goroutine does the blocking
// Next() calls off the caller's goroutine.
func (s *Stream) C() <-chan []byte {
	ch := make(chan []byte)
	go func() {
		defer close(ch)
		for {
			plain, ok := s.Next()
			if !ok {
				return
			}
			ch <- plain
		}
	}()
	return ch
}
