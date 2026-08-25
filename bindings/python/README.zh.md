# temari — Python 包(ctypes 绑定)

> [English README](./README.md)

`temari` 是对 Temari cdylib(`libtemari.so` / `.dll` / `.dylib`)的**零第三方依赖**
ctypes 封装,用于在 Python 进程内直接解密 Apple Music FairPlay SAMPLE-AES 样本。

**本库不负责网络请求**:模板由**调用方**自行获取(如 urllib 拉 40020 JSON 响应体),
再交给 `Temari.from_json` 解析。

## 使用

```bash
# 先构建 cdylib
cd <temari 仓库根>
cargo build --release        # 产物 target/release/libtemari.so
```

```python
from temari import Temari
import urllib.parse, urllib.request

# 1) 调用方负责网络:拉 40020 风格 JSON 响应体(或读本地 JSON 文件)
body = urllib.request.urlopen(
    "http://127.0.0.1:40020/?adamId=1720704575&uri="
    + urllib.parse.quote("skd://itunes.apple.com/p683167073/c23")).read()

# 2) 库只解析 JSON → 模板
t = Temari.from_json(body)

plain = t.decrypt(ct)            # 单样本(等长明文)
plains = t.decrypt_par(samples)  # 并行批量,顺序保留

t.close()                        # 释放句柄;支持 with 语句

# 流式:样本随到随送,按提交顺序取回
s = t.stream(batch_size=256)   # 或 StreamDecryptor.from_json(body)
s.submit(chunk1); s.submit(chunk2); s.finish()
for plain in s: ...            # 阻塞迭代
async for plain in s.aiter(): ...   # asyncio.to_thread 封装
s.close()
```

## 库加载

`load()` 依次尝试:`TEMARI_LIB` 环境变量 → 仓库默认 `target/release/libtemari.so`。
可显式指定:`Temari.from_json(body, lib=load("/path/to/libtemari.so"))`。

## 示例与测试

```bash
python3 examples/json_decrypt.py                  # 自动拉起 mock 40020(caller 拉 JSON)
python3 examples/json_decrypt.py --no-mock --json <模板.json>   # 离线本地 JSON
python3 -m pytest tests/ -v                       # 需已构建 libtemari.so
```

## 与 FFI 的对应

| Python API | FFI 导出 |
|---|---|
| `Temari.from_json` | `tmpl_from_json` |
| `Temari.decrypt` | `decrypt_sample_ffi` |
| `Temari.decrypt_par` | `decrypt_samples_par` |
| `Temari.stream` / `StreamDecryptor` | `stream_new`/`stream_submit`/`stream_next`/... |
| `Temari.close` | `tmpl_destroy` |

> 批量解密把每个样本当作**独立 SAMPLE-AES 单元**(每样本重置状态)。
> 客户端应按片段(fragment/stripe)边界切分样本,不要随意切块后与整轨 `.pt` 拼接比对。