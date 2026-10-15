"""EZ2AC : FINAL EX (FNEX) container codec, EZFF v8 parser, and .ssf audio codec.

FNEX obfuscates .ez, .ezi and .ini the same way Endless Circulation does --
reverse the file, subtract a 512-byte keystream, then reverse within an
alternating 8/16/8/16... span split -- but it uses a DIFFERENT keystream, and a
different one per file type. The three FNEX tables were recovered from the
512-dword array at file offset 0x1818 (VMA 0x403018) inside Kasaski's
ez2djDecoder binaries in ez2ac-tools/Kasaskis-ez2Tools/FNEX-EncryptTools.
The format writeup, including the record-magic irregularities in shipped charts,
is in docs/ez2ac/FINAL-EX.md.

Usage:
  python3 tools/fnex.py info    <file.ez|.ezi|.ini>
  python3 tools/fnex.py decode  <in> -o <out> [--key ez|ezi|ini]
  python3 tools/fnex.py encode  <in> -o <out> [--key ez|ezi|ini]
  python3 tools/fnex.py roundtrip "<glob> ..."
  python3 tools/fnex.py ezi     <file.ezi>
"""

import argparse
import glob
import os
import struct

# Recovered keystreams (low byte of each dword at 0x403018 in the decoder tools).
# Recovered keystreams (low byte of each dword at 0x403018 in the decoder tools).
FNEX_KEY_EZ = bytes.fromhex(
    "125d94625fa4b5c9a9c0a77a76a21d116e2b6eb544f6c910bfb318dd0323cd2f"
    "cd8d8bf05d63be00b6fdd6e34b0fcb9401854ba8f07c3a7b650b66dc1ed629f2"
    "066fff306055660fd6793ebe33b9ddb1ab6d2a5f15949d4f48b643b463e95f2e"
    "62c6afb4d75e19932e81e20f4ede9079510f2768e74f7768bbc69840789ffd55"
    "02452bebe89e357d8be22d76e129bea75b6f1f6d371461034c506c5c8e836a79"
    "5170ea4a92f2314fd97b2212a67cbc5c2a753bf8801856d9d21e0d8d01b9fc39"
    "d5bc01c8ff073cdff34ba9ca12f1566ee5a12938d2626974026182565b4ace9c"
    "3dd661f6c368424605fd4bb9012088423257928f9f5f3d7749670caab6988a1b"
    "1f9bedb3cdd0ed6475e3d9aa547ad61f90f8138981a2223662006531e071660d"
    "3b4ae439e12dc4920bd9e03e517f860926726b1a36b50206e66563139eb6015c"
    "4e25502e4eacbb060978d2133ad3ae113181a3f5f4fd37ea076ce3d12c9c6c51"
    "357a17aa62965221df36793e6013886185452dad8b5f7c09cc1b3a9657282b43"
    "f95bd154e451d84f18f1375e7782a1213c46f52a94ac70dcc5c0c41e84c0532b"
    "524b5b048747038479f172a31d535964d38eb6334129972471ad617213aeb86f"
    "f01a362268a817e7437db4bb54071dc825326a8fac0fe8c0da071ac066a53269"
    "9d98c773b1660c0a6928896d34edef0f866e82193dbaf61e81c5c22d93ab8800")
