# temari FFI — cdylib 接口参考

> [English FFI.md](./FFI.md)

temari 核心编译为动态链接库(`libtemari.so` / `.dll` / `.dylib`),导出 C ABI,
供 Python、Go 等语言在进程内直接调用解密核心。

## 构建

```bash
cargo build --release        # 生成 target/release/libtemari.so(Windows 为 temari.dll)
```

## 函数

```c
void*  tmpl_from_json(const char* json, size_t len);          // JSON 模板 → 句柄(出错返回 NULL)
void   tmpl_destroy(void* tmpl);                              // 释放模板句柄(NULL 安全)
size_t decrypt_sample_ffi(const void* tmpl, const uint8_t* sample,
                          size_t sample_len, uint8_t* out);   // 单样本解密
size_t decrypt_samples_par(const void* tmpl,
                           const uint8_t* const* ptrs,
                           const size_t* lens, size_t n,
                           uint8_t* out);         // 并行批量(散列输入),顺序保留
void*  stream_new(const void* tmpl, size_t batch_size);       // 创建流式解密器
void   stream_submit(void* s, const uint8_t* sample, size_t len);  // 提交一个样本
size_t stream_next(void* s, uint8_t* out, size_t cap);        // 阻塞按序取回
int    stream_try_next(void* s, uint8_t* out, size_t cap, size_t* out_len); // 非阻塞探针
void   stream_finish(void* s);                                // 关闭输入侧
void   stream_destroy(void* s);                               // 释放流句柄(NULL 安全)
```

- `decrypt_sample_ffi` / `decrypt_samples_par` 返回写出的明文长度(恒等于密文长度);`0` 表示出错。
- `stream_next` 在流已关闭且消费完毕时返回 `0`;`stream_try_next` 返回 `1`=有数据、`0`=暂无、`-1`=已关闭。

## 模板

`tmpl_from_json` 解析 40020 key server 返回的 JSON。**本库不联网**——由调用方
自行拉取并按 `(adam_id, uri)` 缓存:

```json
{ "ctx": "<b64>", "state": "<b64>",
  "rcx": "0x..", "rax": "0x..", "rdx": "0x..", "r9": "0x..", "rbp": "0x.." }
```

`ctx` / `state` 为 base64 编码的解密上下文;寄存器为十六进制字符串。

## 所有权

模板与流句柄由库分配,调用方负责释放(`tmpl_destroy` / `stream_destroy`)。明文
写入调用方提供的 `out` 缓冲。`stream_new` 会克隆模板,流存活期间可释放原句柄。

## 语言绑定

- Python(ctypes,零依赖):[`bindings/python`](./bindings/python/README.zh.md)
- Go(purego,免 cgo):[`bindings/go`](./bindings/go/README.zh.md)

完整示例与用法见各绑定 README。