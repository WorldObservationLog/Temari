#!/usr/bin/env python3
"""json_decrypt.py — 使用 temari Python 包的完整示例。

演示 **调用方负责网络** 的新模型:
  1. 调用方用 urllib 从 40020 key server 拉取 JSON 响应体
  2. Temari.from_json(json) 解析为模板(库不做任何网络请求)
  3. decrypt / decrypt_par 解密

默认自动拉起仓库 mock 40020,对 10 条测试轨做 from_json 全流程验证,
并逐字节对比已知明文。也可用 `--json` 指定本地 JSON 模板文件(离线)。

运行(需已 `cargo build --release` 构建 libtemari.so):

    cd bindings/python
    python3 examples/json_decrypt.py [--server 127.0.0.1:40020] [--no-mock]
"""
import argparse
import os
import subprocess
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.abspath(os.path.join(HERE, ".."))
REPO = os.path.abspath(os.path.join(PKG, "..", ".."))
TESTDATA = os.path.join(REPO, "tests", "testdata")
MOCK = os.path.join(REPO, "tools", "temari-decrypt", "tests", "mock_key_server.py")

sys.path.insert(0, PKG)
from temari import Temari  # noqa: E402

TRACKS = {
    "1720704575": "skd://itunes.apple.com/p683167073/c23",
    "1720704582": "skd://itunes.apple.com/p683167040/c6",
    "1720704586": "skd://itunes.apple.com/p683167043/c6",
    "1720704833": "skd://itunes.apple.com/p683167041/c6",
    "1720704841": "skd://itunes.apple.com/p683166958/c23",
    "1720704847": "skd://itunes.apple.com/p683167009/c6",
    "1720704989": "skd://itunes.apple.com/p683167008/c6",
    "1720704998": "skd://itunes.apple.com/p683167044/c23",
    "1720705006": "skd://itunes.apple.com/p683167074/c23",
    "1720705190": "skd://itunes.apple.com/p683166957/c6",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="127.0.0.1:40020")
    ap.add_argument("--no-mock", action="store_true", help="不自动拉起 mock 40020")
    ap.add_argument("--json", default=None, help="本地 JSON 模板文件(离线, 跳过网络)")
    args = ap.parse_args()

    mock = None
    if args.json is None and not args.no_mock:
        mock = subprocess.Popen(
            [sys.executable, MOCK, "40020"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        wait_port(args.server, timeout=10)

    try:
        if args.json:
            run_local(args.json)
        else:
            run_network(args.server)
        print("JSON-DECRYPT: PASS")
    finally:
        if mock:
            mock.terminate()


def fetch_json(server, adam_id, uri):
    """调用方负责网络:从 40020 拉 JSON 响应体(库本身不联网)。"""
    url = f"http://{server}/?adamId={urllib.parse.quote(adam_id)}&uri={urllib.parse.quote(uri)}"
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.read()


def run_network(server):
    for adam, uri in TRACKS.items():
        body = fetch_json(server, adam, uri)          # 网络在这里
        t = Temari.from_json(body)                     # 库只解析
        ct = open(os.path.join(TESTDATA, f"track_{adam}_s1.ct"), "rb").read()
        pt = open(os.path.join(TESTDATA, f"track_{adam}_s1.pt"), "rb").read()
        assert t.decrypt(ct) == pt, f"track {adam}: mismatch"
        t.close()
    print(f"[network] from_json: {len(TRACKS)} tracks PASS (caller-side HTTP)")

    # 并行批量
    t = Temari.from_json(fetch_json(server, "1720704575", TRACKS["1720704575"]))
    ct = open(os.path.join(TESTDATA, "track_1720704575_s1.ct"), "rb").read()
    pt = open(os.path.join(TESTDATA, "track_1720704575_s1.pt"), "rb").read()
    chunks = [ct[i:i + 1024] for i in range(0, len(ct), 1024)]
    plains = t.decrypt_par(chunks)
    assert plains == [t.decrypt(c) for c in chunks]
    t.close()
    print(f"[network] decrypt_par: {len(chunks)} samples PASS")

    # 上下文管理器
    with Temari.from_json(fetch_json(server, "1720704575", TRACKS["1720704575"])) as t:
        assert t.decrypt(ct) == pt
    print("[network] context-manager PASS")

    # 流式:增量提交,按序取回
    t = Temari.from_json(fetch_json(server, "1720704575", TRACKS["1720704575"]))
    expected = [t.decrypt(c) for c in chunks]
    s = t.stream(batch_size=4)
    for c in chunks:
        s.submit(c)
    s.finish()
    got = list(s)
    s.close(); t.close()
    assert got == expected
    print("[network] stream: ordered plaintexts PASS")


def run_local(json_path):
    """离线:读本地 JSON 模板文件(40020 响应体或 gen_testvec 产物)。"""
    with open(json_path, "rb") as f:
        body = f.read()
    t = Temari.from_json(body)
    base = os.path.splitext(os.path.basename(json_path))[0]
    # 若有同名 .ct/.pt 则校验
    ct_p = os.path.join(os.path.dirname(json_path), base + ".ct")
    pt_p = os.path.join(os.path.dirname(json_path), base + ".pt")
    if os.path.exists(ct_p) and os.path.exists(pt_p):
        ct = open(ct_p, "rb").read()
        pt = open(pt_p, "rb").read()
        assert t.decrypt(ct) == pt, "local JSON decrypt mismatch"
        print(f"[local] {json_path}: decrypt==pt PASS")
    t.close()


def wait_port(host_port, timeout=10.0):
    """阻塞直到 host:port 可连接(mock 40020 就绪)。"""
    import socket
    import time
    host, _, port = host_port.rpartition(":")
    port = int(port)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host or "127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(0.1)
    raise SystemExit(f"server {host_port} did not become ready in {timeout}s")


if __name__ == "__main__":
    main()