FNEX_KEY_EZI = bytes.fromhex(
    "f5ffd39d76f6346d73658d4987638f5903f3df82652269c9811825a087591653"
    "240e7f073a187bfbdc2d7d6c9708475c83b00633e851c84d17b68eb796e42174"
    "3dc13e179f7b4309cc2fcdff322592ac5cded45919f5aa03a79905441831b85b"
    "fc3dc849c09425c57389b10b8ec83b84fba22e85477c5e9fea180312b05e4498"
    "e4783801e8852f7a2872bc4e7e32bc1a6ed308c280563049ef8c9d3300ada0a1"
    "8d0d0fc7bb016acf1edf74af4b2918424e637169f0c3ecb7122989e51c4e6e26"
    "74bdf15a10089b90bc4c5e29c2f53da136b772c0415295cfb995d7754a23624e"
    "e63ac43ddef67e5eb7bd531d812f6d36dda24c0ac88d8655bfe336e8e2100582"
    "723dd40d44c7466fd053a3883f946d1b13562c1b9c18f58e6516ae8203f99d1b"
    "3daea20b7b44a79c5d3735d5ef984a0fd2889659a90e3e55c34ac0b4c362389b"
    "93053bd5b97c87251e4500e547a65e173b354507f167aa39f5382c303325a8af"
    "239dccd6f31c870ee10b3513891a3ea74d4b54067ecab17368a3290710550040"
    "0e718f00e7c0cf24e7061950c6f9ffa457e42d395fb01e52553021b596376a64"
    "d49ae02699e3521e63c9bbe850f52b48165a0d289016c02a21659ddef6b961c6"
    "13a46717ce5c09e61eab5539b42f8070744ee7cee8cb6f518210ba18a372fb23"
    "a25519322b1d5e3d59a97b8f4296d4ae6472feef7a13692cfe97171f99a540d7")
FNEX_KEY_INI = bytes.fromhex(
    "2ec81a481797c81b1fb67525f74df16ba1270a79be3a37021a693fc344a65a3e"
    "66dd5e2b29b7967a399ccabc7c8cd97aa36423542a06eda4cd1b2bd4437d6922"
    "c51afbf3b9893296264240684f5e264b26965574bf5f2258964c6741c044346f"
    "1e626f0123474eb515d6b6bb8abee38fa78fca49cf1b287513c125faa4051602"
    "01d32fc7cabe32bc4b5c88fdcc34a39d51e5d0576b55aec7f8e8704b5888e1f4"
    "fc1eb5bff1f4502e262e472469bd305f7b2d304bc4383143aa0e1ad9a2f280dc"
    "b29e917cad560c4a433ca647ed759ea90891a7d0553957a6401a4128d6d3e9ea"
    "7471cb3394006e7902c4906dd283d435b2002dcb1986ae596593d154774af530"
    "d8d38253b6c0b809c115df4ecc40f853b6884f48a33849fb9208957ef1459333"
    "6489893cdac4b9476085165bd51da4b58ac77ffcd5941380e6aa4fe4fd50aeca"
    "172960cd66616c69b0b8302b1978a078b60a5e59d07ac9a8776e40303e7bd51f"
    "f3188281aab04742aa877d4a5d0acfdb256f1e899f68dd63f1afa9935e916202"
    "211638b61a41212a323f1a70571cfe1e7420db221da7732722e416b319a9da30"
    "07db665e69fc5c63160b158ddd701331947ac0a04d477de64e5f3a5cb4d13832"
    "6b505d81d5db60c50e59430a0a08f98f83dc3e8d587db0294d375a3646f425a3"
    "2901afd2f826a2fd43c5d170ab295b3cb3ac36fc1703b17b80ec20ba28a972bf")
# Other EZ2AC builds, for completeness.
EV_KEY_EZ = bytes.fromhex(
    "646345035c790c32102845433d3e5c4638131733732872011c691f0367366a27"
    "704166787c0d56561b270313015801683450757854480821431b7c5a05690d53"
    "1718312e2e1e6f191e587c351d213c515020405705467924166e294703031704"
    "7819115c0802061465423d7d270828356c060d5e1802237e3d622b7b55234736"
    "4d634a48285b0361141a18014d7c1e7f1c52793402287a6155267d3a6712684f"
    "221b743577000f3b4a620c2935597c624a131c123f334530275c614165637e41"
    "4c217b113c3f17404f33397136571d05615a2c510345757c524c4922350d606b"
    "20391f47575b1729617858737702134d717f6e047854614a67096d2e7d5b1d07"
    "141e140212446c1e1e7021606c06043d516c2947352016133e572e4d4b5d4664"
    "13172d31064f22194c76444b1f1e772d543e6d755852344c78736d3753676b78"
    "3d262c4d33026e521604014447462271720338496a060773665004073e095c03"
    "171760783c1b4e2b080209711b247d7210513c3c733968442f70710d0a294a10"
    "37772c58335b2d5b483f5b77297e3e45096c5046212a1373394a57026f69444b"
    "4b50703a45251d540247156478447a5b73687e00435865735f4d6a353b4a5d4e"
    "613529081845195812260d2c560f16713476111b654c0216733f574a002b6876"
    "312a021005055f746b50087233617079677a1053612746407b667c58151f2128")
