#!/usr/bin/env python3
"""EZ2AC: Endless Circulation chart files -- codec, parser, builder.

Covers the three file types EC keeps in its obfuscated container form:

  .ez    note chart            EZFF v6 binary payload
  .ezi   keysound/instrument   `note flag filename` text
  .ini   config / per-song     plain text

All three use the same container codec, recovered from EZ2AC.exe. See
docs/ez2ac/FORMAT.md for the derivation and docs/ez2ac/REVERSE.md for the functions.

    python3 tools/ez2ac.py decode in.ez -o out.ez
    python3 tools/ez2ac.py encode in.ez -o out.ez
    python3 tools/ez2ac.py info in.ez
    python3 tools/ez2ac.py roundtrip '/path/to/Endless Circulation/*.ini'
"""

import argparse
import glob
import os
import struct
import sys

# ---------------------------------------------------------------------------
# EC container codec
# ---------------------------------------------------------------------------
# 512 dwords at DAT_004bf1f0 in EZ2AC.exe; only the low byte of each dword is
# used, because the consumer assigns `(char)*(undefined4 *)(&DAT_004bf1f0 +
# i*4)`. Values above 0xff exist (0x1b8, 0x1f3, ...) and their low bytes are
# what matter.
_EC_TABLE_HEX = (
    "0cf00d284741060717b82a5f2a5a041f09fc08351357034e17033db326082d37"
    "0339084c2e53532c47422a014824090f4c2a354c5a1d58091d6e18013d1f5861"
    "1acf184447b55b4009040f0001322b0ab6500e330206304f400812b33f01085c"
    "153e07507a55513c3f62015e1117470f0e01073c2a0c570e2a5f000f16015459"
    "3e02053642d33650075b05394f0d124e1841423e164f4c090d2d4e0138116108"
    "30626140390359302b0361022e1f13386055182e010040493729393f4735000e"
    "2f0c0801365647051d121e016009093430621d1a4e364a241048011f56570f0e"
    "3b1e5201631c3c191318010c1607112e1eca14bd292b4331285e1b2c0502581d"
    "11a705452b4b1333180c0525060e226359524b22424d4e0847230519062b5715"
    "53042a2d2458592a134f4c5f19612d2e481122150e0e0707550522070e3d3f25"
    "165d51435b4b552e0e225e56340324035d2d11155b502c375b5d2b185e0e075e"
    "3f16610d0e3b1c20542a08293e1b443e1f2657290b4507405f2e5c021563101a"
    "00213b321c062d234512184d24075c595e48232f28132912270c582b0824422c"
    "5e445f054f32294a290d3a55045721585e064522231b353419611c3f0b1d1844"
    "264c542363435b4d044a5b2a5543161f27454314430958045f332c1353023643"
    "1728224144382c341e324b24302a44052539630224060f110921020a0e230a01"
)
EC_KEY = bytes.fromhex(_EC_TABLE_HEX)
assert len(EC_KEY) == 512


def _chunk_spans(n):
    """The alternating 8/16/8/16... spans used by the container transform.

    Mirrors the loop in FUN_0041a58e exactly, including the tail case that
    does not flip the 8/16 toggle.
    """
    spans = []
    s = 0
    toggle = 0
    while s < n:
        if n < s + 8:
            length = n - s
        else:
            if toggle == 0:
                length = 8
            else:
                length = 16
                if n < s + 16:
                    length = n - s
            toggle ^= 1
        spans.append((s, length))
        s += length
    return spans


def ec_decode(data):
    """Container bytes -> payload.

    plain[i] = reversed(data)[i] - EC_KEY[i % 512], then reverse within each
    alternating 8/16 span.
    """
    rev = data[::-1]
    x = bytes((rev[i] - EC_KEY[i % 512]) & 0xFF for i in range(len(rev)))
    out = bytearray(x)
    for s, length in _chunk_spans(len(x)):
        out[s:s + length] = x[s:s + length][::-1]
    return bytes(out)


def ec_encode(payload):
    """Payload -> container bytes. Exact inverse of ec_decode."""
    out = bytearray(payload)
    for s, length in _chunk_spans(len(payload)):
        out[s:s + length] = payload[s:s + length][::-1]
    x = bytes((out[i] + EC_KEY[i % 512]) & 0xFF for i in range(len(out)))
    return x[::-1]


def is_ec_container(data):
    """Heuristic: does this look like EC's obfuscated container form?"""
    if len(data) < 0x9a:
        return False
    return ec_decode(data)[:4] in (b"EZFF",) or b"\r\n" in ec_decode(data)[:200]


# ---------------------------------------------------------------------------
# EZFF payload (EZ2AC v6)
# ---------------------------------------------------------------------------
MAGIC_EZFF = b"EZFF"
MAGIC_EZTR = b"EZTR"
HEADER_SIZE = 0x96
TRACK_HEADER_SIZE = 0x4E
NOTE_SIZE = 11  # v6: 4 position + 1 type + 6 payload

NOTE_TYPE_NAMES = {1: "note", 2: "volume", 3: "bpm", 4: "beats"}


