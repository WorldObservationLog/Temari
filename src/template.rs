//! Template loading: binary test-vector format + 40020 key-server HTTP client
//! with a minimal hand-rolled JSON parser (std only, no third-party crates).

use crate::rounds::{R1Entry, ST_SIZE, Template};
use std::fs;

pub const CTX_SIZE: usize = 0x8000;

/// Original state-slot offsets (in the 0x2000-entry layout) that the round
/// chain actually touches. `St` is compacted: compact slot `i` holds the value
/// of the original slot `ST_USED[i]` (ST_USED is sorted ascending, so a
/// binary search maps an original offset to its compact index).
pub const ST_USED: &[usize] = &[
    32, 64, 72, 80, 88, 96, 104, 112, 120, 144, 152, 176,
    192, 200, 208, 216, 224, 232, 240, 248, 256, 264, 280, 288,
    304, 336, 344, 352, 360, 368, 376, 384, 392, 400, 408, 416,
    424, 432, 440, 448, 512, 528, 536, 544, 552, 560, 568, 576,
    584, 592, 600, 608, 616, 624, 640, 648, 656, 664, 672, 680,
    688, 696, 704, 720, 728, 736, 744, 752, 760, 768, 776, 784,
    792, 800, 808, 816, 824, 832, 840, 848, 856, 864, 872, 880,
    888, 896, 904, 912, 920, 944, 952, 960, 968, 976, 992, 1000,
    1016, 1024, 1040, 1048, 1056, 1064, 1072, 1088, 1096, 1104, 1120, 1128,
    1136, 1144, 1152, 1160, 1168, 1240, 1248, 1256, 1264, 1272, 1280, 1288,
    1296, 1304, 1312, 1320, 1328, 1336, 1344, 1352, 1360, 1368, 1376, 1384,
    1392, 1400, 1408, 1416, 1424, 1432, 1440, 1448, 1456, 1464, 1472, 1480,
    1496, 1512, 1520, 1528, 1536, 1544, 1552, 1560, 1568, 1576, 1592, 1600,
    1624, 1632, 1640, 1648, 1656, 1664, 1672, 1680, 1688, 1704, 1712, 1720,
    1728, 1736, 1752, 1760, 1768, 1776, 1784, 1792, 1800, 1856, 1888, 1896,
    1904, 1912, 1920,
];

/// Map an original state offset to its compact index, if that slot is used.
fn st_compact_index(old: usize) -> Option<usize> {
    ST_USED.binary_search(&old).ok()
}

/// Load a binary template file produced by gen_testvec.py:
///   ctx[0x8000] | st_init[0x2000 * 4 LE] | rdx u32 | rcx u32 | rax u32 | r9 u32 | rbp u32
///
/// The on-disk state block always holds 0x2000 (8192) u32 entries, but the round
/// chain only touches the `ST_USED` slots, so only those are kept (compacted).
/// The read offset still skips the full on-disk block so the trailing registers
/// are read from the correct position.
pub fn load_binary_template(path: &str) -> Template {
    const FILE_ST_SIZE: usize = 8192; // on-disk state entry count (fixed format)
    let data = fs::read(path).expect("read template");
    assert!(data.len() >= CTX_SIZE + FILE_ST_SIZE * 4 + 20, "template file too short");
    let mut off = 0;
    let ctx = data[off..off + CTX_SIZE].to_vec();
    off += CTX_SIZE;
    let mut st = [0u32; ST_SIZE];
    for (pos, &old) in ST_USED.iter().enumerate() {
        if old >= FILE_ST_SIZE {
            continue;
        }
        st[pos] = u32::from_le_bytes([
            data[off + old * 4],
            data[off + old * 4 + 1],
            data[off + old * 4 + 2],
            data[off + old * 4 + 3],
        ]);
    }
    off += FILE_ST_SIZE * 4; // skip the full on-disk st block (incl. unused high slots)
    let rdx = u32::from_le_bytes(data[off..off + 4].try_into().unwrap());
    let rcx = u32::from_le_bytes(data[off + 4..off + 8].try_into().unwrap());
    let rax = u32::from_le_bytes(data[off + 8..off + 12].try_into().unwrap());
    let r9 = u32::from_le_bytes(data[off + 12..off + 16].try_into().unwrap());
    let rbp = u32::from_le_bytes(data[off + 16..off + 20].try_into().unwrap());
    Template::new(ctx, st, R1Entry { rdx, rcx, rax, r9, rbp })
}

