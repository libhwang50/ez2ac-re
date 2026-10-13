#!/usr/bin/env python3
"""Convert between 3S `.sss` charts and EZ2AC `.ez` + `.ezi` pairs.

A `.sss` is an EZ2AC chart with its two halves concatenated into one file:

    [ .ezi payload as text ][ EZFF v6 payload == the .ez file ]

so conversion is a split, not a translation. Both halves are copied verbatim.
Optionally re-wrap them in EZ2AC EC's container codec so EC can load them.

    # .sss -> plain EZ2AC v6 .ez + .ezi
    python3 tools/sss2ez.py split path/to/firestorm_1n.sss -o out/

    # .sss -> EC-container .ez + .ezi (loadable by EZ2AC EC)
    python3 tools/sss2ez.py split path/to/firestorm_1n.sss -o out/ --ec

    # .ez + .ezi -> .sss (proves the split is lossless)
    python3 tools/sss2ez.py combine out/firestorm_1n.ez out/firestorm_1n.ezi -o rt.sss

    # move 3S's slot-8 lane onto EC's slot 10, and drop 3S's 1-measure lead-in
    python3 tools/sss2ez.py split x.sss -o out/ --remap 8:10 --shift -192
"""

import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ez2ac import (MAGIC_EZFF, NOTE_SIZE, build_ezi, build_ezff, ec_decode,
                   ec_encode, note_fields, parse_ezi, parse_ezff)

# 3S chart keystream (128 bytes), from FUN_00444ce0 in 3s.exe.
SSS_KEY = bytes.fromhex(
    "063d7d2310fe0dece810d44cb8c57e2e0f01022124042012171ae41a7c57de0e"
    "050b02033d292313d5061c56185702544101021f560403d827063a0604070204"
    "053d192306361f24d306520654611a2e0f01022124361f111f7e1c0618571604"
    "050b0203a19b87740d3d1c56185702544101021f560e03a623103a0604070204"
)


def sss_decrypt(data):
    return bytes((data[i] - SSS_KEY[i % 128]) & 0xFF for i in range(len(data)))


def sss_encrypt(plain):
    return bytes((plain[i] + SSS_KEY[i % 128]) & 0xFF for i in range(len(plain)))


def split_sss(data):
    """-> (ezi_text, ezff_payload). Locates the footer by validating the parse."""
    plain = sss_decrypt(data)
    off = 0
    while True:
        off = plain.find(MAGIC_EZFF, off)
        if off < 0:
            raise ValueError("no EZFF footer found")
        try:
            chart = parse_ezff(plain[off:])
        except ValueError:
            off += 4
            continue
        if chart["trailing"]:
            off += 4
            continue
        return plain[:off], plain[off:], chart
    raise AssertionError


def apply_transforms(chart, remap=(), shift_notes=0, shift_events=0, retime=False):
    """Return a new chart with lane remaps and tick shifts applied.

    Type-1 notes and the type 2/3/4 control events are shifted separately,
    because 3S and EZ2AC EC disagree about them: 3S puts its control events at
    tick 0 and starts the notes one measure later, EC puts both at tick 192.
    """
    for t in chart["tracks"]:
        new = []
        for raw in t["notes"]:
            pos = struct.unpack_from("<I", raw, 0)[0]
            delta = shift_notes if raw[4] == 1 else shift_events
            pos += delta
            if pos < 0:
                continue
            if pos != struct.unpack_from("<I", raw, 0)[0]:
                nb = bytearray(raw)
                struct.pack_into("<I", nb, 0, pos)
                raw = bytes(nb)
            new.append(raw)
        t["notes"] = new
    for src, dst in remap:
        s = chart["tracks"][src]
        d = chart["tracks"][dst]
        d["notes"] = sorted(d["notes"] + s["notes"], key=lambda r: struct.unpack_from("<I", r, 0)[0])
        s["notes"] = []
    h = chart["header"]
    if retime:
        used = [struct.unpack_from("<I", n, 0)[0] for t in chart["tracks"] for n in t["notes"]]
        if used:
            h["total_ticks"] = max(used)
            h["duration"] = h["total_ticks"] / h["ticks_per_measure"] * 4 * 60.0 / h["bpm"]
    return chart


def set_names(chart, name1=None, name2=None, track_names=None):
    """Write name strings into the EZFF header and/or individual track headers.

    Both header name fields are 0x40 bytes, NUL padded, and are empty in every
    shipped chart we have -- including EZ2AC EC's own. The one human-readable
    label EC does populate is track 0's name (`untitled`).
    """
    def enc(s):
        b = s.encode("latin1")
        if len(b) > 0x40:
            raise ValueError("name %r is %d bytes, max 0x40" % (s, len(b)))
        return b
    if name1 is not None:
        chart["header"]["name1"] = enc(name1)
    if name2 is not None:
        chart["header"]["name2"] = enc(name2)
    for idx, s in (track_names or {}).items():
        chart["tracks"][idx]["name"] = enc(s)
    return chart


