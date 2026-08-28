"""temari — Python bindings for the Temari Apple Music FairPlay sample decryption library.

`libtemari`(cdylib)导出的是 C ABI(见仓库根 `FFI.md`):模板以不透明句柄传递,
样本为扁平 buffer。本包用 ctypes 做零依赖薄封装。

**本库不负责网络请求**:模板由**调用方**自行获取——从 40020 key server 拉取 JSON
响应体(或读本地 JSON 文件),再交给 `Temari.from_json` 解析。

    from temari import Temari, TemariError
    import json, urllib.request

    # 调用方负责网络:拉取 40020 风格的 JSON 响应体
    body = urllib.request.urlopen(
        "http://127.0.0.1:40020/?adamId=1720704575&uri=skd://...").read()

    t = Temari.from_json(body)            # JSON 响应体 → 模板句柄
    plain = t.decrypt(ct)                 # 单样本
    plains = t.decrypt_par(samples)       # 并行批量
    t.close()

# 流式解密:样本随到随送,按提交顺序取回明文(绑定层可再包 async)
s = t.stream(batch_size=256)   # 或 StreamDecryptor.from_json(json)
s.submit(chunk1); s.submit(chunk2)
s.finish()
for plain in s: ...            # 阻塞迭代;async for plain in s.aiter(): ...
s.close()

库路径解析顺序:`TEMARI_LIB` 环境变量 → 仓库默认 `target/release/libtemari.so`。
"""
import array
import asyncio
import ctypes
import os
import platform
import shutil
import subprocess
import sys

__all__ = ["Temari", "TemariError", "StreamDecryptor", "load", "default_library_path"]

__version__ = "0.1.0"


class TemariError(RuntimeError):
    """Raised when the cdylib fails to load or a native call returns an error."""


def _platform_key():
    """Return a short platform key like 'linux-x86_64' / 'windows-x86_64' /
    'macos-arm64', matching the bundled-lib directory names produced by
    scripts/build_platform_libs.py, or None if unknown."""
    p = sys.platform
    osname = "linux" if p.startswith("linux") else "macos" if p == "darwin" else \
        "windows" if p in ("win32", "cygwin") else None
    if not osname:
        return None
    m = platform.machine().lower()
    arch = "x86_64" if m in ("x86_64", "amd64", "intel64") else \
        "arm64" if m in ("arm64", "aarch64") else None
    if not arch:
        return None
    return f"{osname}-{arch}"


def _bundled_library_path():
    """Path of the cdylib bundled inside this package (temari/lib/<platform>/),
    if present. Bundled libs are built and shipped by the PyPI wheels."""
    here = os.path.dirname(os.path.abspath(__file__))
    key = _platform_key()
    if not key:
        return None
    names = ("temari.dll", "libtemari.dll") if key.startswith("windows") else \
        ("libtemari.dylib",) if key.startswith("macos") else ("libtemari.so",)
    for name in names:
        p = os.path.join(here, "lib", key, name)
        if os.path.exists(p):
            return p
    return None


def default_library_path():
    """Return the cdylib path used by :func:`load`.

    Resolution order:
    1. the ``TEMARI_LIB`` environment variable
    2. the cdylib bundled inside this package (PyPI wheel, per platform)
    3. the repo build output (``<repo>/target/release/...``)
    """
    env = os.environ.get("TEMARI_LIB")
    if env:
        return env
    bundled = _bundled_library_path()
    if bundled:
        return bundled
    here = os.path.dirname(os.path.abspath(__file__))
    # bindings/python/temari/__init__.py -> <repo>/target/release/
    repo = os.path.abspath(os.path.join(here, "..", "..", ".."))
    # Linux/macOS -> libtemari.so/.dylib; Windows cdylib -> temari.dll (no lib prefix)
    for name in ("libtemari.so", "libtemari.dylib", "libtemari.dll", "temari.dll"):
        p = os.path.join(repo, "target", "release", name)
        if os.path.exists(p):
            return p
    return os.path.join(repo, "target", "release", "libtemari.so")


