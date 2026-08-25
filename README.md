## Temari
Apple Music FairPlay Streaming decryption library

The project name comes from [Tsukimura Temari (月村手毬)](https://bangumi.tv/character/153576)

> [中文版 README](./README.zh.md)

### What is this
This library decrypts content protected by Apple Music's FairPlay Streaming DRM. Technically, it supports decrypting content encrypted via the `NfcRKVnxuKZy04KWbdFu71Ou` method.

It depends on the decryption-context data provided by [WorldObservationLog/wrapper](https://github.com/WorldObservationLog/wrapper).

### How to use
If you are not a developer, you probably do not need this library. You should look at [zhaarey/apple-music-downloader](https://github.com/zhaarey/apple-music-downloader) and [WorldObservationLog/AppleMusicDecrypt](https://github.com/WorldObservationLog/AppleMusicDecrypt).

Build the dynamic library:

```bash
cargo build --release        # produces target/release/libtemari.so (temari.dll on Windows)
```

#### Rust
```rust
use temari::rounds;
use temari::template::template_from_json;

let tmpl = template_from_json(&json)?;
let plain = rounds::decrypt(&tmpl, &ct);
let plains = rounds::decrypt_par(&tmpl, &samples);
```

#### FFI
See also [`FFI.md`](./FFI.md)

```c
void*  tmpl_from_json(const char* json, size_t len);
void   tmpl_destroy(void* tmpl);
size_t decrypt_sample_ffi(const void* tmpl, const uint8_t* sample, size_t sample_len, uint8_t* out);
size_t decrypt_samples_par(const void* tmpl,
                           const uint8_t* const* ptrs,
                           const size_t* lens, size_t n,
                           uint8_t* out);
```

#### Python Binding
See also [`bindings/python`](./bindings/python/README.md)

```python
from temari import Temari

body = fetch_decrypt_context_json()
t = Temari.from_json(body)
plain = t.decrypt(ct)
plains = t.decrypt_par(samples)
t.close()
```

#### Golang Binding
See also [`bindings/go`](./bindings/go/README.md)

```go
import "temari"

lib, _ := temari.Load("/path/to/libtemari.so")
t, _ := lib.FromJSON(body)
plain, _ := t.Decrypt(sample)
plains, _ := t.DecryptPar(samples)
t.Close()
```

### Special Thanks
- An anonymous person provided the original Frida decryption program and the wrapper decryption program
- chocomint provided arm64 architecture support for the wrapper
- Deepseek, Claude Code, and Deepseek Harness did most of the reverse engineering and programming work

### License
MIT, see [`LICENSE`](./LICENSE).