#!/usr/bin/env python3
"""Codec for Sabin Sound Star: Renascence Burst .wav samples.

The samples a chart references (the third column of its text header) are not
plain WAV files, but they are only *partially* obfuscated: the game subtracts a
fixed 128-byte keystream from the first 256 bytes of the file and leaves the
rest of the audio untouched.

    plain[i] = (cipher[i] - KEY[i % 128]) & 0xff      for i < 256
    plain[i] =  cipher[i]                             for i >= 256

That is exactly the loop in FUN_004043b0, the sample loader:

    for (i = 0; i < 0x100; i++)
        buf[i] -= (char)key[c], c = (c + 1) & 0x7f;
    mmioOpenA(NULL, &mmioinfo{ fccIOProc = 'MEM ' }, 0x10000);

Two consequences worth spelling out, because both are easy to get wrong:

* The on-disk magic is "WTH]" (0x57 0x54 0x48 0x5d), which is "RIFF" plus the
  first four keystream bytes. It is not a custom container.
* The keystream covers 256 bytes, not 44. Bytes 44..255 are *audio*, so a
  header-only fixup leaves 212 bytes of noise at the start of every sample.

The keystream here is NOT the .sss keystream. It is a distinct 128-byte key
that happens to share 121 of its bytes with the .sss key rotated left by 96;
seven bytes differ (indices 3, 22, 27, 31, 78, 91, 109). Using the rotated
.sss key instead decrypts the header correctly but injects loud clicks into
the audio at exactly those positions, so the key below is the one to use.

Subcommands
    info      print the decoded WAV header of each file
    decode    write de-obfuscated, playable WAV data to stdout (or -o FILE)
    encode    re-obfuscate a plain WAV back to the on-disk form (-o required)
    roundtrip verify encode(decode(x)) == x over a set of files

Only the Python standard library is used.
"""

import argparse
import glob
import json
import struct
import sys

# 128-byte sample keystream, read from the stack-resident initialiser in
# FUN_004043b0 (3s.exe). The compiler stored each byte as a separate dword
# write, so the values below are the low bytes of those immediates.
KEY = [
    0x05, 0x0b, 0x02, 0x17, 0xa1, 0x9b, 0x87, 0x74, 0x0d, 0x3d, 0x1c, 0x56, 0x18, 0x57, 0x02, 0x54,
    0x41, 0x01, 0x02, 0x1f, 0x56, 0x0e, 0x49, 0xa6, 0x23, 0x10, 0x3a, 0x4c, 0x04, 0x07, 0x02, 0x18,
    0x06, 0x3d, 0x7d, 0x23, 0x10, 0xfe, 0x0d, 0xec, 0xe8, 0x10, 0xd4, 0x4c, 0xb8, 0xc5, 0x7e, 0x2e,
    0x0f, 0x01, 0x02, 0x21, 0x24, 0x04, 0x20, 0x12, 0x17, 0x1a, 0xe4, 0x1a, 0x7c, 0x57, 0xde, 0x0e,
    0x05, 0x0b, 0x02, 0x03, 0x3d, 0x29, 0x23, 0x13, 0xd5, 0x06, 0x1c, 0x56, 0x18, 0x57, 0x0c, 0x54,
    0x41, 0x01, 0x02, 0x1f, 0x56, 0x04, 0x03, 0xd8, 0x27, 0x06, 0x3a, 0x60, 0x04, 0x07, 0x02, 0x04,
    0x05, 0x3d, 0x19, 0x23, 0x06, 0x36, 0x1f, 0x24, 0xd3, 0x06, 0x52, 0x06, 0x54, 0xc5, 0x1a, 0x2e,
    0x0f, 0x01, 0x02, 0x21, 0x24, 0x36, 0x1f, 0x11, 0x1f, 0x7e, 0x1c, 0x06, 0x18, 0x57, 0x16, 0x04,
]

# The .sss keystream, for reference only (see docs/WAV.md).
SSS_KEY = [
    0x06, 0x3d, 0x7d, 0x23, 0x10, 0xfe, 0x0d, 0xec, 0xe8, 0x10, 0xd4, 0x4c, 0xb8, 0xc5, 0x7e, 0x2e,
    0x0f, 0x01, 0x02, 0x21, 0x24, 0x04, 0x20, 0x12, 0x17, 0x1a, 0xe4, 0x1a, 0x7c, 0x57, 0xde, 0x0e,
    0x05, 0x0b, 0x02, 0x03, 0x3d, 0x29, 0x23, 0x13, 0xd5, 0x06, 0x1c, 0x56, 0x18, 0x57, 0x02, 0x54,
    0x41, 0x01, 0x02, 0x1f, 0x56, 0x04, 0x03, 0xd8, 0x27, 0x06, 0x3a, 0x06, 0x04, 0x07, 0x02, 0x04,
    0x05, 0x3d, 0x19, 0x23, 0x06, 0x36, 0x1f, 0x24, 0xd3, 0x06, 0x52, 0x06, 0x54, 0x61, 0x1a, 0x2e,
    0x0f, 0x01, 0x02, 0x21, 0x24, 0x36, 0x1f, 0x11, 0x1f, 0x7e, 0x1c, 0x06, 0x18, 0x57, 0x16, 0x04,
    0x05, 0x0b, 0x02, 0x03, 0xa1, 0x9b, 0x87, 0x74, 0x0d, 0x3d, 0x1c, 0x56, 0x18, 0x57, 0x02, 0x54,
    0x41, 0x01, 0x02, 0x1f, 0x56, 0x0e, 0x03, 0xa6, 0x23, 0x10, 0x3a, 0x06, 0x04, 0x07, 0x02, 0x04,
]