# array typecode matching c_size_t (Q=8 bytes on 64-bit, L=4 on 32-bit)
_SIZE_T_CODE = "Q" if ctypes.sizeof(ctypes.c_size_t) == 8 else "L"


class Temari:
    """A decryption template (opaque handle) with decrypt methods.

    Create via :meth:`from_json`; close with :meth:`close`. A handle is
    immutable and thread-safe for concurrent decrypts.
    """

    # ------------------------------------------------------------------ #
    # construction
    # ------------------------------------------------------------------ #
    @classmethod
    def from_json(cls, json_data, lib=None):
        """Build a Temari handle from a 40020-style key-server JSON response.

        ``json_data`` is the JSON response body as ``str`` or ``bytes``.
        The library does **no network** — fetch the JSON yourself first.
        """
        lib = lib or load()
        if isinstance(json_data, str):
            json_data = json_data.encode()
        handle = lib._tmpl_from_json(ctypes.c_char_p(json_data), len(json_data))
        if not handle:
            raise TemariError("tmpl_from_json failed (bad JSON template?)")
        return cls.__new__(cls)._init_handle(handle, lib)

    def _init_handle(self, handle, lib=None):
        self._handle = handle
        self._lib = lib or load()
        return self

    def close(self):
        """Free the template handle (safe to call multiple times)."""
        h, self._handle = getattr(self, "_handle", None), None
        if h:
            self._lib._tmpl_destroy(h)

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ------------------------------------------------------------------ #
    # decryption
    # ------------------------------------------------------------------ #
    def decrypt(self, sample):
        """Decrypt one sample (equal-length plaintext)."""
        if self._handle is None:
            raise TemariError("handle already closed")
        n = len(sample)
        out = (ctypes.c_ubyte * n)()
        src = (ctypes.c_ubyte * n).from_buffer_copy(sample)
        got = self._lib._decrypt_sample_ffi(self._handle, src, n, out)
        if got != n:
            raise TemariError(f"decrypt_sample_ffi returned {got} (expected {n})")
        return ctypes.string_at(out, n)

    def decrypt_par(self, samples):
        """Decrypt a batch of samples in parallel, preserving order.

        Returns a list of plaintexts (each equal in length to its input).
        Fast path: input is joined with a single C-speed ``b''.join``, the
        lens array is a zero-copy ``array`` view, and output is read back
        with one ``string_at`` copy (no per-sample ctypes slicing).
        """
        if self._handle is None:
            raise TemariError("handle already closed")
        if not samples:
            return []
        n = len(samples)
        ptrs = (ctypes.c_void_p * n)()
        lens_arr = (ctypes.c_size_t * n)()
        total = 0
        for i, s in enumerate(samples):
            if s:
                ptrs[i] = ctypes.cast(ctypes.c_char_p(s), ctypes.c_void_p)
            lens_arr[i] = len(s)
            total += len(s)
        outbuf = (ctypes.c_ubyte * total)()
        got = self._lib._decrypt_samples_par(
            self._handle, ptrs, lens_arr, n, outbuf
        )
        if got != total:
            raise TemariError(
                f"decrypt_samples_par returned {got} (expected {total})"
            )
        out = ctypes.string_at(outbuf, total)
        results = [None] * n
        off = 0
        for i, s in enumerate(samples):
            l = len(s)
            results[i] = out[off:off + l]
            off += l
        return results

    # ------------------------------------------------------------------ #
    # streaming
    # ------------------------------------------------------------------ #
    def stream(self, batch_size=256):
        """Create a streaming decryptor over this template.

        Samples submitted incrementally are decrypted in the background and
        returned in submission order. The stream clones the template, so this
        handle may be closed afterwards.
        """
        if self._handle is None:
            raise TemariError("handle already closed")
        h = self._lib._stream_new(self._handle, int(batch_size))
        if not h:
            raise TemariError("stream_new failed")
        return StreamDecryptor(h, self._lib)