def cmd_split(args):
    data = open(args.input, "rb").read()
    ezi_text, ezff, chart = split_sss(data)
    remap = []
    for spec in args.remap:
        a, b = spec.split(":")
        remap.append((int(a), int(b)))
    shift_notes = args.shift_notes
    shift_events = args.shift_events
    track_names = {}
    title = args.title
    if title is not None:
        track_names[0] = title
    for spec in args.track_name:
        idx, _, s = spec.partition(":")
        track_names[int(idx)] = s
    if remap or shift_notes or shift_events or args.retime or track_names \
            or args.name1 is not None or args.name2 is not None:
        chart = apply_transforms(chart, remap, shift_notes, shift_events, args.retime)
        set_names(chart, args.name1, args.name2, track_names)
        ezff = build_ezff(chart)
        if args.rebuild_ezi:
            ezi_text = build_ezi(parse_ezi(ezi_text))
    if args.ec:
        ezff = ec_encode(ezff)
        ezi_text = ec_encode(ezi_text)

    base = args.name or os.path.splitext(os.path.basename(args.input))[0]
    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)
    ez_path = os.path.join(outdir, base + ".ez")
    ezi_path = os.path.join(outdir, base + ".ezi")
    open(ez_path, "wb").write(ezff)
    open(ezi_path, "wb").write(ezi_text)

    h = chart["header"]
    print("%s" % args.input)
    print("  bpm %.4f  ticks/measure %d  tracks %d  total ticks %d  duration %.3f s"
          % (h["bpm"], h["ticks_per_measure"], h["num_tracks"], h["total_ticks"], h["duration"]))
    keysounds = -1 if args.ec else len([l for l in ezi_text.split(b"\r\n") if l])
    print("  keysounds %s  notes %d"
          % (keysounds if keysounds >= 0 else "(wrapped)",
             sum(len(t["notes"]) for t in chart["tracks"])))
    if remap:
        print("  remapped lanes: %s" % ", ".join("%d->%d" % r for r in remap))
    if shift_notes:
        print("  shifted notes %d ticks (%.4f measures)" % (shift_notes, shift_notes / h["ticks_per_measure"]))
    if shift_events:
        print("  shifted control events %d ticks" % shift_events)
    if args.name1 is not None or args.name2 is not None or track_names:
        if args.name1 is not None:
            print("  header name1 -> %r" % args.name1)
        if args.name2 is not None:
            print("  header name2 -> %r" % args.name2)
        for idx in sorted(track_names):
            print("  track %d name -> %r" % (idx, track_names[idx]))
    print("  -> %s  (%d bytes%s)" % (ez_path, len(ezff), ", EC container" if args.ec else ""))
    print("  -> %s (%d bytes%s)" % (ezi_path, len(ezi_text), ", EC container" if args.ec else ""))

    if not args.ec:
        back = parse_ezff(ezff)
        consumed = len(build_ezff(back))
        print("  verify: .ez re-parses, %d bytes in / %d bytes out, %d trailing"
              % (len(ezff), consumed, len(back["trailing"])))
    return 0


def cmd_combine(args):
    ez = open(args.ez, "rb").read()
    ezi = open(args.ezi, "rb").read()
    if args.ez_ec:
        ez = ec_decode(ez)
    if args.ezi_ec:
        ezi = ec_decode(ezi)
    parse_ezff(ez)  # validate
    out = sss_encrypt(ezi + ez)
    if args.output:
        open(args.output, "wb").write(out)
        print("%d bytes -> %s" % (len(out), args.output))
    else:
        sys.stdout.buffer.write(out)
    return 0


def cmd_audit(args):
    """Report how a .sss maps onto EZ2AC lane expectations."""
    data = open(args.input, "rb").read()
    ezi_text, ezff, chart = split_sss(data)
    h = chart["header"]
    print("%s  bpm %.2f  tpm %d  total ticks %d" % (args.input, h["bpm"], h["ticks_per_measure"], h["total_ticks"]))
    for t in chart["tracks"]:
        if not t["notes"]:
            continue
        name = t["name"].split(b"\0")[0].decode("latin1")
        kinds = {}
        for raw in t["notes"]:
            f = note_fields(raw)
            kinds[f["type"]] = kinds.get(f["type"], 0) + 1
        print("  %2d %-14s %5d  %s" % (t["index"], name, len(t["notes"]),
                                       " ".join("%s:%d" % kv for kv in sorted(kinds.items()))))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("split", help=".sss -> .ez + .ezi")
    s.add_argument("input")
    s.add_argument("-o", "--output", help="output directory")
    s.add_argument("--name", help="output basename without extension")
    s.add_argument("--ec", action="store_true", help="wrap outputs in EC's container codec")
    s.add_argument("--remap", action="append", default=[], metavar="SRC:DST",
                   help="move a lane's notes to another track slot (repeatable)")
    s.add_argument("--shift-notes", dest="shift_notes", type=int, default=0, metavar="TICKS",
                   help="shift type-1 notes by N ticks")
    s.add_argument("--shift-events", dest="shift_events", type=int, default=0, metavar="TICKS",
                   help="shift type 2/3/4 control events by N ticks")
    s.add_argument("--retime", action="store_true",
                   help="recompute total_ticks and duration from the notes")
    s.add_argument("--rebuild-ezi", action="store_true",
                   help="re-serialise the keysound table instead of copying it verbatim")
    s.add_argument("--name1", metavar="STR",
                   help="write the 0x40 header name field at offset 0x06")
    s.add_argument("--name2", metavar="STR",
                   help="write the 0x40 header name field at offset 0x46")
    s.add_argument("--track-name", dest="track_name", action="append", default=[],
                   metavar="IDX:STR", help="write a track's name field (repeatable)")
    s.add_argument("--title", metavar="STR",
                   help="shorthand for --track-name 0:STR (the label EC actually uses)")
    s.set_defaults(func=cmd_split)

    c = sub.add_parser("combine", help=".ez + .ezi -> .sss")
    c.add_argument("ez")
    c.add_argument("ezi")
    c.add_argument("-o", "--output")
    c.add_argument("--ez-ec", action="store_true", help=".ez is in EC container form")
    c.add_argument("--ezi-ec", action="store_true", help=".ezi is in EC container form")
    c.set_defaults(func=cmd_combine)

    a = sub.add_parser("audit", help="show what a .sss puts in each track slot")
    a.add_argument("input")
    a.set_defaults(func=cmd_audit)

    args = ap.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
