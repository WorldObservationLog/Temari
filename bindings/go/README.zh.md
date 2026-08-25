# temari — Go 包(purego,无需 cgo)

> [English README](./README.md)

`temari` 用纯 Go 的 FFI 直接调用 Temari cdylib(`libtemari.so` / `.dylib` /
`temari.dll`),在 Go 进程内直接解密 Apple Music FairPlay SAMPLE-AES 样本。

**本库不负责网络请求**:模板由**调用方**自行获取(如 net/http 拉 40020 JSON 响应体),
再交给 `FromJSON` 解析。

**无需 cgo**:所有调用走 [`purego`](https://github.com/ebitengine/purego),
`CGO_ENABLED=0` 下即可构建、测试、运行,支持 Linux / macOS / Windows。

## 使用

```bash
# 先构建 cdylib
cd <temari 仓库根>
cargo build --release        # 产物 target/release/libtemari.so

# 运行示例与测试(可用 CGO_ENABLED=0)
cd bindings/go
go run ./examples/json_decrypt.go      # 自动拉起 mock 40020(caller 拉 JSON)
go run ./examples/json_decrypt.go --no-mock --json <模板.json>   # 离线
go test ./... -v
```

```go
import "temari"

lib, err := temari.Load("/path/to/target/release/libtemari.so")

// 1) 调用方负责网络:拉 40020 风格 JSON 响应体(或读本地 JSON 文件)
//    body, _ := fetchJSON(server, adamID, uri)   // net/http

// 2) 库只解析 JSON → 模板
t, err := lib.FromJSON(body)

plain, err := t.Decrypt(sample)          // 单样本(等长明文)
plains, err := t.DecryptPar(samples)     // 并行批量,顺序保留

t.Close()                                // 释放句柄

// 流式:样本随到随送,按提交顺序取回
s, _ := t.NewStream(256)
s.Submit(chunk1); s.Submit(chunk2); s.Finish()
for plain := range s.C() { ... }          // goroutine + channel 异步
s.Close()
```

## 注意事项

- 符号在 `Load` 时绑定,缺符号会以 error 返回。
- 句柄需 `Close()` 释放。
- 批量解密把每个样本当作**独立 SAMPLE-AES 单元**(每样本重置状态);
  客户端应按片段(fragment/stripe)边界切分样本。

## 与 FFI 的对应

| Go API | FFI 导出 |
|---|---|
| `Library.FromJSON` | `tmpl_from_json` |
| `Temari.Decrypt` | `decrypt_sample_ffi` |
| `Temari.DecryptPar` | `decrypt_samples_par` |
| `Temari.NewStream` / `Stream` | `stream_new`/`stream_submit`/`stream_next`/... |
| `Temari.Close` | `tmpl_destroy` |