// ---------------------------------------------------------------------------
// Minimal JSON parser (flat object: { "key": value, ... })
// ---------------------------------------------------------------------------

/// Parse a flat JSON object. Keys must be double-quoted strings. Values may be
/// double-quoted strings (with \/ and \\ and \uXXXX escapes handled minimally),
/// integers, or hex-looking strings. Returns a Vec<(String, String)> of raw
/// string values (unquoted).
pub fn parse_flat_json(input: &str) -> Vec<(String, String)> {
    let b = input.as_bytes();
    let mut i = 0;
    let n = b.len();
    let mut out = Vec::new();

    // skip to first '{'
    while i < n && b[i] != b'{' {
        i += 1;
    }
    i += 1; // consume '{'
    while i < n {
        // skip whitespace and commas
        while i < n && (b[i].is_ascii_whitespace() || b[i] == b',' || b[i] == b'{' || b[i] == b'}') {
            i += 1;
        }
        if i >= n {
            break;
        }
        // read key string
        if b[i] != b'"' {
            break;
        }
        i += 1;
        let mut key = Vec::new();
        while i < n && b[i] != b'"' {
            if b[i] == b'\\' && i + 1 < n {
                // handle \" \\ \/ \uXXXX
                i += 1;
                match b[i] {
                    b'"' => key.push(b'"'),
                    b'\\' => key.push(b'\\'),
                    b'/' => key.push(b'/'),
                    b'n' => key.push(b'\n'),
                    b't' => key.push(b'\t'),
                    b'u' => {
                        if i + 4 < n {
                            let hex = &input[i + 1..i + 5];
                            if let Ok(v) = u32::from_str_radix(hex, 16) {
                                // encode as UTF-8 (handle only BMP, non-surrogate)
                                if let Some(c) = char::from_u32(v) {
                                    let mut buf = [0u8; 4];
                                    key.extend_from_slice(c.encode_utf8(&mut buf).as_bytes());
                                }
                            }
                            i += 4;
                        }
                    }
                    _ => {}
                }
            } else {
                key.push(b[i]);
            }
            i += 1;
        }
        i += 1; // consume closing quote
        let key = String::from_utf8_lossy(&key).to_string();

        // skip to ':'
        while i < n && b[i] != b':' {
            i += 1;
        }
        i += 1; // consume ':'

        // skip whitespace
        while i < n && b[i].is_ascii_whitespace() {
            i += 1;
        }

        // read value
        let val = if i < n && b[i] == b'"' {
            i += 1;
            let mut v = Vec::new();
            while i < n && b[i] != b'"' {
                if b[i] == b'\\' && i + 1 < n {
                    i += 1;
                    match b[i] {
                        b'"' => v.push(b'"'),
                        b'\\' => v.push(b'\\'),
                        b'/' => v.push(b'/'),
                        b'n' => v.push(b'\n'),
                        b't' => v.push(b'\t'),
                        b'u' => {
                            if i + 4 < n {
                                let hex = &input[i + 1..i + 5];
                                if let Ok(vv) = u32::from_str_radix(hex, 16) {
                                    if let Some(c) = char::from_u32(vv) {
                                        let mut buf = [0u8; 4];
                                        v.extend_from_slice(c.encode_utf8(&mut buf).as_bytes());
                                    }
                                }
                                i += 4;
                            }
                        }
                        _ => {}
                    }
                } else {
                    v.push(b[i]);
                }
                i += 1;
            }
            i += 1; // consume closing quote
            String::from_utf8_lossy(&v).to_string()
        } else {
            // bare value (number / hex / null / true)
            let start = i;
            while i < n && !b[i].is_ascii_whitespace() && b[i] != b',' && b[i] != b'}' {
                i += 1;
            }
            input[start..i].to_string()
        };
        out.push((key, val));
    }
    out
}

