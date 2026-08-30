# temari — WebAssembly(浏览器)绑定

> [English README](./README.md)

temari 核心可编译为 **WebAssembly**(`wasm32-unknown-unknown`),在浏览器内
直接解密样本——无需网络服务、客户端无需 Rust 工具链。wasm 导出与 FFI 相同的
接口(`tmpl_from_json`、`decrypt_sample_ffi` 等),本目录提供轻量 JS 封装。

## 构建

```bash
rustup target add wasm32-unknown-unknown
cargo build --release --target wasm32-unknown-unknown
# -> target/wasm32-unknown-unknown/release/temari.wasm  (~160 KB)
```

## 用法

```js
import { loadTemari } from "./temari.js";

const temari = await loadTemari("/temari.wasm");

// 调用方自己拉取 40020 模板 JSON(wasm 本身不联网)
const json = new Uint8Array(await (await fetch(templateUrl)).arrayBuffer());
const t = temari.Temari.fromJson(json);

const ct = new Uint8Array(ciphertextBytes);
const plain = t.decrypt(ct);   // Uint8Array,等长明文
t.close();
```

## 限制

- **仅支持单样本解密。** 并行批量(`decrypt_par`)依赖 `std::thread`,浏览器
  wasm 不提供;`decryptPar()` 返回 `null`。浏览器内并行可把样本拆到多个
  **Web Worker**,每个 Worker 各自一个 wasm 实例。
- JS 封装用 bump 分配器,按需 grow 线性内存;调用间不回收内存(对典型小样本
  无影响)。
- 完整浏览器多线程需 `SharedArrayBuffer` + COOP/COEP 与 `atomics`/
  `bulk-memory` wasm 特性——这里未启用。

## 性能(node v24,x86_64)

| 路径 | 吞吐 |
|---|---|
| wasm 单样本(9354 B) | ~62 MB/s |

与金标逐字节一致;原生单核 ~60–80 MB/s,故 wasm 串行路径约为原生的
80–100%。