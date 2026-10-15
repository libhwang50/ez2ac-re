#!/usr/bin/env python3
"""
Sabin Sound Star : Renascence Burst  --  .sss chart container codec.

See ../FORMAT.md for the full specification; this file is the reference
implementation of it.

Container = [text header: instrument/sample table, CRLF-terminated lines]
          + [EZFF binary footer: EZ2AC v6 compiled chart, 11-byte notes]
and the whole file is obfuscated with a fixed 128-byte *subtract* keystream.
That is obfuscation, not encryption -- see FORMAT.md section 1.

    plaintext[i]  = (ciphertext[i] - KEY[i % 128]) & 0xff
    ciphertext[i] = (plaintext[i] + KEY[i % 128]) & 0xff

Usage:
    python3 sss.py decode    FILE.sss [-o out.txt]   # human readable dump
    python3 sss.py decode    FILE.sss --raw          # decrypted bytes to stdout
    python3 sss.py json      FILE.sss [-o out.json]  # lossless JSON
    python3 sss.py encode    IN.json     OUT.sss     # rebuild (byte-exact)
    python3 sss.py roundtrip GLOB                    # verify byte-exact re-encode

`roundtrip` is the regression test: parse -> build must reproduce the input
byte-for-byte. Note records keep their 6 payload bytes verbatim (see the
_pack_data comment) because rebuilding them from decoded fields alone is lossy.
"""
import argparse, json, re, struct, sys, glob, os

# --- keystream, recovered from 3s.exe FUN_00444ce0 (chart loader) -----------
KEY = bytes([
    0x06, 0x3d, 0x7d, 0x23, 0x10, 0xfe, 0x0d, 0xec, 0xe8, 0x10, 0xd4, 0x4c, 0xb8, 0xc5, 0x7e, 0x2e,
    0x0f, 0x01, 0x02, 0x21, 0x24, 0x04, 0x20, 0x12, 0x17, 0x1a, 0xe4, 0x1a, 0x7c, 0x57, 0xde, 0x0e,
    0x05, 0x0b, 0x02, 0x03, 0x3d, 0x29, 0x23, 0x13, 0xd5, 0x06, 0x1c, 0x56, 0x18, 0x57, 0x02, 0x54,
    0x41, 0x01, 0x02, 0x1f, 0x56, 0x04, 0x03, 0xd8, 0x27, 0x06, 0x3a, 0x06, 0x04, 0x07, 0x02, 0x04,
    0x05, 0x3d, 0x19, 0x23, 0x06, 0x36, 0x1f, 0x24, 0xd3, 0x06, 0x52, 0x06, 0x54, 0x61, 0x1a, 0x2e,
    0x0f, 0x01, 0x02, 0x21, 0x24, 0x36, 0x1f, 0x11, 0x1f, 0x7e, 0x1c, 0x06, 0x18, 0x57, 0x16, 0x04,
    0x05, 0x0b, 0x02, 0x03,
    0xa1, 0x9b, 0x87, 0x74, 0x0d, 0x3d, 0x1c, 0x56, 0x18, 0x57, 0x02, 0x54,
    0x41, 0x01, 0x02, 0x1f, 0x56, 0x0e, 0x03, 0xa6, 0x23, 0x10, 0x3a, 0x06, 0x04, 0x07, 0x02, 0x04,
])
assert len(KEY) == 128

MAGIC_EZFF = b'EZFF'
MAGIC_EZTR = b'EZTR'
EZFF_HDR = 0x96
TRACK_HDR = 0x4E
NOTE_SIZE = 11          # 3S always uses EZ2AC v5/v6 sized notes
MAX_TRACKS = 64
MAX_EVENTS = 0x400      # game clamps to 1024 events / 0x9008-byte track block

NOTE_TYPES = {1: 'note', 2: 'volume', 3: 'bpm', 4: 'beats'}
TYPE_OF = {v: k for k, v in NOTE_TYPES.items()}

PITCH = {'C': 0, 'C#': 1, 'D': 2, 'D#': 3, 'E': 4, 'F': 5, 'F#': 6,
         'G': 7, 'G#': 8, 'A': 9, 'A#': 10, 'B': 11}
NAME_OF = {v: k for k, v in PITCH.items()}
SAMPLE_RE = re.compile(r'^([A-G]#?)(\d{1,2}) (\d+) (.*)$')


def decrypt(data: bytes) -> bytes:
    return bytes((c - KEY[i % 128]) & 0xFF for i, c in enumerate(data))


