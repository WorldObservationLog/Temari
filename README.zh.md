## Temari
Apple Music Fairplay Streaming 解密库

项目名来自[月村手毬（Tsukimura Temari）](https://bangumi.tv/character/153576)

> [English README](./README.md)

### 这是什么
该库用于解密 Apple Music 中受 Fairplay Streaming DRM 保护的内容。技术上，其支持解密通过`NfcRKVnxuKZy04KWbdFu71Ou`方法解密的内容。

该库依赖于 [WorldObservationLog/wrapper](https://github.com/WorldObservationLog/wrapper) 提供的解密上下文数据。

### 如何使用
如果您不是开发者，您可能并不需要使用本库。您应当查看 [zhaarey/apple-music-downloader](https://github.com/zhaarey/apple-music-downloader) 和 [WorldObservationLog/AppleMusicDecrypt](https://github.com/WorldObservationLog/AppleMusicDecrypt)

构建动态库:

```bash
cargo build --release        # 生成 target/release/libtemari.so(Windows 为 temari.dll)
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
另见 [`FFI.md`](./FFI.md)

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
另见 [`bindings/python`](./bindings/python/README.md)

```python
from temari import Temari

body = fetch_decrypt_context_json()
t = Temari.from_json(body)
plain = t.decrypt(ct)
plains = t.decrypt_par(samples)
t.close()
```

#### Golang Binding
另见 [`bindings/go`](./bindings/go/README.md)

```go
import "temari"

lib, _ := temari.Load("/path/to/libtemari.so")
t, _ := lib.FromJSON(body)
plain, _ := t.Decrypt(sample)
plains, _ := t.DecryptPar(samples)
t.Close()
```

### 特别感谢
- 匿名人士提供了原始的 Frida 解密程序与 wrapper 解密程序
- chocomint 为 wrapper 提供了 arm64 架构支持
- Deepseek、Claude Code和Deepseek Harness完成了绝大部分逆向工程与程序编写的工作

### 许可证
MIT,详见 [`LICENSE`](./LICENSE)。