# ---------------------------------------------------------------------- #
# streaming decryptor
# ---------------------------------------------------------------------- #
class StreamDecryptor:
    """Incremental parallel decryption with in-order results.

    Submit encrypted samples as they arrive, then receive plaintexts in
    submission order. Blocking at the library level; wrap in a thread for
    async (`async for plain in s.aiter()` uses asyncio.to_thread).
    """

    def __init__(self, handle, lib=None):
        self._h = handle
        self._lib = lib or load()

    @classmethod
    def from_json(cls, json_data, lib=None, batch_size=256):
        """Build a stream directly from a 40020-style JSON template."""
        t = Temari.from_json(json_data, lib=lib)
        try:
            return t.stream(batch_size)
        finally:
            t.close()  # the stream cloned the template; safe to release

    def submit(self, sample):
        """Submit one encrypted sample (blocks on internal backpressure)."""
        if self._h is None:
            raise TemariError("stream closed")
        n = len(sample)
        src = (ctypes.c_ubyte * n).from_buffer_copy(sample)
        self._lib._stream_submit(self._h, src, n)

    def _next_optional(self):
        """Block for the next plaintext (in order). Returns bytes, or None
        once the stream is closed and everything is consumed."""
        if self._h is None:
            return None
        cap = 1 << 16  # sample capacity; grown on overflow
        while True:
            out = (ctypes.c_ubyte * cap)()
            n = self._lib._stream_next(self._h, out, cap)
            if n == 0:
                return None
            if n < cap:
                return ctypes.string_at(out, n)
            cap *= 2  # larger sample than guessed capacity: retry with more room

    def next(self):
        """Block for the next plaintext (in order). Raises StopIteration when
        the stream is closed and everything is consumed."""
        v = self._next_optional()
        if v is None:
            raise StopIteration
        return v

    def try_next(self):
        """Non-blocking probe: returns bytes when a plaintext is ready,
        None when none is pending yet; raises StopIteration when closed."""
        if self._h is None:
            raise StopIteration
        cap = 1 << 16
        while True:
            out = (ctypes.c_ubyte * cap)()
            got = ctypes.c_size_t(0)
            r = self._lib._stream_try_next(self._h, out, cap, ctypes.byref(got))
            if r == 1:
                if got.value < cap:
                    return ctypes.string_at(out, got.value)
                cap *= 2
                continue
            if r == 0:
                return None
            raise StopIteration

    def finish(self):
        """Close the input side; already-submitted samples still drain."""
        if self._h is not None:
            self._lib._stream_finish(self._h)

    def close(self):
        """Destroy the stream (safe to call multiple times)."""
        h, self._h = getattr(self, "_h", None), None
        if h:
            self._lib._stream_destroy(h)

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __iter__(self):
        return self

    def __next__(self):
        return self.next()

    async def aiter(self):
        """Async iterator (asyncio): one background pump thread drains the
        blocking stream into a bounded asyncio.Queue (semaphore-tracked free
        slots -> pump blocks on full instead of raising QueueFull). Async
        throughput matches the blocking path."""
        import threading
        loop = asyncio.get_running_loop()
        maxq = 16
        queue = asyncio.Queue(maxsize=maxq)
        space = threading.Semaphore(maxq)  # free slots in the queue
        sentinel = object()

        def pump():
            # batch plaintexts so the cross-thread handoff is amortized
            CHUNK = 64
            try:
                batch = []
                while True:
                    v = self._next_optional()
                    if v is None:
                        break
                    batch.append(v)
                    if len(batch) >= CHUNK:
                        space.acquire()  # block when the queue is full
                        loop.call_soon_threadsafe(queue.put_nowait, batch)
                        batch = []
                if batch:
                    space.acquire()
                    loop.call_soon_threadsafe(queue.put_nowait, batch)
            finally:
                space.acquire()
                loop.call_soon_threadsafe(queue.put_nowait, sentinel)

        threading.Thread(target=pump, daemon=True).start()
        while True:
            item = await queue.get()
            space.release()
            if item is sentinel:
                break
            for p in item:
                yield p


