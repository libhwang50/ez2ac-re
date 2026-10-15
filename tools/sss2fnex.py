"""Convert a 3S `.sss` chart into a chart EZ2AC : FINAL EX can load.

A `.sss` is `[.ezi text][EZFF v6 binary]`. FINAL EX wants the same two halves
separately, but (a) wrapped in the FNEX container with a per-type keystream,
(b) EZFF version 8 with 13-byte note records instead of v6's 11, and (c) an
`.ezi` whose first column is a plain decimal keysound index rather than 3S's
`C#0`-style note name. The end-to-end recipe, and what is still open about
importing a song, is in docs/ez2ac/ADD-A-SONG.md. FINAL EX also expects keysounds as `.ssf` (see
wav2ssf.py) and populates the header's name1 field with the chart's stem.

Usage:
  python3 tools/sss2fnex.py convert <chart.sss> -o <outdir> [--stem NAME]
                                   [--slot A:B ...] [--shift-notes N]
  python3 tools/sss2fnex.py audit <chart.sss>
"""

import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ez2ac
import fnex

SSS_KEY = bytes.fromhex(
    "063d7d2310fe0dece810d44cb8c57e2e0f01022124042012171ae41a7c57de0e"
    "050b02033d292313d5061c56185702544101021f560403d827063a0604070204"
    "053d192306361f24d306520654611a2e0f01022124361f111f7e1c0618571604"
    "050b0203a19b87740d3d1c56185702544101021f560e03a623103a0604070204"
    ""
    ""
    ""
    ""
    ""
    ""
    ""
    ""
    ""
    ""
    ""
    "")


def sss_decrypt(buf):
    return bytes((b - SSS_KEY[i % 128]) & 0xFF for i, b in enumerate(buf))


def split_sss(buf):
    """Return (ezi_text, ezff_binary, sss_key_applied)."""
    plain = sss_decrypt(buf)
    i = plain.find(b"EZFF")
    if i < 0:
        raise ValueError("no EZFF footer")
    return plain[:i], plain[i:]


def convert_chart(chart, stem, slot_map=None, shift_notes=0):
    """v6 chart dict -> v8 chart dict ready for FINAL EX."""
    out = {
        "header": {
            "version": 8,
            "name1": stem.encode("latin1")[:0x40],
            "name2": b"",
            "ticks_per_measure": chart["header"]["ticks_per_measure"],
            "bpm": chart["header"]["bpm"],
            "num_tracks": chart["header"]["num_tracks"],
            "total_ticks": chart["header"]["total_ticks"],
            "duration": chart["header"]["duration"],
        },
        "tracks": [],
        "trailing": b"",
    }
    buckets = {}
    for t in chart["tracks"]:
        idx = (slot_map or {}).get(t["index"], t["index"])
        notes = []
        for raw in t["notes"]:
            pos = struct.unpack_from("<I", raw, 0)[0]
            if raw[4] == 1 and shift_notes:
                pos += shift_notes
                if pos < 0:
                    continue
                nb = bytearray(raw)
                struct.pack_into("<I", nb, 0, pos)
                raw = bytes(nb)
            elif struct.unpack_from("<I", raw, 0)[0] != pos:
                nb = bytearray(raw)
                struct.pack_into("<I", nb, 0, pos)
                raw = bytes(nb)
            notes.append(fnex.upgrade_note_v6_to_v8(raw))
        buckets.setdefault(idx, []).extend(notes)
    for t in chart["tracks"]:
        notes = sorted(buckets.get(t["index"], []),
                       key=lambda r: struct.unpack_from("<I", r, 0)[0])
        out["tracks"].append({"index": t["index"], "name": t["name"],
                              "num_ticks": t["num_ticks"], "notes": notes})
    return out


def convert_ezi(ezi_entries):
    """ez2ac.parse_ezi yields (index, note_name, flag, filename). FINAL EX's
    .ezi puts a plain decimal index in the first column, so emit that."""
    out = [{"index": idx, "flag": flag, "filename": fn}
           for idx, _name, flag, fn in ezi_entries]
    out.sort(key=lambda x: x["index"])
    return out


