# temari FFI — cdylib interface reference

> [中文版 FFI.md](./FFI.zh.md)

The temari core compiles to a dynamic library (`libtemari.so` / `.dll` /
`.dylib`) exporting a C ABI, so Python, Go, and other languages can call the
decryption core directly in-process.

## Build

```bash
cargo build --release        # produces target/release/libtemari.so (temari.dll on Windows)
```

## Functions

```c
void*  tmpl_from_json(const char* json, size_t len);          // JSON template -> handle (NULL on error)
void   tmpl_destroy(void* tmpl);                              // free a template handle (NULL-safe)
size_t decrypt_sample_ffi(const void* tmpl, const uint8_t* sample,
                          size_t sample_len, uint8_t* out);   // decrypt one sample
size_t decrypt_samples_par(const void* tmpl,
                           const uint8_t* const* ptrs,
                           const size_t* lens, size_t n,
                           uint8_t* out);         // parallel batch (scattered input), order preserved
void*  stream_new(const void* tmpl, size_t batch_size);       // create a streaming decryptor
void   stream_submit(void* s, const uint8_t* sample, size_t len);  // submit one sample
size_t stream_next(void* s, uint8_t* out, size_t cap);        // blocking in-order receive
int    stream_try_next(void* s, uint8_t* out, size_t cap, size_t* out_len); // non-blocking probe
void   stream_finish(void* s);                                // close the input side
void   stream_destroy(void* s);                               // free a stream (NULL-safe)
```

- `decrypt_sample_ffi` / `decrypt_samples_par` return the number of plaintext
  bytes written (always equal to the ciphertext length); `0` = error.
- `stream_next` returns `0` when the stream is closed and fully consumed;
  `stream_try_next` returns `1` = data, `0` = empty, `-1` = closed.

## Template

`tmpl_from_json` parses the JSON returned by the 40020 key server. The library
itself performs **no networking** — the caller fetches and caches the JSON
(by `(adam_id, uri)`):

```json
{ "ctx": "<b64>", "state": "<b64>",
  "rcx": "0x..", "rax": "0x..", "rdx": "0x..", "r9": "0x..", "rbp": "0x.." }
```

`ctx` / `state` are base64-encoded decryption contexts; the registers are hex
strings.

## Ownership

Template and stream handles are allocated by the library and must be freed by
the caller (`tmpl_destroy` / `stream_destroy`). Plaintext is written into the
caller-provided `out` buffer. `stream_new` clones the template, so the
original handle can be freed while the stream lives.

## Language bindings

- Python (ctypes, zero deps): [`bindings/python`](./bindings/python/README.md)
- Go (purego, no cgo): [`bindings/go`](./bindings/go/README.md)

Full examples and usage live in each binding's README.