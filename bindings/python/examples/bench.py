#!/usr/bin/env python3
"""bench.py — temari Python 绑定性能基准 (Linux / Windows 通用)。

测三组:
  [1] 单样本吞吐    整轨(9354 B)逐样本解密, MB/s
  [2] 并行批量吞吐  1 KB/样本, n ∈ {64,256,1024,4096}, MB/s
  [3] 小样本调用开销 16 B 样本, calls/s 与 us/call

运行:
  python3 examples/bench.py [--lib <libtemari.so|temari.dll>] [--testdata DIR]
  # Windows 示例(设置 TEMARI_LIB 指向 temari.dll):
  TEMARI_LIB=C:\\...\\temari.dll python3 examples/bench.py
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.abspath(os.path.join(HERE, ".."))
REPO = os.path.abspath(os.path.join(PKG, "..", ".."))

sys.path.insert(0, PKG)
from temari import Temari, load  # noqa: E402

ADAM = "1720704575"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", default=None, help="cdylib 路径 (默认 TEMARI_LIB 或仓库 target/release)")
    ap.add_argument("--testdata", default=os.path.join(REPO, "tests", "testdata"))
    ap.add_argument("--chunk", type=int, default=1024)
    args = ap.parse_args()

    lib = load(args.lib)
    print(f"# library: {lib.path}")

    tmpl_json = open(os.path.join(args.testdata, f"track_{ADAM}_s1.json"), "rb").read()
    ct = open(os.path.join(args.testdata, f"track_{ADAM}_s1.ct"), "rb").read()
    pt = open(os.path.join(args.testdata, f"track_{ADAM}_s1.pt"), "rb").read()
    t = Temari.from_json(tmpl_json, lib=lib)
    assert t.decrypt(ct) == pt, "decrypt mismatch (wrong .dll/.so?)"
    print(f"# track {ADAM}: {len(ct)} B, decrypt==pt OK")
    print(f"# cores={os.cpu_count()}")

    # ---- [1] single-sample throughput ----
    iters = 3000
    for _ in range(10):  # warmup
        t.decrypt(ct)
    t0 = time.perf_counter()
    for _ in range(iters):
        t.decrypt(ct)
    dt = time.perf_counter() - t0
    mbps = len(ct) * iters / 1e6 / dt
    print(f"\n[1] single-sample ({len(ct)} B): {mbps:8.1f} MB/s")

    # ---- [2] parallel batch throughput ----
    chunk = args.chunk
    # pool of 1 KB chunks from ct (repeat to reach needed counts)
    pool = [ct[i:i + chunk] for i in range(0, len(ct) - chunk + 1, chunk)]
    for n in (64, 256, 1024, 4096):
        samples = [pool[i % len(pool)] for i in range(n)]
        K = {64: 40, 256: 20, 1024: 10, 4096: 4}[n]
        for _ in range(3):  # warmup
            t.decrypt_par(samples)
        t0 = time.perf_counter()
        for _ in range(K):
            t.decrypt_par(samples)
        dt = time.perf_counter() - t0
        mbps = n * chunk * K / 1e6 / dt
        print(f"[2] batch n={n:<5} x {chunk} B: {mbps:8.1f} MB/s")

    # ---- [3] small-sample per-call overhead ----
    s16 = ct[:16]
    N = 200_000
    for _ in range(1000):  # warmup
        t.decrypt(s16)
    t0 = time.perf_counter()
    for _ in range(N):
        t.decrypt(s16)
    dt = time.perf_counter() - t0
    print(f"[3] 16 B sample: {N/dt/1e6:7.2f} M calls/s, {dt/N*1e6:6.2f} us/call")

    # ---- [4] stream: aggregate throughput + first-plaintext latency ----
    NSTREAM = 20000
    def make_chunks():
        return [ct[i:i + chunk] for i in range(0, len(ct) - chunk + 1, chunk)]
    stream_chunks = make_chunks()
    def fill(n):
        return [stream_chunks[i % len(stream_chunks)] for i in range(n)]
    big = fill(NSTREAM)

    # first-plaintext latency (single sample)
    s = t.stream(batch_size=256)
    s.submit(big[0])
    t0 = time.perf_counter()
    p0 = s.next()
    lat = (time.perf_counter() - t0) * 1e3
    s.finish()
    while True:
        try:
            s.next()
        except StopIteration:
            break
    s.close()
    print(f"[4] stream first-plaintext latency: {lat:6.2f} ms (1 sample, batch=256)")

    for b in (16, 64, 256, 1024):
        s = t.stream(batch_size=b)
        for _ in range(3):
            pass
        t0 = time.perf_counter()
        for smp in big:
            s.submit(smp)
        s.finish()
        got = 0
        while True:
            try:
                s.next()
                got += 1
            except StopIteration:
                break
        dt = time.perf_counter() - t0
        s.close()
        print(f"[4] stream batch={b:<4} n={got}: {len(big)*chunk/1e6/dt:8.1f} MB/s")

    # async aiter aggregate
    async def drain_all():
        s = t.stream(batch_size=256)
        for smp in big:
            s.submit(smp)
        s.finish()
        n = 0
        async for _p in s.aiter():
            n += 1
        s.close()
        return n
    import asyncio
    t0 = time.perf_counter()
    n = asyncio.run(drain_all())
    dt = time.perf_counter() - t0
    print(f"[4] stream async aiter batch=256: {n} samples, {len(big)*chunk/1e6/dt:8.1f} MB/s")

    t.close()


if __name__ == "__main__":
    main()