COVERED = 0x100  # bytes of the file the game touches


def _xform(data):
    """Add/subtract the keystream over the first COVERED bytes. Self-inverse
    in the sense that decode and encode are the same operation with -/+."""
    out = bytearray(data[:min(COVERED, len(data))])
    rest = data[len(out):]
    return out, rest


def decode(raw):
    """On-disk sample bytes -> plain WAV bytes."""
    out, rest = _xform(raw)
    for i in range(len(out)):
        out[i] = (out[i] - KEY[i % 128]) & 0xff
    return bytes(out) + rest


def encode(plain):
    """Plain WAV bytes -> on-disk sample bytes."""
    out, rest = _xform(plain)
    for i in range(len(out)):
        out[i] = (out[i] + KEY[i % 128]) & 0xff
    return bytes(out) + rest


def header(plain):
    """Decode the canonical WAV header from already-deobfuscated bytes."""
    if len(plain) < 44:
        raise ValueError("short file: %d bytes" % len(plain))
    if plain[:4] != b"RIFF" or plain[8:16] != b"WAVEfmt ":
        raise ValueError("not a RIFF/WAVE/fmt chunk chain after de-obfuscation")
    riff_size = struct.unpack_from("<I", plain, 4)[0]
    fmt_size = struct.unpack_from("<I", plain, 16)[0]
    fmt, channels, rate, bps_rate, align, bits = struct.unpack_from("<HHIIHH", plain, 20)
    return {
        "riff_size": riff_size,
        "fmt_size": fmt_size,
        "audio_format": fmt,
        "channels": channels,
        "sample_rate": rate,
        "byte_rate": bps_rate,
        "block_align": align,
        "bits_per_sample": bits,
        "data_tag": plain[36:40].decode("latin-1"),
        "data_size": struct.unpack_from("<I", plain, 40)[0],
    }


def expand(paths):
    out = []
    for p in paths:
        m = glob.glob(p)
        out.extend(sorted(m) if m else [p])
    return out


def cmd_info(args):
    for path in expand(args.files):
        plain = decode(open(path, "rb").read())
        h = header(plain)
        h["path"] = path
        if args.json:
            print(json.dumps(h, ensure_ascii=False))
        else:
            print("%s  %d Hz  %d ch  %d bit  fmt=%d  data=%s:%d" % (
                path, h["sample_rate"], h["channels"], h["bits_per_sample"],
                h["audio_format"], h["data_tag"], h["data_size"]))
    return 0


def cmd_decode(args):
    raw = open(args.files[0], "rb").read()
    out = decode(raw)
    if args.output:
        open(args.output, "wb").write(out)
    else:
        sys.stdout.buffer.write(out)
    return 0


def cmd_encode(args):
    if not args.output:
        sys.stderr.write("encode needs -o\n")
        return 2
    plain = open(args.files[0], "rb").read()
    open(args.output, "wb").write(encode(plain))
    return 0


def cmd_roundtrip(args):
    same = diff = 0
    for path in expand(args.files):
        raw = open(path, "rb").read()
        if encode(decode(raw)) != raw:
            diff += 1
            print("MISMATCH %s" % path)
        else:
            same += 1
    print("roundtrip: %d identical, %d mismatched" % (same, diff))
    return 0 if diff == 0 else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("info", help="print decoded WAV headers")
    p.add_argument("files", nargs="+")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_info)

    p = sub.add_parser("decode", help="write a playable WAV")
    p.add_argument("files", nargs=1)
    p.add_argument("-o", "--output")
    p.set_defaults(fn=cmd_decode)

    p = sub.add_parser("encode", help="re-obfuscate a plain WAV")
    p.add_argument("files", nargs=1)
    p.add_argument("-o", "--output", required=True)
    p.set_defaults(fn=cmd_encode)

    p = sub.add_parser("roundtrip", help="verify encode(decode(x)) == x")
    p.add_argument("files", nargs="+")
    p.set_defaults(fn=cmd_roundtrip)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