// ---------------------------------------------------------------------------
// base64
// ---------------------------------------------------------------------------

/// Decode standard base64 (RFC 4648 with padding).
pub fn base64_decode(s: &str) -> Vec<u8> {
    let mut out = Vec::new();
    let mut buf: u32 = 0;
    let mut bits = 0;
    for &c in s.as_bytes() {
        let v = if c == b'=' {
            break;
        } else if (b'A'..=b'Z').contains(&c) {
            (c - b'A') as u32
        } else if (b'a'..=b'z').contains(&c) {
            (c - b'a' + 26) as u32
        } else if (b'0'..=b'9').contains(&c) {
            (c - b'0' + 52) as u32
        } else if c == b'+' {
            62
        } else if c == b'/' {
            63
        } else {
            continue;
        };
        buf = (buf << 6) | v;
        bits += 6;
        if bits >= 8 {
            bits -= 8;
            out.push((buf >> bits) as u8);
        }
    }
    out
}

// ---------------------------------------------------------------------------
// 40020 key-server HTTP client
// ---------------------------------------------------------------------------

/// The 263 state slots (offsets within kdContext), from decryption/assets/st_init_0.json.
/// Embedded here so the binary is fully self-contained.
pub const ST_SLOTS: &[u16] = &[
    0x30, 0x40, 0x48, 0x50, 0x58, 0x5a, 0x60, 0x68, 0x70, 0x72, 0x78, 0x80, 0x88, 0x90, 0x96,
    0x98, 0xa0, 0xb0, 0xc0, 0xc8, 0xd0, 0xd8, 0xe0, 0xe8, 0xf0, 0xf8, 0x100, 0x104, 0x108,
    0x112, 0x118, 0x120, 0x130, 0x144, 0x150, 0x152, 0x158, 0x160, 0x168, 0x170, 0x178,
    0x180, 0x188, 0x190, 0x192, 0x198, 0x1a0, 0x1a8, 0x1b0, 0x1b8, 0x1c0, 0x200, 0x208,
    0x210, 0x216, 0x218, 0x220, 0x224, 0x228, 0x230, 0x232, 0x238, 0x240, 0x248, 0x250,
    0x256, 0x258, 0x260, 0x264, 0x268, 0x270, 0x280, 0x288, 0x290, 0x298, 0x2a0, 0x2a8,
    0x2b0, 0x2b8, 0x2c0, 0x2c8, 0x2d0, 0x2d8, 0x2e0, 0x2e8, 0x2f0, 0x2f8, 0x300, 0x304,
    0x308, 0x310, 0x318, 0x320, 0x328, 0x330, 0x336, 0x338, 0x340, 0x344, 0x348, 0x350,
    0x352, 0x358, 0x360, 0x368, 0x370, 0x376, 0x378, 0x380, 0x384, 0x388, 0x390, 0x392,
    0x398, 0x3b0, 0x3b8, 0x3c0, 0x3c8, 0x3d0, 0x3e0, 0x3e8, 0x3f8, 0x400, 0x408, 0x410,
    0x416, 0x418, 0x420, 0x424, 0x428, 0x430, 0x432, 0x440, 0x448, 0x450, 0x460, 0x468,
    0x470, 0x478, 0x480, 0x488, 0x490, 0x4d8, 0x4e0, 0x4e8, 0x4f0, 0x4f8, 0x500, 0x508,
    0x510, 0x512, 0x518, 0x520, 0x528, 0x530, 0x536, 0x538, 0x540, 0x548, 0x550, 0x552,
    0x558, 0x560, 0x568, 0x570, 0x576, 0x578, 0x580, 0x584, 0x588, 0x590, 0x592, 0x598,
    0x5a0, 0x5a8, 0x5b0, 0x5b8, 0x5c0, 0x5c8, 0x5d8, 0x5e8, 0x5f0, 0x5f8, 0x600, 0x608,
    0x610, 0x616, 0x618, 0x620, 0x624, 0x628, 0x638, 0x640, 0x648, 0x656, 0x658, 0x660,
    0x664, 0x668, 0x670, 0x672, 0x678, 0x680, 0x688, 0x690, 0x696, 0x698, 0x6a8, 0x6b0,
    0x6b8, 0x6c0, 0x6c8, 0x6d8, 0x6e0, 0x6e8, 0x6f0, 0x6f8, 0x700, 0x708, 0x720, 0x728,
    0x736, 0x740, 0x752, 0x760, 0x768, 0x770, 0x778, 0x780, 0x792, 0x816, 0x824, 0x872,
    0x912, 0x944, 0x952, 0x960, 0x992, 0x1040, 0x1088, 0x1328, 0x1360, 0x1368, 0x1384,
    0x1408, 0x1416, 0x1424, 0x1432, 0x1440, 0x1448, 0x1456, 0x1480, 0x1512, 0x1528,
    0x1536, 0x1552, 0x1560, 0x1568, 0x1576, 0x1632, 0x1704, 0x1720, 0x1760,
];

