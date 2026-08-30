## Temari
Apple Music FairPlay Streaming decryption library

The project name comes from [Tsukimura Temari (月村手毬)](https://bangumi.tv/character/153576)

> [中文版 README](./README.zh.md)

### What is this
This library decrypts content protected by Apple Music's FairPlay Streaming DRM. Technically, it supports decrypting content encrypted via the `NfcRKVnxuKZy04KWbdFu71Ou` method.

It depends on the decryption-context data provided by [WorldObservationLog/wrapper](https://github.com/WorldObservationLog/wrapper).

### How to use
If you are not a developer, you probably do not need this library. You should look at [zhaarey/apple-music-downloader](https://github.com/zhaarey/apple-music-downloader) and [WorldObservationLog/AppleMusicDecrypt](https://github.com/WorldObservationLog/AppleMusicDecrypt).

### Install from package registries

All three packages are published and self-contained (platform cdylibs bundled):

| Registry | Package | Install |
|---|---|---|
| crates.io | `temari` | `cargo add temari` |
| PyPI | `temari` | `pip install temari` |
| Go | `github.com/WorldObservationLog/Temari/bindings/go` | `go get github.com/WorldObservationLog/Temari/bindings/go@v0.4.0` |

The Python and Go packages automatically select the bundled cdylib for the
current platform (Linux x86_64 / arm64, Windows x86_64 / arm64, macOS
x86_64 / arm64 — the macOS x86_64 and Windows arm64 libs are cross-compiled,
no Intel-Mac runner is used) — **no Rust
toolchain is needed on the target machine**. For Rust, add the crate as a
normal dependency:

```toml
[dependencies]
temari = "0.1"
```

**Un-precompiled platforms** (e.g. riscv64, ppc64le, FreeBSD): both the Python
wheel and the Go module ship the Rust source, so they can self-compile — the
Python package at install time (`pip install temari --no-binary :all:`) or on
first use; the Go module on first `LoadDefault()`. This needs a `cargo`
toolchain; without it, build the cdylib yourself (`cargo build --release`) and
point `TEMARI_LIB` / `Load()` at it.

> Building the cdylib by hand (`cargo build --release`) is only needed for the
> FFI / manual-loading path.

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

lib, _ := temari.LoadDefault()   // bundled cdylib for the current platform
t, _ := lib.FromJSON(body)
plain, _ := t.Decrypt(sample)
plains, _ := t.DecryptPar(samples)
t.Close()
```

#### WebAssembly (browser)
See also [`bindings/wasm`](./bindings/wasm/README.md)

```js
import { loadTemari } from "temari.js";

const temari = await loadTemari("/temari.wasm");
const t = temari.Temari.fromJson(jsonBytes);   // caller fetches the JSON
const plain = t.decrypt(ctBytes);              // single sample (no threads in wasm)
t.close();
```

### Special Thanks
- An anonymous person provided the original Frida decryption program and the wrapper decryption program
- chocomint provided arm64 architecture support for the wrapper
- Deepseek, Claude Code, and Deepseek Harness did most of the reverse engineering and programming work

### License
MIT, see [`LICENSE`](./LICENSE).