def parse_ezff(buf):
    """Parse an EZFF v6 payload into a dict. Raises ValueError if malformed."""
    if buf[:4] != MAGIC_EZFF:
        raise ValueError("not an EZFF payload (magic %r)" % buf[:4])
    ver = buf[5]
    if ver != 6:
        raise ValueError("unsupported EZFF version %d (this tool handles v6)" % ver)
    hdr = {
        "version": ver,
        "byte4": buf[4],
        "name1": buf[0x06:0x46],
        "name2": buf[0x46:0x86],
        "ticks_per_measure": struct.unpack_from("<H", buf, 0x86)[0],
        "bpm": struct.unpack_from("<f", buf, 0x88)[0],
        "num_tracks": struct.unpack_from("<H", buf, 0x8c)[0],
        "total_ticks": struct.unpack_from("<I", buf, 0x8e)[0],
        "duration": struct.unpack_from("<f", buf, 0x92)[0],
    }
    tracks = []
    off = HEADER_SIZE
    for i in range(hdr["num_tracks"]):
        if buf[off:off + 4] != MAGIC_EZTR:
            raise ValueError("track %d: bad magic %r at 0x%x"
                             % (i, buf[off:off + 4], off))
        num_ticks = struct.unpack_from("<I", buf, off + 0x46)[0]
        data_size = struct.unpack_from("<I", buf, off + 0x4a)[0]
        if data_size % NOTE_SIZE:
            raise ValueError("track %d: data size %d is not a multiple of %d"
                             % (i, data_size, NOTE_SIZE))
        blob = buf[off + TRACK_HEADER_SIZE:off + TRACK_HEADER_SIZE + data_size]
        if len(blob) != data_size:
            raise ValueError("track %d: truncated note data" % i)
        tracks.append({
            "index": i,
            "pad": struct.unpack_from("<H", buf, off + 4)[0],
            "name": buf[off + 6:off + 0x46],
            "num_ticks": num_ticks,
            "notes": [blob[NOTE_SIZE * k:NOTE_SIZE * k + NOTE_SIZE]
                      for k in range(data_size // NOTE_SIZE)],
        })
        off += TRACK_HEADER_SIZE + data_size
    return {"header": hdr, "tracks": tracks, "trailing": buf[off:]}


def build_ezff(chart):
    """Rebuild an EZFF payload from the structure parse_ezff returns."""
    h = chart["header"]
    buf = bytearray(HEADER_SIZE)
    buf[0:4] = MAGIC_EZFF
    buf[4] = h["byte4"]
    buf[5] = h["version"]
    buf[0x06:0x46] = h["name1"][:0x40].ljust(0x40, b"\0")
    buf[0x46:0x86] = h["name2"][:0x40].ljust(0x40, b"\0")
    struct.pack_into("<H", buf, 0x86, h["ticks_per_measure"])
    struct.pack_into("<f", buf, 0x88, h["bpm"])
    struct.pack_into("<H", buf, 0x8c, h["num_tracks"])
    struct.pack_into("<I", buf, 0x8e, h["total_ticks"])
    struct.pack_into("<f", buf, 0x92, h["duration"])
    for t in chart["tracks"]:
        rec = bytearray(TRACK_HEADER_SIZE)
        rec[0:4] = MAGIC_EZTR
        struct.pack_into("<H", rec, 4, t["pad"])
        rec[6:0x46] = t["name"][:0x40].ljust(0x40, b"\0")
        struct.pack_into("<I", rec, 0x46, t["num_ticks"])
        struct.pack_into("<I", rec, 0x4a, NOTE_SIZE * len(t["notes"]))
        buf += rec
        for n in t["notes"]:
            assert len(n) == NOTE_SIZE
            buf += n
    buf += chart.get("trailing", b"")
    return bytes(buf)


def note_fields(raw):
    """Decode one 11-byte v6 note record."""
    pos = struct.unpack_from("<I", raw, 0)[0]
    typ = raw[4]
    d = raw[5:11]
    if typ == 1:
        return {"pos": pos, "type": "note", "sound": d[0], "velocity": d[1],
                "pan": d[2], "zero": d[3],
                "length": struct.unpack_from("<H", d, 4)[0], "raw": raw}
    if typ == 2:
        return {"pos": pos, "type": "volume", "volume": d[0], "raw": raw}
    if typ == 3:
        return {"pos": pos, "type": "bpm",
                "bpm": struct.unpack_from("<f", d, 0)[0], "raw": raw}
    if typ == 4:
        return {"pos": pos, "type": "beats", "beats": d[0], "raw": raw}
    return {"pos": pos, "type": "unknown(%d)" % typ, "raw": raw}


def derived_duration(h):
    """duration == total_ticks / tpm * 4 * 60 / bpm (verified in EC and 3S)."""
    return h["total_ticks"] / h["ticks_per_measure"] * 4 * 60.0 / h["bpm"]


# ---------------------------------------------------------------------------
# .ezi payload: `note flag filename` text, CRLF terminated
# ---------------------------------------------------------------------------
def parse_ezi(buf):
    """-> list of (index, note_name, flag, filename)."""
    out = []
    for line in buf.split(b"\r\n"):
        if not line:
            continue
        parts = line.split(b" ", 2)
        if len(parts) != 3:
            raise ValueError("bad .ezi line %r" % line)
        name, flag, fn = parts[0].decode(), int(parts[1]), parts[2].decode()
        out.append((note_name_to_index(name), name, flag, fn))
    return out


def build_ezi(entries):
    return b"".join(("%s %d %s\r\n" % (n, f, fn)).encode() for _, n, f, fn in entries)


_SEMITONES = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6,
              "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


def note_name_to_index(name):
    """Old-style keysound numbering: index = octave*12 + semitone, max 255."""
    for i in range(len(name), 0, -1):
        head, tail = name[:i], name[i:]
        if head in _SEMITONES and tail.isdigit():
            return int(tail) * 12 + _SEMITONES[head]
    raise ValueError("unparsable note name %r" % name)


def index_to_note_name(index):
    octave, semi = divmod(index, 12)
    return next(k for k, v in _SEMITONES.items() if v == semi) + str(octave)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _out_path(args, default_suffix=".out"):
    if args.output:
        return args.output
    base, ext = os.path.splitext(args.input)
    return base + default_suffix


def cmd_decode(args):
    data = open(args.input, "rb").read()
    payload = ec_decode(data)
    open(_out_path(args, ".plain" + os.path.splitext(args.input)[1]), "wb").write(payload)
    kind = "EZFF v6" if payload[:4] == MAGIC_EZFF else "text"
    print("%s -> %s  (%d bytes, %s)" % (args.input, _out_path(args, ".plain" + os.path.splitext(args.input)[1]), len(payload), kind))


def cmd_encode(args):
    payload = open(args.input, "rb").read()
    open(_out_path(args, ".ec" + os.path.splitext(args.input)[1]), "wb").write(ec_encode(payload))
    print("%s -> %s  (%d bytes, EC container)" % (args.input, _out_path(args, ".ec" + os.path.splitext(args.input)[1]), len(payload)))


def cmd_info(args):
    data = open(args.input, "rb").read()
    payload = ec_decode(data) if args.ec else data
    if payload[:4] == MAGIC_EZFF:
        c = parse_ezff(payload)
        h = c["header"]
        print("%s: EZFF v6" % args.input)
        print("  ticks/measure %d   bpm %.4f   tracks %d   total ticks %d"
              % (h["ticks_per_measure"], h["bpm"], h["num_tracks"], h["total_ticks"]))
        print("  duration %.4f s   (derived %.4f s)"
              % (h["duration"], derived_duration(h)))
        print("  name1 %r  name2 %r" % (h["name1"].split(b"\0")[0], h["name2"].split(b"\0")[0]))
        used = [(t["index"], t["name"].split(b"\0")[0].decode("latin1"), len(t["notes"]))
                for t in c["tracks"] if t["notes"]]
        print("  %d tracks, %d with notes, %d notes total"
              % (len(c["tracks"]), len(used), sum(u[2] for u in used)))
        for i, n, k in used:
            print("    %2d  %-16s %5d" % (i, n, k))
        if c["trailing"]:
            print("  %d trailing bytes" % len(c["trailing"]))
    else:
        try:
            e = parse_ezi(payload)
        except ValueError:
            print("%s: %d bytes, not EZFF and not a .ezi table" % (args.input, len(payload)))
            print(repr(payload[:200].decode("latin1", "replace")))
            return
        print("%s: .ezi keysound table, %d entries, index %d..%d"
              % (args.input, len(e), e[0][0], e[-1][0]))
        for idx, n, f, fn in e[:5]:
            print("    %3d %-4s %d %s" % (idx, n, f, fn))
        print("    ...")
        for idx, n, f, fn in e[-3:]:
            print("    %3d %-4s %d %s" % (idx, n, f, fn))


def cmd_roundtrip(args):
    files = []
    for p in args.input:
        files.extend(sorted(glob.glob(p)) if any(c in p for c in "*?[") else [p])
    ok = bad = 0
    for f in files:
        data = open(f, "rb").read()
        if ec_encode(ec_decode(data)) == data:
            ok += 1
        else:
            bad += 1
            print("MISMATCH %s" % f)
    print("roundtrip: %d identical, %d mismatched" % (ok, bad))
    return 0 if bad == 0 else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("decode", help="EC container -> payload")
    d.add_argument("input")
    d.add_argument("-o", "--output")
    d.set_defaults(func=cmd_decode)

    e = sub.add_parser("encode", help="payload -> EC container")
    e.add_argument("input")
    e.add_argument("-o", "--output")
    e.set_defaults(func=cmd_encode)

    i = sub.add_parser("info", help="decode and describe a file")
    i.add_argument("input")
    i.add_argument("--ec", action="store_true", help="input is in EC container form")
    i.set_defaults(func=cmd_info)

    r = sub.add_parser("roundtrip", help="verify decode/encode is byte-exact")
    r.add_argument("input", nargs="+")
    r.set_defaults(func=cmd_roundtrip)

    args = ap.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
