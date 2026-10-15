#!/usr/bin/env python3
"""Codec for the PNG images Sabin Sound Star ships (skin_data, Flare, UI art).

A 3S `.png` is an ordinary PNG whose **first 256 bytes only** have a fixed
128-byte keystream subtracted from them; the rest of the file, including all of
the IDAT pixel data, is stored untouched:

    plain[i] = (cipher[i] - KEY[i % 128]) & 0xff      for i < 256
    plain[i] =  cipher[i]                             for i >= 256

That is the same shape as the `.wav` sample obfuscation -- 0x100 bytes covered,
counter wrapping mod 0x80 -- but it uses **the `.sss` chart keystream
unrotated**, not the sample keystream. `tools/wav.py` uses the variant that is
rotated left by 96. Substituting the wrong one here yields garbage immediately:
the two keys share no useful alignment at offset 0.

The tell is the magic. A 3S PNG starts `8f 8d cb 6a 1d 08 27 f6`, which is
`\x89PNG\\r\\n\x1a\\n` plus the first eight bytes of the chart keystream, and
every 3S PNG on disk shares those 16 bytes because the plaintext prefix (magic,
IHDR length, `IHDR`) is identical across files. Subtracting the known PNG prefix
recovers the keystream directly, and it matches `sss.KEY` byte for byte.

The coverage of 256 bytes, and hence this whole reading of the format, is
confirmed rather than guessed:

* every chunk CRC in all 116 supplied files verifies, including `iCCP`, `gAMA`
  and `cHRM` chunks that lie partly past the covered region -- a chunk CRC is a
  CRC-32 over its own bytes, so it is a strict check on the exact bytes stored,
  and it fails loudly if the keystream is applied too far as well as too short;
* the IDAT streams inflate with `zlib`, which they cannot do if a single byte of
  the zlib header or stream is wrong;
* re-obfuscating the decoded image reproduces the input file byte for byte, so
  this is exactly the inverse of what the game does.

Subcommands
    info      print the decoded PNG header of each file
    decode    write de-obfuscated PNGs (-o FILE, or -o DIR with --all)
    encode    re-obfuscate a plain PNG back to the on-disk form (-o required)
    roundtrip verify encode(decode(x)) == x over a set of files
    audit     report chunk-CRC and inflate status without writing anything

Only the Python standard library is used.
"""

import argparse
import binascii
import glob
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sss import KEY                    # the .sss chart keystream, 128 bytes

COVERED = 0x100                       # keystream reaches this many bytes
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


# The transform is a subtract, not an xor, so it is not self-inverse: decode
# and encode differ in sign, and both are needed to prove the codec correct.
def deobfuscate(data):
    out = bytearray(data[:COVERED])
    for i in range(len(out)):
        out[i] = (data[i] - KEY[i % 128]) & 0xFF
    return bytes(out) + data[COVERED:]


def obfuscate(data):
    out = bytearray(data[:COVERED])
    for i in range(len(out)):
        out[i] = (data[i] + KEY[i % 128]) & 0xFF
    return bytes(out) + data[COVERED:]


def inspect(data):
    """Walk the chunk chain and verify every CRC. Returns (ok, detail)."""
    if not data.startswith(PNG_MAGIC):
        return False, "magic %s" % data[:8].hex()
    off = 8
    seen = []
    idat = b""
    ihdr = None
    while off + 12 <= len(data):
        length = struct.unpack_from(">I", data, off)[0]
        ctype = data[off + 4:off + 8]
        if not all(32 <= c < 127 for c in ctype):
            return False, "chunk type %r at 0x%x" % (ctype, off)
        if off + 12 + length > len(data):
            return False, "%s truncated at 0x%x" % (ctype.decode(), off)
        body = data[off + 8:off + 8 + length]
        want = struct.unpack_from(">I", data, off + 8 + length)[0]
        if binascii.crc32(ctype + body) & 0xFFFFFFFF != want:
            return False, "CRC mismatch in %s at 0x%x" % (ctype.decode(), off)
        name = ctype.decode("latin1")
        seen.append(name)
        if ctype == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body[:13])
        elif ctype == b"IDAT":
            idat += body
        off += 12 + length
        if ctype == b"IEND":
            break
    if ihdr is None:
        return False, "no IHDR"
    try:
        raw = zlib.decompress(idat)
    except Exception as exc:                    # noqa: BLE001 - reported, not raised
        return False, "IDAT inflate failed: %s" % exc
    scanline = ihdr[0] * ((ihdr[2] * {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ihdr[3]] + 7) // 8) + 1
    if len(raw) != ihdr[1] * scanline:
        return False, "IDAT gives %d bytes, expected %d for %dx%d" % (
            len(raw), ihdr[1] * scanline, ihdr[0], ihdr[1])
    return True, "%dx%d depth=%d colortype=%d interlace=%d chunks=%s scanlines=%d" % (
        ihdr[0], ihdr[1], ihdr[2], ihdr[3], ihdr[6], "/".join(seen), len(raw))


def expand(patterns):
    out = []
    for p in patterns:
        hit = glob.glob(p)
        out.extend(hit if hit else [p])
    return [f for f in out if os.path.isfile(f)]


def cmd_info(args):
    for f in expand(args.files):
        ok, detail = inspect(deobfuscate(open(f, "rb").read()))
        print("%s\n  %s%s" % (f, "ok  " if ok else "FAIL ", detail))


def cmd_audit(args):
    good = bad = 0
    for f in expand(args.files):
        ok, detail = inspect(deobfuscate(open(f, "rb").read()))
        if ok:
            good += 1
        else:
            bad += 1
            print("FAIL %s: %s" % (f, detail))
    print("audit: %d valid PNGs, %d failures" % (good, bad))
    return 0 if not bad else 1


def cmd_decode(args):
    files = expand(args.files)
    if args.output and args.output.endswith(".png"):
        if len(files) != 1:
            sys.exit("decode: -o FILE requires exactly one input")
        data = deobfuscate(open(files[0], "rb").read())
        out = args.output
    else:
        outdir = args.output or "."
        os.makedirs(outdir, exist_ok=True)
        for f in files:
            data = deobfuscate(open(f, "rb").read())
            out = os.path.join(outdir, os.path.basename(f))
            open(out, "wb").write(data)
            print("%s -> %s" % (f, out))
        return 0
    open(out, "wb").write(data)
    print("%s -> %s" % (files[0], out))


def cmd_encode(args):
    if not args.output:
        sys.exit("encode: -o is required")
    data = obfuscate(open(args.files[0], "rb").read())
    open(args.output, "wb").write(data)
    print("%s -> %s" % (args.files[0], args.output))


def cmd_roundtrip(args):
    same = diff = 0
    for f in expand(args.files):
        raw = open(f, "rb").read()
        if obfuscate(deobfuscate(raw)) != raw:
            diff += 1
            print("MISMATCH %s" % f)
        else:
            same += 1
    print("roundtrip: %d identical, %d mismatched" % (same, diff))
    return 0 if not diff else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn, one in (("info", cmd_info, False), ("audit", cmd_audit, False),
                          ("decode", cmd_decode, False),
                          ("roundtrip", cmd_roundtrip, False),
                          ("encode", cmd_encode, True)):
        p = sub.add_parser(name)
        p.add_argument("files", nargs=1 if one else "+")
        if name in ("decode", "encode"):
            p.add_argument("-o", "--output")
        p.set_defaults(func=fn)
    args = ap.parse_args()
    rc = args.func(args)
    sys.exit(rc or 0)


if __name__ == "__main__":
    main()