# ---------------------------------------------------------------------- #
# library loading
# ---------------------------------------------------------------------- #
class Library:
    """ctypes binding to libtemari with all FFI entry points bound."""

    def __init__(self, path):
        try:
            self._cdll = ctypes.CDLL(path)
        except OSError as e:  # pragma: no cover - depends on platform
            raise TemariError(f"cannot load libtemari from {path}: {e}") from e
        self.path = path

        c = self._cdll
        c.tmpl_from_json.restype = ctypes.c_void_p
        c.tmpl_from_json.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
        c.tmpl_destroy.argtypes = [ctypes.c_void_p]
        c.decrypt_sample_ffi.restype = ctypes.c_size_t
        c.decrypt_sample_ffi.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
        c.decrypt_samples_par.restype = ctypes.c_size_t
        c.decrypt_samples_par.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]

        c.stream_new.restype = ctypes.c_void_p
        c.stream_new.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        c.stream_submit.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
        c.stream_next.restype = ctypes.c_size_t
        c.stream_next.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
        c.stream_try_next.restype = ctypes.c_int
        c.stream_try_next.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        c.stream_finish.argtypes = [ctypes.c_void_p]
        c.stream_destroy.argtypes = [ctypes.c_void_p]

        self._tmpl_from_json = c.tmpl_from_json
        self._tmpl_destroy = c.tmpl_destroy
        self._decrypt_sample_ffi = c.decrypt_sample_ffi
        self._decrypt_samples_par = c.decrypt_samples_par
        self._stream_new = c.stream_new
        self._stream_submit = c.stream_submit
        self._stream_next = c.stream_next
        self._stream_try_next = c.stream_try_next
        self._stream_finish = c.stream_finish
        self._stream_destroy = c.stream_destroy


_LOADED = {}


def load(path=None):
    """Load (and cache) the libtemari cdylib. ``path=None`` -> default path.

    If no prebuilt/bundled library exists for the current platform and a
    `cargo` toolchain is available, the bundled Rust source (temari/_src) is
    compiled on demand into ``~/.cache/temari/lib/`` — so un-precompiled
    platforms (e.g. macOS x86_64, Windows arm64) work too.
    """
    path = path or default_library_path()
    if not path or not os.path.exists(path):
        built = _auto_build_library()
        if built:
            path = built
    if not path or not os.path.exists(path):
        raise TemariError(
            "no libtemari found for this platform. Options: install the "
            "standard wheel (Linux x86_64/arm64, Windows x86_64, macOS arm64), "
            "or build it yourself: `cargo build --release` in the temari repo "
            "(Rust required), then set TEMARI_LIB to the artifact."
        )
    lib = _LOADED.get(os.path.abspath(path))
    if lib is None:
        lib = Library(path)
        _LOADED[os.path.abspath(path)] = lib
    return lib


def _auto_build_library():
    """Compile the bundled Rust source (temari/_src) with cargo into a user
    cache dir for an un-precompiled platform. Returns the built cdylib path,
    or None if there is no cargo / no bundled source / the build fails."""
    key = _platform_key()
    if not key:
        return None
    name = ("temari.dll" if key.startswith("windows")
            else "libtemari.dylib" if key.startswith("macos") else "libtemari.so")
    cache = os.path.join(os.path.expanduser("~"), ".cache", "temari", "lib", key)
    out = os.path.join(cache, name)
    if os.path.exists(out):
        return out
    cargo = shutil.which("cargo")
    if not cargo:
        return None
    here = os.path.dirname(os.path.abspath(__file__))
    src = os.path.join(here, "_src")
    if not os.path.isfile(os.path.join(src, "Cargo.toml")):
        return None
    # build in the cache so we never write into site-packages
    build_dir = os.path.join(os.path.expanduser("~"), ".cache", "temari", "src")
    if os.path.isdir(build_dir):
        shutil.rmtree(build_dir, ignore_errors=True)
    shutil.copytree(src, build_dir)
    try:
        subprocess.check_call(
            [cargo, "build", "--release",
             "--manifest-path", os.path.join(build_dir, "Cargo.toml")],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, OSError):
        return None
    artifact = os.path.join(build_dir, "target", "release", name)
    if not os.path.exists(artifact):
        return None
    os.makedirs(cache, exist_ok=True)
    shutil.copy2(artifact, out)
    return out