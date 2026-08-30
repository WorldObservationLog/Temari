# temari — WebAssembly (browser) bindings

> [中文版 README](./README.zh.md)

The temari core compiles to **WebAssembly** (`wasm32-unknown-unknown`) for
in-browser sample decryption — no network service, no Rust toolchain on the
client. The wasm exports the same FFI surface (`tmpl_from_json`,
`decrypt_sample_ffi`, …), wrapped here by a tiny JS module.

## Build

```bash
rustup target add wasm32-unknown-unknown
cargo build --release --target wasm32-unknown-unknown
# -> target/wasm32-unknown-unknown/release/temari.wasm  (~160 KB)
```

## Usage

```js
import { loadTemari } from "./temari.js";

const temari = await loadTemari("/temari.wasm");

// caller fetches the 40020 template JSON (the wasm performs no network)
const json = new Uint8Array(await (await fetch(templateUrl)).arrayBuffer());
const t = temari.Temari.fromJson(json);

const ct = new Uint8Array(ciphertextBytes);
const plain = t.decrypt(ct);   // Uint8Array, same length
t.close();
```

## Limitations

- **Single-sample decrypt only.** The parallel batch (`decrypt_par`) relies on
  `std::thread`, which browser wasm does not provide; `decryptPar()` returns
  `null`. For parallel work in the browser, split samples across **Web
  Workers**, each with its own wasm instance.
- The JS wrapper uses a bump allocator that grows the linear memory as needed;
  it does not reclaim memory between calls (fine for typical small samples).
- Full browser threading would require `SharedArrayBuffer` + COOP/COEP and
  the `atomics`/`bulk-memory` wasm features — not enabled here.

## Performance (node v24, x86_64)

| Path | Throughput |
|---|---|
| wasm single-sample (9354 B) | ~62 MB/s |

Byte-identical to the golden vectors; native single-core is ~60–80 MB/s, so
wasm is within ~80–100% of native for the serial path.