EV_KEY_INI = bytes.fromhex(
    "760175530b28324703602c28744175093229705c677e02756e330037704c6b39"
    "1d674b1c2f441e4c1d0c4f654c42566b233e2815666b76593c4d274331745f43"
    "547d2b08793f481b2e27515e7647676a13154b6a4a661c2f291a281710566830"
    "183d2a75376f001415704330295b5702626f0b15774327291d6c713714735125"
    "2f097422025931741a30182144511128247343007629744a05521d1e437e7c0f"
    "62354e671e0f563a2a7529185d627f42077e1f371e49326a02194f507f44277f"
    "216e1e633e653644627f026472522e304b440e1e4069050640180076413b4d53"
    "6b7c625f69476f0f14074e1c2413740f0b63362e5a35640b166729236463236d"
    "204c5a703c3936240c5746162374582167407c255d553b34116278200f447c30"
    "7d4e64774a2555303c08091b023c7e474478080b736f5c304356741d4b392f52"
    "74564b5c69575a657078357443484e404525087c5f5e5114685d424875186767"
    "424f640218150544555269470a16661e57572954666e591b5e5c1e155c060976"
    "55110e1a611d73432e4479633d795a77581140006838186f7c2a7d56302b434e"
    "6620643c09223a08692b320c1b7e5a2c28054b56500316373747642a41520d70"
    "7f3e416a19291125413605731239015a1e42775d280d082f6350630e7824322b"
    "1a7f75484073064d221d5c3d1e6d4278352d2d4e2d3077343f4d1f095d7f7075")
AEIC_KEY = bytes.fromhex(
    "11140d2847291a410028235f2a5a531f09161b051357274e17033d2d26081100"
    "0355214c2e53532c4720293e4824090f4c2a354c5a1d58091d244e443d1f5861"
    "1a5f5f44472f5b4009040f534d322b0a305021330206304f1e0832613f12085c"
    "153e33342655513c3f62545e0750470f0e623f3c550c570e2a5f420f16285459"
    "3e020c36324936502f5b05395d15124e1841423e563f4c550d2d4e22383b6108"
    "30620b40210359302b0336022e1f13386055562e452140493729393f4735630e"
    "2f0c0801365647051d121e30600c2f3430621d1a4e4c4a24104800205657110e"
    "3b1e524e011c3c1d13183e0c3639112e1e30142d29264331285e1b2c0531581d"
    "111105452b4b1333180c6125500e136359524e2c424d4e39472331344c2b5715"
    "53042a2d3e485928134f4c5f524e2d2e48112d150e0e583a5517224e433d3f25"
    "165d51435b4b552e0e3a5e56340324035d0511265b502c375b5d2b455e0e075e"
    "3f16611d0e1f1c20542e08273e1b443e1f265713564507405f2e5c021563101a"
    "00213b321c062d2345121d4d24075c605e48232f281329122716582b1c241e2c"
    "5e445f2e4f32294a290d3a554e5721585e066022271b353419611c3f0b1d1844"
    "264c545e1d245b4d044a5b2a0843161f27454314350958565f33631353023643"
    "1728224138382c341e324b585f5e44202521630a446145112f203221221e0e34")

KEYS = {"ez": FNEX_KEY_EZ, "ezi": FNEX_KEY_EZI, "ini": FNEX_KEY_INI}


