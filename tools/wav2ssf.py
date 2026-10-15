"""3S .wav  <->  EZ2AC FINAL EX .ssf keysound audio converter.

FINAL EX stores keysounds as `.ssf`: an 18-byte header -- the WAV `fmt` chunk
body with `wFormatTag` dropped, plus a trailing u32 PCM byte count -- followed by
raw PCM. It is NOT encrypted.

3S `.wav` files are a normal RIFF/WAVE, but the first 0x100 bytes are obfuscated
with a fixed 128-byte keystream (subtract on the way out, add on the way in).
Renaming a 3S .wav to .ssf produces a file FINAL EX cannot open for two separate
reasons: the bytes are still obfuscated, and the container is WAV rather than
.ssf. This tool fixes both. See docs/ez2ac/FINAL-EX.md section 4.

Usage:
  python3 tools/wav2ssf.py convert <in.wav|.ssf dir> -o <outdir> [--to ssf|wav]
  python3 tools/wav2ssf.py info <file>
  python3 tools/wav2ssf.py verify <dir>            # every .ssf parses and is self-consistent
"""

import argparse
import os
import struct
import sys

# 3S keysound keystream, from FUN_004043b0 in 3s.exe. Applied to the first
# 0x100 bytes only: plain[i] = cipher[i] - K[i % 128].
SSS_WAV_KEY = bytes.fromhex(
    "050b0217a19b87740d3d1c56185702544101021f560e49a623103a4c04070218"
    "063d7d2310fe0dece810d44cb8c57e2e0f01022124042012171ae41a7c57de0e"
    "050b02033d292313d5061c5618570c544101021f560403d827063a6004070204"
    "053d192306361f24d306520654c51a2e0f01022124361f111f7e1c0618571604")

SSF_HEADER_SIZE = 18


def deobfuscate_sss_wav(buf):
    """Undo the 3S keystream on the first 0x100 bytes."""
    out = bytearray(buf[:min(len(buf), 0x100)])
    for i in range(len(out)):
        out[i] = (out[i] - SSS_WAV_KEY[i % 128]) & 0xFF
    return bytes(out) + buf[len(out):]


def obfuscate_sss_wav(buf):
    """Re-apply the 3S keystream (for going back to a 3S .wav)."""
    out = bytearray(buf[:min(len(buf), 0x100)])
    for i in range(len(out)):
        out[i] = (out[i] + SSS_WAV_KEY[i % 128]) & 0xFF
    return bytes(out) + buf[len(out):]


def parse_wav(buf):
    """Return (channels, rate, bits, pcm) for an uncompressed PCM WAV."""
    if buf[:4] != b"RIFF" or buf[8:12] != b"WAVE":
        raise ValueError("not RIFF/WAVE")
    fmt = None
    off = 12
    data = None
    while off + 8 <= len(buf):
        cid = buf[off:off + 4]
        size = struct.unpack_from("<I", buf, off + 4)[0]
        body = buf[off + 8:off + 8 + size]
        if cid == b"fmt ":
            fmt = struct.unpack_from("<HHIIHH", body, 0)
        elif cid == b"data":
            data = body
        off += 8 + size + (size & 1)
    if fmt is None:
        raise ValueError("no fmt chunk")
    tag, channels, rate, _bytesec, align, bits = fmt
    if tag != 1:
        raise ValueError("WAVE_FORMAT_TAG %d: only uncompressed PCM (1) converts" % tag)
    if data is None:
        raise ValueError("no data chunk")
    if align != channels * bits // 8:
        raise ValueError("inconsistent fmt: align=%d channels=%d bits=%d" % (align, channels, bits))
    return channels, rate, bits, data


