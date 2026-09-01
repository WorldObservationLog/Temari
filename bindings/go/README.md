# temari — Go package (purego, no cgo)

> [中文版 README.md](./README.zh.md)

`temari` calls the Temari cdylib (`libtemari.so` / `.dylib` / `temari.dll`)
from pure Go and decrypts Apple Music FairPlay SAMPLE-AES samples directly
inside a Go process.

**This package does no networking**: the template is fetched by the **caller**
(e.g. pull the 40020 JSON response body with net/http) and handed to
`FromJSON` for parsing.

**No cgo required**: all calls go through
[`purego`](https://github.com/ebitengine/purego), so `CGO_ENABLED=0` builds,
tests, and runs work on Linux, macOS, and Windows.

## Install

```bash
go get github.com/WorldObservationLog/Temari/bindings/go@v0.5.1
```

The module ships the cdylibs for all platforms under `lib/<platform>/`, and
`LoadDefault()` selects the right one for the current GOOS/GOARCH — no Rust
toolchain needed on the target machine. The Rust source is also embedded
(`crate/`), so on an un-precompiled platform `LoadDefault()` compiles it on
first use with `cargo` (cached under the user cache dir).

## Usage

```bash
# (optional) build the cdylib from the repo instead of using the bundled one
cd <temari repo root>
cargo build --release        # artifact target/release/libtemari.so

# run examples and tests (CGO_ENABLED=0 works)
cd bindings/go
go run ./examples/json_decrypt.go      # auto-starts a mock 40020 (caller fetches JSON)
go run ./examples/json_decrypt.go --no-mock --json <template.json>   # offline
go test ./... -v
```

```go
import "temari"

lib, err := temari.LoadDefault()   // bundled cdylib for the current platform

// 1) caller owns networking: fetch the 40020-style JSON response body (or read a local JSON file)
//    body, _ := fetchJSON(server, adamID, uri)   // net/http

// 2) the library only parses JSON -> template
t, err := lib.FromJSON(body)

plain, err := t.Decrypt(sample)          // single sample (equal-length plaintext)
plains, err := t.DecryptPar(samples)     // parallel batch, order preserved

t.Close()                                // free the handle

// streaming: submit samples as they arrive, receive in submission order
s, _ := t.NewStream(256)
s.Submit(chunk1); s.Submit(chunk2); s.Finish()
for plain := range s.C() { ... }          // goroutine + channel async
s.Close()
```

## Notes

- Symbols are bound at `Load` time; a missing symbol returns an error.
- Handles must be released with `Close()`.
- Batch decryption treats each sample as an **independent SAMPLE-AES unit**
  (state resets per sample); clients should split samples on
  fragment/stripe boundaries.

## Mapping to the FFI

| Go API | FFI export |
|---|---|
| `Library.FromJSON` | `tmpl_from_json` |
| `Temari.Decrypt` | `decrypt_sample_ffi` |
| `Temari.DecryptPar` | `decrypt_samples_par` |
| `Temari.NewStream` / `Stream` | `stream_new`/`stream_submit`/`stream_next`/... |
| `Temari.Close` | `tmpl_destroy` |