def key_for(name):
    """Pick the FNEX keystream by file extension."""
    ext = os.path.splitext(name)[1].lower()
    return {".ez": FNEX_KEY_EZ, ".ezi": FNEX_KEY_EZI, ".ini": FNEX_KEY_INI}[ext]


def _chunk_spans(n):
    spans = []
    s, length = 0, 8
    while s < n:
        e = min(s + length, n)
        spans.append((s, e))
        s = e
        length = 16 if length == 8 else 8
    return spans


def fnex_decode(data, key):
    out = bytes((b - key[i % 512]) & 0xFF for i, b in enumerate(data[::-1]))
    buf = bytearray(out)
    for s, e in _chunk_spans(len(buf)):
        buf[s:e] = buf[s:e][::-1]
    return bytes(buf)


def fnex_encode(payload, key):
    buf = bytearray(payload)
    for s, e in _chunk_spans(len(buf)):
        buf[s:e] = buf[s:e][::-1]
    return bytes(((buf[i] + key[i % 512]) & 0xFF for i in range(len(buf))))[::-1]


# ---------------------------------------------------------------- EZFF v8 ----
# FINAL EX writes version 8. The 0x96-byte file header and the 0x4e-byte track
# header are unchanged from v6, but notes grow from 11 to 13 bytes because the
# keysound index widens from u8 to u16. ez2stuff documents this layout as
# "v7 and later"; FINAL EX's version byte is 8 and the layout is identical.

V8_NOTE_SIZE = 13
HEADER_SIZE = 0x96
TRACK_HEADER_SIZE = 0x4E

NOTE_TYPES = {1: "note", 2: "volume", 3: "bpm", 4: "beats"}

# FINAL EX v8 emits four record magics with an identical 0x4e-byte header
# (magic, u16 pad, 0x40-byte name, u32 numTicks, u32 dataSize). EZTR is by far
# the common one; EZTK / EZMR / ESTR appear between or after the EZTR run. What
# distinguishes them is not established -- names seen inside them are ordinary
# lane labels such as `(1P)Line 6` and `BG 6` -- but all four must be accepted
# or the walk desyncs.
RECORD_MAGICS = (b"EZTR", b"EZTK", b"EZMR", b"ESTR")

# A further minority of shipped charts have a record whose magic reads `>ZTR`
# (0x3e 5a 54 52) -- "EZTR" with its first byte reduced by 7, the same 7 that
# turns up as a short-by-7 dataSize elsewhere in the same files. This looks like
# authoring-tool corruption in the shipped set rather than a real fifth variant.
# It is accepted so the track walk can continue; it is reported as an anomaly.
CORRUPT_MAGICS = (b">ZTR",)
ACCEPTED_MAGICS = RECORD_MAGICS + CORRUPT_MAGICS