/// Build a Template from a 40020-style key-server JSON response body.
///
/// The library does **not** perform any network requests — the caller fetches
/// the JSON themselves (e.g. via their own HTTP client) and passes it here.
/// Expected flat JSON:
/// ```json
/// { "ctx": "<b64>", "state": "<b64>",
///   "rcx": "0x..", "rax": "0x..", "rdx": "0x..", "r9": "0x..", "rbp": "0x.." }
/// ```
pub fn template_from_json(json: &str) -> Result<Template, String> {
    let fields = parse_flat_json(json);
    let mut map = std::collections::HashMap::new();
    for (k, v) in fields {
        map.insert(k, v);
    }
    let ctx_b64 = map.get("ctx").ok_or("no ctx field")?;
    let state_b64 = map.get("state").ok_or("no state field")?;
    let rcx = parse_hex(map.get("rcx").map(|s| s.as_str()).unwrap_or("0x0"))?;
    let rax = parse_hex(map.get("rax").map(|s| s.as_str()).unwrap_or("0x0"))?;
    let rdx = parse_hex(map.get("rdx").map(|s| s.as_str()).unwrap_or("0x0"))?;
    let r9 = parse_hex(map.get("r9").map(|s| s.as_str()).unwrap_or("0x0"))?;
    let rbp = parse_hex(map.get("rbp").map(|s| s.as_str()).unwrap_or("0x0"))?;

    let ctx = base64_decode(ctx_b64);
    if ctx.len() < CTX_SIZE {
        return Err(format!("ctx too short: {}", ctx.len()));
    }
    let st_raw = base64_decode(state_b64);
    if st_raw.len() < 0x2000 {
        return Err(format!("state too short: {}", st_raw.len()));
    }
    let mut st = [0u32; ST_SIZE];
    for &off in ST_SLOTS.iter() {
        let off = off as usize;
        // only keep slots the round chain actually reads (compacted layout)
        if let Some(pos) = st_compact_index(off) {
            let src = 0x2000usize - off;
            if src + 4 <= st_raw.len() {
                st[pos] = u32::from_le_bytes(st_raw[src..src + 4].try_into().unwrap());
            }
        }
    }
    Ok(Template::new(ctx, st, R1Entry { rdx, rcx, rax, r9, rbp }))
}

fn parse_hex(s: &str) -> Result<u32, String> {
    let s = s.trim();
    let s = s.strip_prefix("0x").unwrap_or(s);
    // r9/rbp in the 40020 response are 64-bit pointers; only the low 32 bits matter
    // for the round chain (they are never actually read). Accept up to u64 and truncate.
    let v = u64::from_str_radix(s, 16).map_err(|e| format!("bad hex {s}: {e}"))?;
    Ok(v as u32)
}