def encrypt(data: bytes) -> bytes:
    return bytes((c + KEY[i % 128]) & 0xFF for i, c in enumerate(data))


def sample_index(note: str) -> int:
    """'C#3' -> 3*12 + 1.  Matches FUN_004456c0 (letter table + '#' + octave)."""
    m = re.fullmatch(r'([A-G]#?)(\d{1,2})', note)
    if not m:
        raise ValueError(f'bad note name {note!r}')
    return int(m.group(2)) * 12 + PITCH[m.group(1)]


def sample_name(idx: int) -> str:
    return f'{NAME_OF[idx % 12]}{idx // 12}'


# ---------------------------------------------------------------- parsing ---
def parse(data: bytes) -> dict:
    plain = decrypt(data)
    cut = plain.find(MAGIC_EZFF)
    if cut < 0:
        raise ValueError('EZFF footer not found (wrong key or not a chart?)')
    text = plain[:cut]
    foot = plain[cut:]

    instruments = []
    for line in text.decode('latin-1').split('\r\n'):
        m = SAMPLE_RE.match(line)
        if m:
            instruments.append({'note': m.group(1) + m.group(2),
                                'index': sample_index(line.split(' ')[0]),
                                'flag': int(m.group(3)),
                                'file': m.group(4)})

    h = foot[:EZFF_HDR]
    hdr = {
        'magic': h[:4].decode(),
        'byte4': h[4],                                   # 0x04 = 0
        'fmtver': h[5],                                  # 0x05 = 6 -> EZ2AC v6 note format
        'name1': h[0x06:0x46].rstrip(b'\0').decode('latin-1'),   # 64 bytes @0x06
        'name2': h[0x46:0x86].rstrip(b'\0').decode('latin-1'),   # 64 bytes @0x46
        'ticks_per_measure': struct.unpack_from('<H', h, 0x86)[0],   # always 192 = 0xc0
        'initial_bpm': struct.unpack_from('<f', h, 0x88)[0],
        'num_tracks': struct.unpack_from('<H', h, 0x8c)[0],
        'total_ticks': struct.unpack_from('<I', h, 0x8e)[0],
        'duration': struct.unpack_from('<f', h, 0x92)[0],            # seconds of audio
    }
    hdr['tick_rate'] = hdr['total_ticks'] / hdr['duration'] if hdr['duration'] else 0.0

    tracks = []
    p = EZFF_HDR
    for i in range(hdr['num_tracks']):
        magic = foot[p:p + 4]
        if magic != MAGIC_EZTR:
            raise ValueError(f'track {i}: expected EZTR, got {magic!r} @ {hex(p)}')
        t = {'index': i,
             'magic': magic.decode(),
             'pad': struct.unpack_from('<H', foot, p + 4)[0],
             'name': foot[p + 6:p + 0x46].rstrip(b'\0').decode('latin-1'),
             'num_ticks': struct.unpack_from('<I', foot, p + 0x46)[0],
             'data_size': struct.unpack_from('<I', foot, p + 0x4a)[0]}
        p += TRACK_HDR
        notes = []
        for n in range(t['data_size'] // NOTE_SIZE):
            rec = foot[p + n * NOTE_SIZE: p + (n + 1) * NOTE_SIZE]
            pos, typ = struct.unpack_from('<IB', rec, 0)
            d = rec[5:11]
            ev = {'pos': pos, 'type': NOTE_TYPES.get(typ, typ), 'raw': d.hex()}
            if typ == 1:
                ev.update(sound=d[0], velocity=d[1], pan=d[2], unk=d[3],
                          length=struct.unpack_from('<H', d, 4)[0])
            elif typ == 2:
                ev['volume'] = d[0]
            elif typ == 3:
                ev['bpm'] = struct.unpack_from('<f', d, 0)[0]
            elif typ == 4:
                ev['beats'] = d[0]
            notes.append(ev)
        t['notes'] = notes
        p += t['data_size']
        tracks.append(t)

    return {'text': text, 'instruments': instruments, 'header': hdr,
            'tracks': tracks, 'footer_tail': foot[p:], 'plain': plain}


# ------------------------------------------------------------- serialising ---
def _pack_data(ev):
    """Re-derive the 6 data bytes from decoded fields (used for hand-written charts)."""
    t = ev['type']
    if t == 'note':
        return (bytes([ev['sound'] & 0xFF, ev['velocity'] & 0xFF, ev['pan'] & 0xFF,
                       ev.get('unk', 0) & 0xFF]) + struct.pack('<H', ev.get('length', 0)))
    if t == 'volume':
        return bytes([ev['volume'] & 0xFF]) + b'\0' * 5
    if t == 'bpm':
        return struct.pack('<f', ev['bpm']) + b'\0' * 2
    if t == 'beats':
        return bytes([ev['beats'] & 0xFF]) + b'\0' * 5
    raise ValueError(f'no raw bytes and unknown type {t!r}')


def build(c: dict) -> bytes:
    h = c['header']
    foot = bytearray(MAGIC_EZFF)                       # 0x00..0x03
    foot.append(h.get('byte4', 0))                     # 0x04
    foot.append(h.get('fmtver', 6))                    # 0x05  (EZ2AC format version)
    foot += h.get('name1', '').encode('latin-1')[:0x40].ljust(0x40, b'\0')   # 0x06..0x45
    foot += h.get('name2', '').encode('latin-1')[:0x40].ljust(0x40, b'\0')   # 0x46..0x85
    assert len(foot) == 0x86, len(foot)
    foot += b'\0' * (EZFF_HDR - len(foot))             # reserve 0x86..0x95
    struct.pack_into('<H', foot, 0x86, h.get('ticks_per_measure', 192))
    struct.pack_into('<f', foot, 0x88, h.get('initial_bpm', 0.0))
    struct.pack_into('<H', foot, 0x8c, h.get('num_tracks', len(c['tracks'])))
    struct.pack_into('<I', foot, 0x8e, h.get('total_ticks', 0))
    struct.pack_into('<f', foot, 0x92, h.get('duration', 0.0))
    assert len(foot) == EZFF_HDR, len(foot)

    for t in c['tracks']:
        foot += MAGIC_EZTR
        foot += struct.pack('<H', t.get('pad', 0))
        foot += t.get('name', '').encode('latin-1')[:0x40].ljust(0x40, b'\0')
        notes = t.get('notes', [])
        foot += struct.pack('<II', t.get('num_ticks', 0), len(notes) * NOTE_SIZE)
        for ev in notes:
            foot += struct.pack('<IB', ev['pos'], TYPE_OF[ev['type']] if isinstance(ev['type'], str) else ev['type'])
            # byte-exact: the 6 data bytes are copied verbatim; decoded fields are display-only
            foot += bytes.fromhex(ev['raw']) if ev.get('raw') is not None else _pack_data(ev)
    foot += c.get('footer_tail', b'')

    text = c['text'] if isinstance(c.get('text'), bytes) else \
        '\r\n'.join(f"{i['note']} {i['flag']} {i['file']}" for i in c['instruments']).encode('latin-1')
    return encrypt(text + bytes(foot))


# ------------------------------------------------------------------ dumps ---
def tick_str(tick, tpm):
    if not tpm:
        return f'{tick}t'
    m, r = divmod(tick, tpm)
    if r == 0:
        return f'm{m + 1}:1'
    # express remainder as a small fraction of a beat (4/4 assumed, tpm per measure)
    num, den = r * 4, tpm
    from math import gcd
    g = gcd(num, den)
    return f'm{m + 1}:{num // g}+{den // g}'


def dump(c: dict) -> str:
    h, tpm = c['header'], c['header']['ticks_per_measure']
    out = []
    a = out.append
    a(f'; ---- .sss text header ({len(c["text"])} bytes, {len(c["instruments"])} instruments) ----')
    for line in c['text'].decode('latin-1').split('\r\n'):
        a('; ' + line)
    a('')
    a(f'; ---- EZFF footer ----')
    a(f'magic            = {h["magic"]}')
    a(f'byte@0x04        = {h["byte4"]}')
    a(f'fmt version@0x05 = {h["fmtver"]}  (EZ2AC v6)')
    a(f'name1/name2      = {h["name1"]!r} / {h["name2"]!r}')
    a(f'ticks/measure@86 = {h["ticks_per_measure"]}')
    a(f'initial BPM@0x88 = {h["initial_bpm"]}')
    a(f'num_tracks@0x8c  = {h["num_tracks"]}')
    a(f'total_ticks@0x8e = {h["total_ticks"]}  = {h["total_ticks"] // h["ticks_per_measure"]} measures')
    a(f'duration@0x92    = {round(h["duration"], 4)} s   -> {round(h["tick_rate"], 3)} ticks/s'
      f'  (= {h["total_ticks"]} t / {h["ticks_per_measure"]} tpm x 4 beats x 60 / {h["initial_bpm"]} BPM'
      f' = {h["total_ticks"] / h["ticks_per_measure"] * 4 * 60 / h["initial_bpm"]:.3f} s)')
    a('')
    names = {i['index']: i['file'] for i in c['instruments']}
    for t in c['tracks']:
        if not t['notes']:
            continue
        a(f'[track {t["index"]:2}] magic={t["magic"]} pad={t["pad"]} name={t["name"]!r} '
          f'numTicks={t["num_ticks"]} dataSize={t["data_size"]} notes={len(t["notes"])}')
        for ev in t['notes']:
            base = f'  tick {ev["pos"]:6} ({tick_str(ev["pos"], tpm):>8})  {ev["type"]}'
            if ev['type'] == 'note':
                s = names.get(ev['sound'], '?')
                a(f'{base} sound={ev["sound"]:3} ({s}) vel={ev["velocity"]:3} pan={ev["pan"]:3} '
                  f'unk={ev["unk"]} len={ev["length"]}')
            elif ev['type'] == 'volume':
                a(f'{base} volume={ev["volume"]}')
            elif ev['type'] == 'bpm':
                a(f'{base} bpm={round(ev["bpm"], 6)}')
            elif ev['type'] == 'beats':
                a(f'{base} beats={ev["beats"]}')
            else:
                a(f'{base} raw={ev["raw"]}')
        a('')
    return '\n'.join(out)


def to_json_obj(c: dict) -> dict:
    return {'header': {k: v for k, v in c['header'].items() if k != 'magic'},
            'header_magic': c['header']['magic'],
            'text': c['text'].decode('latin-1'),
            'instruments': c['instruments'],
            'tracks': [{k: v for k, v in t.items() if k != 'magic'} for t in c['tracks']],
            'footer_tail': c['footer_tail'].hex()}


def from_json_obj(o: dict) -> dict:
    h = dict(o['header']); h['magic'] = o.get('header_magic', 'EZFF')
    return {'text': o['text'].encode('latin-1'), 'instruments': o.get('instruments', []),
            'header': h, 'tracks': o['tracks'],
            'footer_tail': bytes.fromhex(o.get('footer_tail', ''))}


# ------------------------------------------------------------------- main ---
def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('decode', 'json'):
        s = sub.add_parser(name); s.add_argument('file'); s.add_argument('-o', '--out')
        if name == 'decode':
            s.add_argument('--raw', action='store_true')
    s = sub.add_parser('encode'); s.add_argument('json'); s.add_argument('out')
    s = sub.add_parser('roundtrip'); s.add_argument('glob')
    a = ap.parse_args()

    if a.cmd == 'decode':
        c = parse(open(a.file, 'rb').read())
        out = c['plain'] if a.raw else dump(c)
        (open(a.out, 'w', encoding='utf-8') if a.out else sys.stdout).write(out)
    elif a.cmd == 'json':
        c = parse(open(a.file, 'rb').read())
        txt = json.dumps(to_json_obj(c), indent=1, ensure_ascii=False)
        (open(a.out, 'w', encoding='utf-8') if a.out else sys.stdout).write(txt)
    elif a.cmd == 'encode':
        open(a.out, 'wb').write(build(from_json_obj(json.load(open(a.json, encoding='utf-8')))))
    elif a.cmd == 'roundtrip':
        # Two independent paths must both reproduce the input byte-for-byte:
        #   parse -> build                       (in-memory model)
        #   parse -> to_json_obj -> from_json_obj -> build   (lossless JSON)
        # The JSON path has caught real bugs the in-memory path alone missed.
        ok = bad = 0
        for f in sorted(glob.glob(a.glob, recursive=True)):
            orig = open(f, 'rb').read()
            try:
                c = parse(orig)
                re_enc = build(c)
                json_enc = build(from_json_obj(to_json_obj(c)))
            except Exception as e:
                print(f'FAIL {f}: {e}'); bad += 1; continue
            if re_enc == orig and json_enc == orig:
                ok += 1
            else:
                bad += 1
                which = 'memory' if re_enc != orig else 'json'
                n = next((i for i, (x, y) in enumerate(zip(re_enc, orig)) if x != y),
                         min(len(re_enc), len(orig)))
                print(f'DIFF {f}: {which} path, len {len(re_enc)} vs {len(orig)}, first diff @{hex(n)}')
        print(f'roundtrip: {ok} identical, {bad} mismatched')


if __name__ == '__main__':
    main()