def parse_ezff(data, expect_version=None, strict=False):
    """Walk the track table. Notes are fixed-size, so the note count is derived
    from dataSize. A minority of shipped FNEX charts carry a dataSize that is a
    few bytes short of the real note block (an authoring-tool slip, e.g. 864
    where 871 = 67*13 bytes follow); in that case the walk resyncs on the next
    EZTR and records the anomaly in chart['anomalies'] instead of failing.
    """
    if data[:4] != b"EZFF":
        raise ValueError("not an EZFF payload (magic %r)" % data[:4])
    ver = data[5]
    if expect_version is not None and ver != expect_version:
        raise ValueError("format version %d, expected %d" % (ver, expect_version))
    header = {
        "version": ver,
        "name1": data[0x06:0x46],
        "name2": data[0x46:0x86],
        "ticks_per_measure": struct.unpack_from("<H", data, 0x86)[0],
        "bpm": struct.unpack_from("<f", data, 0x88)[0],
        "num_tracks": struct.unpack_from("<H", data, 0x8C)[0],
        "total_ticks": struct.unpack_from("<I", data, 0x8E)[0],
        "duration": struct.unpack_from("<f", data, 0x92)[0],
    }
    nsize = 11 if ver <= 6 else V8_NOTE_SIZE
    tracks = []
    anomalies = []
    off = HEADER_SIZE
    i = 0
    while off + TRACK_HEADER_SIZE <= len(data) and data[off:off + 4] in ACCEPTED_MAGICS:
        if data[off:off + 4] in CORRUPT_MAGICS:
            anomalies.append({"track": i, "declared": None, "actual": None,
                              "what": "corrupt record magic %r"
                                      % data[off:off + 4]})
        num_ticks, data_size = struct.unpack_from("<II", data, off + 0x46)
        base = off + TRACK_HEADER_SIZE
        end = base + data_size
        if data_size % nsize:
            if strict:
                raise ValueError("track %d: dataSize %d not a multiple of %d"
                                 % (i, data_size, nsize))
            nxt = _next_record(data, base)
            if nxt < 0:
                nxt = len(data)
            anomalies.append({"track": i, "declared": data_size,
                              "actual": nxt - base})
            end = base + ((nxt - base) // nsize) * nsize
        elif end < len(data) and data[end:end + 4] != b"EZTR":
            nxt = _next_record(data, end)
            if 0 <= nxt < end + 0x4e and (nxt - base) % nsize == 0:
                anomalies.append({"track": i, "declared": data_size,
                                  "actual": nxt - base})
                end = nxt
        tracks.append({
            "index": i,
            "name": data[off + 6:off + 0x46],
            "num_ticks": num_ticks,
            "notes": [data[base + nsize * j: base + nsize * (j + 1)]
                      for j in range((end - base) // nsize)],
        })
        off = end
        i += 1
    if len(tracks) != header["num_tracks"]:
        anomalies.append({"track": -1, "declared": header["num_tracks"],
                          "actual": len(tracks), "what": "record count"})
    return {"header": header, "tracks": tracks, "trailing": data[off:],
            "anomalies": anomalies}


def _next_record(data, from_off):
    """Next record magic at a position that keeps the note count integral."""
    pos = from_off
    while True:
        pos = _find_magic(data, pos)
        if pos < 0:
            return len(data)
        if (pos - from_off) % 13 == 0 or (pos - from_off) % 11 == 0:
            return pos
        pos += 4


def _find_magic(data, pos):
    best = -1
    for m in ACCEPTED_MAGICS:
        j = data.find(m, pos)
        if j >= 0 and (best < 0 or j < best):
            best = j
    return best


def build_ezff(chart):
    header = chart["header"]
    nsize = 11 if header["version"] <= 6 else V8_NOTE_SIZE
    out = bytearray(b"EZFF")
    out.append(0)
    out.append(header["version"])
    out += header["name1"][:0x40].ljust(0x40, b"\0")
    out += header["name2"][:0x40].ljust(0x40, b"\0")
    out += struct.pack("<HfHI", header["ticks_per_measure"], header["bpm"],
                       header["num_tracks"], header["total_ticks"])
    out += struct.pack("<f", header["duration"])
    for t in chart["tracks"]:
        out += b"EZTR\0\0"
        out += t["name"][:0x40].ljust(0x40, b"\0")
        out += struct.pack("<II", t["num_ticks"], nsize * len(t["notes"]))
        for n in t["notes"]:
            if len(n) != nsize:
                raise ValueError("track %d note is %d bytes, expected %d"
                                 % (t["index"], len(n), nsize))
            out += n
    out += chart.get("trailing", b"")
    return bytes(out)

def note_fields(raw):
    """Decode one note record of either size (11 = v5/v6, 13 = v7/v8)."""
    pos = struct.unpack_from("<I", raw, 0)[0]
    typ = raw[4]
    kind = NOTE_TYPES.get(typ, "type%d" % typ)
    if len(raw) == 11:
        if typ == 1:
            return {"pos": pos, "type": kind, "sound": raw[5], "velocity": raw[6],
                    "pan": raw[7], "pad": raw[8],
                    "length": struct.unpack_from("<H", raw, 9)[0]}
        if typ == 3:
            return {"pos": pos, "type": kind, "bpm": struct.unpack_from("<f", raw, 5)[0]}
        if typ in (2, 4):
            return {"pos": pos, "type": kind, "value": raw[5]}
        return {"pos": pos, "type": kind}
    if len(raw) != V8_NOTE_SIZE:
        raise ValueError("note record is %d bytes" % len(raw))
    if typ == 1:
        return {"pos": pos, "type": kind,
                "sound": struct.unpack_from("<H", raw, 5)[0],
                "velocity": raw[7], "pan": raw[8], "pad": raw[9],
                "length": struct.unpack_from("<H", raw, 10)[0], "tail": raw[12]}
    if typ == 3:
        return {"pos": pos, "type": kind, "bpm": struct.unpack_from("<f", raw, 5)[0]}
    if typ in (2, 4):
        return {"pos": pos, "type": kind, "value": raw[5]}
    return {"pos": pos, "type": kind}


def upgrade_note_v6_to_v8(raw):
    """11-byte v6 record -> 13-byte v8 record. The keysound index widens from
    u8 to u16 and velocity/pan/pad/length shift right by one byte."""
    if len(raw) != 11:
        raise ValueError("expected an 11-byte v6 note, got %d" % len(raw))
    pos, typ = raw[:4], raw[4]
    if typ == 1:
        sound, vel, pan, pad = raw[5], raw[6], raw[7], raw[8]
        length = struct.unpack_from("<H", raw, 9)[0]
        return (pos + b"\x01" + struct.pack("<H", sound)
                + bytes((vel, pan, pad)) + struct.pack("<H", length) + b"\0")
    if typ == 3:
        return pos + b"\x03" + raw[5:9] + b"\0\0\0\0"
    return pos + bytes((typ,)) + raw[5:11] + b"\0\0"


def parse_ezi(buf):
    """FNEX .ezi: `<index> <flag> <filename>` per CRLF line. FINAL EX uses plain
    decimal keysound indices, not EZ2AC EC's C#0-style note names."""
    out = []
    for line in buf.split(b"\r\n"):
        if not line.strip() or line.startswith(b";"):
            continue
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        out.append({"index": int(parts[0]), "flag": int(parts[1]),
                    "filename": parts[2].decode("latin1")})
    return out


def build_ezi(entries):
    return b"\r\n".join(
        b"%d %d %s" % (e["index"], e["flag"], e["filename"].encode("latin1"))
        for e in entries) + b"\r\n"


# ----------------------------------------------------------------- .ssf ------
# FINAL EX keysound audio: an 18-byte header -- the WAV `fmt` chunk body with
# wFormatTag dropped -- followed by raw PCM. Not encrypted.

SSF_HEADER_SIZE = 18


def parse_ssf(buf):
    channels = struct.unpack_from("<H", buf, 0x00)[0]
    rate = struct.unpack_from("<I", buf, 0x02)[0]
    avg_bytes = struct.unpack_from("<I", buf, 0x06)[0]
    block_align = struct.unpack_from("<H", buf, 0x0A)[0]
    bits = struct.unpack_from("<H", buf, 0x0C)[0]
    data_size = struct.unpack_from("<I", buf, 0x0E)[0]
    if data_size != len(buf) - SSF_HEADER_SIZE:
        raise ValueError("ssf: header declares %d PCM bytes, file has %d"
                         % (data_size, len(buf) - SSF_HEADER_SIZE))
    if block_align != channels * bits // 8 or avg_bytes != rate * block_align:
        raise ValueError("ssf: inconsistent header (rate=%d ch=%d bits=%d "
                         "avgbytes=%d blockalign=%d)"
                         % (rate, channels, bits, avg_bytes, block_align))
    return {"channels": channels, "rate": rate, "bits": bits,
            "pcm": buf[SSF_HEADER_SIZE:]}


def build_ssf(channels, rate, bits, pcm):
    block_align = channels * bits // 8
    return struct.pack("<HIIHHI", channels, rate, rate * block_align,
                       block_align, bits, len(pcm)) + pcm


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("decode", "encode"):
        p = sub.add_parser(name)
        p.add_argument("src")
        p.add_argument("-o", "--out", required=True)
        p.add_argument("--key", choices=sorted(KEYS))
        p.set_defaults(fn=cmd_codec)
    p = sub.add_parser("info"); p.add_argument("src"); p.set_defaults(fn=cmd_info)
    p = sub.add_parser("roundtrip"); p.add_argument("globs", nargs="+")
    p.set_defaults(fn=cmd_rt)
    p = sub.add_parser("ezi"); p.add_argument("src"); p.set_defaults(fn=cmd_ezi)
    args = ap.parse_args(argv)
    args.fn(args)


def cmd_codec(args):
    data = open(args.src, "rb").read()
    key = KEYS[args.key] if args.key else key_for(args.src)
    out = (fnex_decode(data, key) if args.cmd == "decode"
           else fnex_encode(data, key))
    open(args.out, "wb").write(out)
    print("%s %s -> %s (%d bytes)" % (args.cmd, args.src, args.out, len(out)))


def cmd_info(args):
    data = open(args.src, "rb").read()
    try:
        key = key_for(args.src)
    except KeyError:
        print("unknown extension for %s" % args.src)
        return
    payload = fnex_decode(data, key)
    ext = os.path.splitext(args.src)[1].lower()
    if ext == ".ez":
        chart = parse_ezff(payload)
        header = chart["header"]
        if chart["anomalies"]:
            for a in chart["anomalies"]:
                print("  NOTE: track %d declares dataSize %d but %d bytes of "
                      "notes follow (resynced)" % (a["track"], a["declared"],
                                                    a["actual"]))
        print(args.src)
        print("  version=%d name1=%r tpm=%d bpm=%.4f tracks=%d ticks=%d duration=%.3fs"
              % (header["version"],
                 header["name1"].split(b"\0")[0].decode("latin1"),
                 header["ticks_per_measure"], header["bpm"], header["num_tracks"],
                 header["total_ticks"], header["duration"]))
        nsize = 11 if header["version"] <= 6 else V8_NOTE_SIZE
        print("  notes=%d (%d-byte records)  trailing=%d"
              % (sum(len(t["notes"]) for t in chart["tracks"]), nsize,
                 len(chart["trailing"])))
        for t in chart["tracks"]:
            if t["notes"]:
                print("    track %2d %-14r notes=%d"
                      % (t["index"], t["name"].split(b"\0")[0].decode("latin1"),
                         len(t["notes"])))
    elif ext == ".ezi":
        entries = parse_ezi(payload)
        print("%s: %d keysounds, index range %d..%d"
              % (args.src, len(entries),
                 min(e["index"] for e in entries), max(e["index"] for e in entries)))
        for e in entries[:6]:
            print("    %4d %d %s" % (e["index"], e["flag"], e["filename"]))
    else:
        print(repr(payload[:200]))


def cmd_rt(args):
    ok = bad = 0
    for g in args.globs:
        for f in sorted(glob.glob(g, recursive=True)):
            try:
                key = key_for(f)
            except KeyError:
                continue
            data = open(f, "rb").read()
            if fnex_encode(fnex_decode(data, key), key) == data:
                ok += 1
            else:
                bad += 1
                print("MISMATCH %s" % f)
    print("roundtrip: %d identical, %d mismatched" % (ok, bad))


def cmd_ezi(args):
    payload = fnex_decode(open(args.src, "rb").read(), FNEX_KEY_EZI)
    for e in parse_ezi(payload):
        print("%4d %d %s" % (e["index"], e["flag"], e["filename"]))


if __name__ == "__main__":
    main()
