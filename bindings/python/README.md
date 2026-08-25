# temari — Python package (ctypes binding)

> [中文版 README.md](./README.zh.md)

A zero-dependency ctypes wrapper around the Temari cdylib
(`libtemari.so` / `.dll` / `.dylib`) for decrypting Apple Music FairPlay
SAMPLE-AES samples directly inside a Python process.

**This package does no networking**: the template is fetched by the **caller**
(e.g. pull the 40020 JSON response body with urllib) and handed to
`Temari.from_json` for parsing.

## Usage

```bash
# first build the cdylib
cd <temari repo root>
cargo build --release        # artifact target/release/libtemari.so
```

```python
from temari import Temari
import urllib.parse, urllib.request

# 1) caller owns networking: fetch the 40020-style JSON response body (or read a local JSON file)
body = urllib.request.urlopen(
    "http://127.0.0.1:40020/?adamId=1720704575&uri="
    + urllib.parse.quote("skd://itunes.apple.com/p683167073/c23")).read()

# 2) the library only parses JSON -> template
t = Temari.from_json(body)

plain = t.decrypt(ct)            # single sample (equal-length plaintext)
plains = t.decrypt_par(samples)  # parallel batch, order preserved

t.close()                        # free the handle; supports the `with` statement

# streaming: submit samples as they arrive, receive in submission order
s = t.stream(batch_size=256)   # or StreamDecryptor.from_json(body)
s.submit(chunk1); s.submit(chunk2); s.finish()
for plain in s: ...            # blocking iteration
async for plain in s.aiter(): ...   # asyncio.to_thread wrapper
s.close()
```

## Loading the library

`load()` tries, in order: the `TEMARI_LIB` environment variable → the repo
default `target/release/libtemari.so`. You can also specify explicitly:
`Temari.from_json(body, lib=load("/path/to/libtemari.so"))`.

## Examples and tests

```bash
python3 examples/json_decrypt.py                  # auto-starts a mock 40020 (caller fetches JSON)
python3 examples/json_decrypt.py --no-mock --json <template.json>   # offline local JSON
python3 -m pytest tests/ -v                       # requires libtemari.so to be built
```

## Mapping to the FFI

| Python API | FFI export |
|---|---|
| `Temari.from_json` | `tmpl_from_json` |
| `Temari.decrypt` | `decrypt_sample_ffi` |
| `Temari.decrypt_par` | `decrypt_samples_par` |
| `Temari.stream` / `StreamDecryptor` | `stream_new`/`stream_submit`/`stream_next`/... |
| `Temari.close` | `tmpl_destroy` |

> Batch decryption treats each sample as an **independent SAMPLE-AES unit**
> (state resets per sample). Clients should split samples on fragment/stripe
> boundaries and not compare arbitrary chunks against the full-track `.pt`.