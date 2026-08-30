// temari.js — browser/JS bindings for the temari FairPlay SAMPLE-AES cdylib
// compiled to WebAssembly (wasm32-unknown-unknown).
//
// Build the wasm first:
//   rustup target add wasm32-unknown-unknown
//   cargo build --release --target wasm32-unknown-unknown
//   # -> target/wasm32-unknown-unknown/release/temari.wasm
//
// Usage:
//   import { loadTemari } from "./temari.js";
//   const temari = await loadTemari("/temari.wasm");
//   const t = temari.fromJson(jsonBytes);   // caller fetches the 40020 JSON
//   const plain = t.decrypt(ctBytes);       // Uint8Array of equal length
//   t.close();
//
// Only single-sample decrypt is available in wasm: the parallel pool uses
// std::thread, which browsers do not provide. decryptPar returns null.

const wasmImports = {
  env: {
    abort: () => { throw new Error("temari wasm: abort"); },
  },
};

async function loadTemari(wasmUrl) {
  let instance;
  if (wasmUrl instanceof WebAssembly.Instance) {
    instance = wasmUrl;
  } else {
    const res = await fetch(wasmUrl);
    const { instance: inst } = await WebAssembly.instantiateStreaming(res, wasmImports);
    instance = inst;
  }
  const e = instance.exports;
  const mem = e.memory;

  // simple bump allocator; grows the linear memory as needed
  let bump = 0x80000; // start above the Rust static data/heap
  const ensure = (bytes) => {
    const needed = bump + bytes;
    if (needed > mem.buffer.byteLength) {
      const pages = Math.ceil((needed - mem.buffer.byteLength) / 65536);
      mem.grow(pages);
    }
  };
  const alloc = (buf) => {
    ensure(buf.byteLength);
    const p = bump;
    bump += buf.byteLength;
    new Uint8Array(mem.buffer, p, buf.byteLength).set(buf);
    return p;
  };

  class Temari {
    constructor(handle) { this._h = handle; }
    // jsonBytes: Uint8Array of a 40020-style JSON response body
    static fromJson(jsonBytes) {
      const jp = alloc(jsonBytes);
      const h = e.tmpl_from_json(jp, jsonBytes.byteLength);
      if (!h) throw new Error("temari: tmpl_from_json failed");
      return new Temari(h);
    }
    decrypt(ctBytes) {
      if (!this._h) throw new Error("temari: closed");
      const cp = alloc(ctBytes);
      const op = alloc(new Uint8Array(ctBytes.byteLength)); // zeroed region
      const n = e.decrypt_sample_ffi(this._h, cp, ctBytes.byteLength, op);
      if (n === 0 || n !== ctBytes.byteLength) return null;
      return new Uint8Array(mem.buffer, op, n).slice(); // copy out
    }
    // parallel batch is unsupported in wasm (no std::thread)
    decryptPar() { return null; }
    close() { if (this._h) { e.tmpl_destroy(this._h); this._h = 0; } }
  }

  return { Temari, instance, exports: e };
}

export { loadTemari };
export default loadTemari;