def build_wav(channels, rate, bits, pcm):
    align = channels * bits // 8
    fmt = struct.pack("<HHIIHH", 1, channels, rate, rate * align, align, bits)
    body = (b"WAVEfmt " + struct.pack("<I", len(fmt)) + fmt
            + b"data" + struct.pack("<I", len(pcm)) + pcm)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def parse_ssf(buf):
    if len(buf) < SSF_HEADER_SIZE:
        raise ValueError("too short for an .ssf header")
    channels = struct.unpack_from("<H", buf, 0x00)[0]
    rate = struct.unpack_from("<I", buf, 0x02)[0]
    avg = struct.unpack_from("<I", buf, 0x06)[0]
    align = struct.unpack_from("<H", buf, 0x0A)[0]
    bits = struct.unpack_from("<H", buf, 0x0C)[0]
    size = struct.unpack_from("<I", buf, 0x0E)[0]
    if size != len(buf) - SSF_HEADER_SIZE:
        raise ValueError("header declares %d PCM bytes, file has %d"
                         % (size, len(buf) - SSF_HEADER_SIZE))
    if align != channels * bits // 8 or avg != rate * align:
        raise ValueError("inconsistent header: rate=%d ch=%d bits=%d avg=%d align=%d"
                         % (rate, channels, bits, avg, align))
    return channels, rate, bits, buf[SSF_HEADER_SIZE:]


def build_ssf(channels, rate, bits, pcm):
    align = channels * bits // 8
    return struct.pack("<HIIHHI", channels, rate, rate * align, align, bits,
                       len(pcm)) + pcm


def load_any(path):
    """Read an audio file in any of the three dialects and return its parts."""
    buf = open(path, "rb").read()
    if buf[:4] == b"RIFF":
        return parse_wav(buf), "wav"
    head = deobfuscate_sss_wav(buf)
    if head[:4] == b"RIFF":
        return parse_wav(head), "sss-wav-obfuscated"
    try:
        return parse_ssf(buf), "ssf"
    except ValueError:
        raise ValueError("%s: not a WAV, an obfuscated 3S WAV, or a valid .ssf" % path)


def cmd_convert(args):
    src = args.src
    files = []
    if os.path.isdir(src):
        for name in sorted(os.listdir(src)):
            p = os.path.join(src, name)
            if os.path.isfile(p):
                files.append(p)
    else:
        files = [src]
    os.makedirs(args.out, exist_ok=True)
    done = {}
    for p in files:
        stem = os.path.splitext(os.path.basename(p))[0]
        try:
            (ch, rate, bits, pcm), kind = load_any(p)
        except ValueError as e:
            print("  SKIP %s" % e)
            done["skipped"] = done.get("skipped", 0) + 1
            continue
        if args.to == "ssf":
            out, ext = build_ssf(ch, rate, bits, pcm), ".ssf"
        else:
            plain = build_wav(ch, rate, bits, pcm)
            out, ext = (obfuscate_sss_wav(plain) if args.obfuscate_wav else plain), ".wav"
        op = os.path.join(args.out, stem + ext)
        open(op, "wb").write(out)
        key = (kind, ext)
        done[key] = done.get(key, 0) + 1
    print("converted to %s:" % args.to)
    for (kind, ext), n in sorted(done.items()):
        print("   %-22s -> %s x%d" % (kind, ext, n))


def cmd_info(args):
    (ch, rate, bits, pcm), kind = load_any(args.src)
    print("%s  [%s]" % (args.src, kind))
    print("  channels=%d rate=%d bits=%d pcm_bytes=%d duration=%.3fs"
          % (ch, rate, bits, len(pcm), len(pcm) / float(rate * ch * bits // 8)))


def cmd_verify(args):
    ok = bad = 0
    for name in sorted(os.listdir(args.src)):
        p = os.path.join(args.src, name)
        if not os.path.isfile(p) or not name.lower().endswith(".ssf"):
            continue
        try:
            parse_ssf(open(p, "rb").read())
            ok += 1
        except ValueError as e:
            bad += 1
            print("  BAD %s: %s" % (name, e))
    print("%s: %d valid .ssf, %d broken" % (args.src, ok, bad))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("convert")
    c.add_argument("src")
    c.add_argument("-o", "--out", required=True)
    c.add_argument("--to", choices=["ssf", "wav"], default="ssf")
    c.add_argument("--obfuscate-wav", action="store_true",
                   help="re-apply the 3S keystream when writing .wav")
    c.set_defaults(fn=cmd_convert)
    i = sub.add_parser("info"); i.add_argument("src"); i.set_defaults(fn=cmd_info)
    v = sub.add_parser("verify"); v.add_argument("src"); v.set_defaults(fn=cmd_verify)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