def cmd_convert(args):
    raw = open(args.src, "rb").read()
    ezi_text, ezff = split_sss(raw)
    stem = args.stem or os.path.splitext(os.path.basename(args.src))[0]
    chart = ez2ac.parse_ezff(ezff)
    ezi = convert_ezi(ez2ac.parse_ezi(ezi_text))
    slot_map = {}
    for spec in args.slot or []:
        a, _, b = spec.partition(":")
        slot_map[int(a)] = int(b)
    v8 = convert_chart(chart, stem, slot_map, args.shift_notes)

    payload_ez = fnex.build_ezff(v8)
    payload_ezi = fnex.build_ezi(ezi)
    os.makedirs(args.out, exist_ok=True)
    ez_path = os.path.join(args.out, stem + ".ez")
    ezi_path = os.path.join(args.out, stem + ".ezi")
    open(ez_path, "wb").write(fnex.fnex_encode(payload_ez, fnex.FNEX_KEY_EZ))
    open(ezi_path, "wb").write(fnex.fnex_encode(payload_ezi, fnex.FNEX_KEY_EZI))

    back = fnex.parse_ezff(fnex.fnex_decode(
        open(ez_path, "rb").read(), fnex.FNEX_KEY_EZ), strict=True)
    n = sum(len(t["notes"]) for t in back["tracks"])
    src_n = sum(len(t["notes"]) for t in chart["tracks"])
    print("%s -> %s" % (args.src, stem))
    print("  keysounds %d (index %d..%d)   notes %d -> %d"
          % (len(ezi), ezi[0]["index"], ezi[-1]["index"], src_n, n))
    print("  v6 -> v8: %d-byte -> 13-byte notes, name1=%r" % (
        11 if chart["header"]["version"] <= 6 else 13,
        back["header"]["name1"].split(b"\0")[0].decode("latin1")))
    print("  verify: re-decode clean, %d notes, %d-byte payload, trailing=%d"
          % (n, len(payload_ez), len(back["trailing"])))
    print("  -> %s (%d bytes), %s (%d bytes)"
          % (ez_path, os.path.getsize(ez_path), ezi_path, os.path.getsize(ezi_path)))
    print("  next: put the .ssf audio in Sound/<song>/ and list it in the .ezi "
          "with a .wav name, as FINAL EX's own charts do.")


def cmd_audit(args):
    ezi_text, ezff = split_sss(open(args.src, "rb").read())
    chart = ez2ac.parse_ezff(ezff)
    ezi = ez2ac.parse_ezi(ezi_text)
    print("%s" % args.src)
    h = chart["header"]
    print("  v%d tpm=%d bpm=%.4f tracks=%d ticks=%d duration=%.3fs"
          % (h["version"], h["ticks_per_measure"], h["bpm"], h["num_tracks"],
             h["total_ticks"], h["duration"]))
    print("  keysounds=%d  playable-lane notes=%d  BG notes=%d"
          % (len(ezi),
             sum(1 for t in chart["tracks"] if 3 <= t["index"] <= 21
                 for x in t["notes"] if x[4] == 1),
             sum(1 for t in chart["tracks"] if t["index"] >= 22
                 for x in t["notes"] if x[4] == 1)))
    for t in chart["tracks"]:
        if t["notes"]:
            print("    slot %2d %-14r notes=%d" % (
                t["index"], t["name"].split(b"\0")[0].decode("latin1"),
                len(t["notes"])))
    maxidx = max(e[0] for e in ezi)
    print("  highest keysound index in use: %d" % maxidx)
    for t in chart["tracks"]:
        for x in t["notes"]:
            if x[4] == 1 and x[5] > maxidx:
                print("    NOTE slot %d references keysound %d, above the table"
                      % (t["index"], x[5]))
                break


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("convert")
    c.add_argument("src")
    c.add_argument("-o", "--out", required=True)
    c.add_argument("--stem")
    c.add_argument("--slot", action="append", metavar="A:B",
                   help="move playable lane A to B (simultaneous, repeatable)")
    c.add_argument("--shift-notes", type=int, default=0, metavar="TICKS")
    c.set_defaults(fn=cmd_convert)
    a = sub.add_parser("audit"); a.add_argument("src"); a.set_defaults(fn=cmd_audit)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
