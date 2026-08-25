"""pytest for the temari Python package (requires libtemari.so built)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from temari import Temari, TemariError, default_library_path, load  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
TESTDATA = os.path.join(REPO, "tests", "testdata")

ADAM = "1720704575"


def _data(name):
    with open(os.path.join(TESTDATA, f"track_{ADAM}_s1.{name}"), "rb") as f:
        return f.read()


@pytest.fixture(scope="module")
def lib():
    return load()


def test_load_default_path(lib):
    assert os.path.basename(default_library_path()) in (
        "libtemari.so", "libtemari.dll", "temari.dll", "libtemari.dylib")
    assert lib.path


def test_from_json_decrypt_matches_pt(lib):
    t = Temari.from_json(_data("json"), lib=lib)
    try:
        assert t.decrypt(_data("ct")) == _data("pt")
    finally:
        t.close()


def test_from_json_str_and_bytes(lib):
    # accepts both str and bytes
    raw = _data("json")
    a = Temari.from_json(raw, lib=lib)
    b = Temari.from_json(raw.decode("utf-8"), lib=lib)
    try:
        assert a.decrypt(_data("ct")) == b.decrypt(_data("ct"))
    finally:
        a.close()
        b.close()


def test_from_json_invalid(lib):
    with pytest.raises(TemariError):
        Temari.from_json(b"{ not json }", lib=lib)


def test_context_manager(lib):
    with Temari.from_json(_data("json"), lib=lib) as t:
        assert t.decrypt(_data("ct")) == _data("pt")
    # closed after exiting
    with pytest.raises(TemariError):
        t.decrypt(b"x" * 16)


def test_decrypt_par_equals_per_sample(lib):
    t = Temari.from_json(_data("json"), lib=lib)
    try:
        ct = _data("ct")
        chunks = [ct[i:i + 1024] for i in range(0, len(ct), 1024)]
        assert t.decrypt_par(chunks) == [t.decrypt(c) for c in chunks]
    finally:
        t.close()


def test_decrypt_par_empty(lib):
    t = Temari.from_json(_data("json"), lib=lib)
    try:
        assert t.decrypt_par([]) == []
    finally:
        t.close()


def test_all_tracks_via_json():
    """from_json round-trips against golden .pt for every bundled JSON vector."""
    for f in sorted(os.listdir(TESTDATA)):
        if not f.endswith(".json"):
            continue
        adam = f.split("_")[1]
        with open(os.path.join(TESTDATA, f), "rb") as fh:
            t = Temari.from_json(fh.read())
        try:
            ct = open(os.path.join(TESTDATA, f.replace(".json", ".ct")), "rb").read()
            pt = open(os.path.join(TESTDATA, f.replace(".json", ".pt")), "rb").read()
            assert t.decrypt(ct) == pt, f"track {adam}: mismatch"
        finally:
            t.close()

# --------------------------------------------------------------------------- #
# streaming
# --------------------------------------------------------------------------- #
def test_stream_matches_batch(lib):
    ct = _data("ct")
    chunks = [ct[i:i + 1024] for i in range(0, len(ct), 1024)]
    t = Temari.from_json(_data("json"), lib=lib)
    try:
        s = t.stream(batch_size=4)
        for c in chunks:
            s.submit(c)
        s.finish()
        got = list(s)
        s.close()
    finally:
        t.close()
    # compare with per-sample decrypts (batch path already verified elsewhere)
    t2 = Temari.from_json(_data("json"), lib=lib)
    try:
        expected = [t2.decrypt(c) for c in chunks]
    finally:
        t2.close()
    assert got == expected, "stream != per-sample"


def test_stream_async_aiter(lib):
    import asyncio
    ct = _data("ct")
    chunks = [ct[i:i + 1024] for i in range(0, len(ct), 1024)]
    s = Temari.from_json(_data("json"), lib=lib).stream(batch_size=4)
    for c in chunks:
        s.submit(c)
    s.finish()

    async def collect():
        return [p async for p in s.aiter()]

    got = asyncio.run(collect())
    s.close()
    assert len(got) == len(chunks)


def test_stream_try_next(lib):
    ct = _data("ct")
    s = Temari.from_json(_data("json"), lib=lib).stream(batch_size=2)
    s.submit(ct[:1024])
    s.finish()
    data = None
    for _ in range(100):  # poll until ready (coordinator flushes partial batch)
        v = s.try_next()
        if v is not None:
            data = v
            break
    assert data is not None, "try_next never got data"
    try:
        s.try_next()
        assert False, "should raise StopIteration after drain"
    except StopIteration:
        pass
    s.close()
