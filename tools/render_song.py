#!/usr/bin/env python3
"""Render a Sabin Sound Star: Renascence Burst song by auto-playing its chart.

There is no BGM file. A 3S song *is* a render of its chart: every type-1 note on
every track triggers its keysound at its scheduled tick, and the melody lives in
the player lanes (slots 3-21) just as much as in the backing layers (slots
22-39). Rendering only the lanes gives you a dry, half-finished song; rendering
only the backing layers gives you karaoke without the tune. Both are needed, and
they do not overlap -- across the sample set the (tick, sample) pairs shared
between lane slots and backing slots are 0 or 1 per chart, so playing every
track does not double up the melody.

A chart carries its own instrument table, so a render is self-contained: the
`sound` byte of a note indexes the table in the same .sss file, and the table
names the .wav to load. Samples sit next to the chart and are themselves
partially obfuscated, so they go through tools/wav.py before playback.

Usage
-----
    python3 tools/render_song.py path/to/kamui_1n.sss -o kamui_1n.flac
    python3 tools/render_song.py --all path/to/songs -o rendered/
    python3 tools/render_song.py path/to/x.sss --report

Requires numpy and soundfile:  uv venv && uv pip install numpy soundfile

Verified
--------
* Sample resolution: 6786 instrument entries across 36 charts, no duplicate
  indices, and every one of them resolves to a file on disk once lookup is
  case-insensitive (two names differ only by case -- `0-cymbal.wav` on disk is
  `0-CYMBAL.wav` in the table; the game is Windows and does not care).
* `velocity` is genuinely used here, unlike EZ2ON where it is 127 everywhere:
  76% of notes are 127 but 115, 111, 123, 90, 70 and others appear, so it is
  applied as a gain and it changes the mix.
* Lane notes and backing notes never collide, so summing all tracks is safe.

Inferred, not proven
--------------------
* `pan` is a DirectSound balance in 1/100 dB, from the same FUN_00417320:
  `(pan - 64) * 156`, positive attenuating the left channel. 64 is centre, and
  the byte hard-panns beyond roughly +/-40 of centre.
* `velocity` is a dB attenuation rather than an amplitude gain: 0 dB at 127
  falling to -50 dB at 0. 24% of notes sit below 127, and reading it linearly
  put them 5-17 dB too loud -- that is what made keysound volumes sound off.
* Long notes. The `length` field is a tick sustain: 6 for 96% of notes, always
  a multiple of 6, and it never overruns the next note on the same slot
  (98129 shorter, 333 exactly equal, 3 longer). Whether the game sustains the
  sample over that length is NOT established. Default is play-once, matching
  this engine family; `--hold` gates and loops the sample instead.
"""
import argparse
import glob
import io
import os
import sys

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sss  # noqa: E402
import wav as ssswav  # noqa: E402

DEFAULT_RATE = 44100
TAIL_SECONDS = 5.0
FADE_SECONDS = 0.015
DEFAULT_LENGTH = 6          # the "this is a normal note" value of the length field

# The game hands velocity and pan straight to DirectSound, which takes both in
# 1/100 dB. FUN_00417320 is the whole of the volume model:
#
#   FUN_00417320(sample, 0, vel * lanevol[lane] / 0x7f, pan, 1)
#     iVar3 = -(10000 - (param_3 * 10000) / 0x7f);   /* 1/100 dB */
#     if (iVar3 < 0) iVar3 = iVar3 / 2;              /* -> 0 .. -50 dB */
#     iVar1 = (param_4 + -0x40) * 0x9c;              /* (pan-64)*156, 1/100 dB */
#     FUN_00403840(iVar3);   /* vtable +0x3c = IDirectSoundBuffer::SetVolume */
#     FUN_004037a0(iVar1);   /* vtable +0x40 = IDirectSoundBuffer::SetPan    */
#
# So velocity is a dB attenuation, not an amplitude gain: 115 is -4.7 dB (0.58
# amplitude), not 115/127 = 0.91. 24% of notes are not 127, so this dominates
# the mix.
#
# lanevol is DAT_00bdd9e4, a 42-entry per-lane volume table indexed through the
# per-track lane map DAT_00921150. It looks like the per-instrument volume
# control one would hope for, but FUN_00406c30 initialises all 42 entries to
# 0x7f and no shipped code writes it again, so it is a constant 127. The
# instrument table's flag column is dead code as well: FUN_00445b70 evaluates
# "flag != 1 && flag == 2" into a local that is never read.

LANE_VOLUME = 127           # DAT_00bdd9e4[lane], always 127 in the shipped build


def vel_gain(velocity, lane_volume=LANE_VOLUME, linear=False):
    """The game's velocity -> amplitude mapping, integer math and all."""
    v = (velocity * lane_volume) // 127
    if linear:
        return v / 127.0
    cdB = -(10000 - (v * 10000) // 127)
    if cdB < 0:
        cdB = -((-cdB) // 2)          # C truncates toward zero
    return 10.0 ** (cdB / 100.0 / 20.0)


def pan_gains(pan):
    """The game's pan byte -> (left, right) amplitude gains.

    (pan - 64) * 156 is a DirectSound balance in 1/100 dB, so a positive value
    attenuates the LEFT channel and a negative one the RIGHT. It is aggressive:
    pan 96 is +49.9 dB of left attenuation, effectively hard right.
    """
    p = (pan - 0x40) * 0x9c
    left = max(0, p)
    right = max(0, -p)
    return (10.0 ** (-left / 100.0 / 20.0), 10.0 ** (-right / 100.0 / 20.0))


# ------------------------------------------------------------------ samples ---
def load_samples(chart, assets_dir):
    """instrument index -> path, resolved case-insensitively in assets_dir."""
    on_disk = {}
    for fn in os.listdir(assets_dir):
        stem, ext = os.path.splitext(fn)
        if ext.lower() in ('.wav', '.flac', '.ogg', '.mp3'):
            on_disk.setdefault(stem.lower(), os.path.join(assets_dir, fn))
            on_disk.setdefault(fn.lower(), os.path.join(assets_dir, fn))
    out, missing = {}, []
    for ins in chart['instruments']:
        key = os.path.splitext(ins['file'])[0].lower()
        path = on_disk.get(key) or on_disk.get(ins['file'].lower())
        if path is None:
            missing.append(ins['file'])
        else:
            out[ins['index']] = path
    return out, missing


_dur = {}
def sample_seconds(path):
    """Duration in seconds of a (de-obfuscated) sample, cached."""
    if path not in _dur:
        x, sr = sf.read(io.BytesIO(ssswav.decode(open(path, 'rb').read())),
                        dtype='float32', always_2d=True)
        _dur[path] = len(x) / sr
    return _dur[path]


def read_keysound(path, rate):
    """Read a 3S sample: undo the partial keystream, decode, resample to stereo."""
    plain = ssswav.decode(open(path, 'rb').read())
    x, sr = sf.read(io.BytesIO(plain), dtype='float32', always_2d=True)
    if sr != rate:
        n = max(1, int(round(x.shape[0] * rate / sr)))
        idx = np.linspace(0.0, x.shape[0] - 1, n)
        i0 = np.floor(idx).astype(np.int64)
        i1 = np.minimum(i0 + 1, x.shape[0] - 1)
        frac = (idx - i0).astype(np.float32)[:, None]
        x = x[i0] * (1.0 - frac) + x[i1] * frac
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    elif x.shape[1] > 2:
        x = x[:, :2]
    return np.ascontiguousarray(x, dtype=np.float32)


# -------------------------------------------------------------- timing map ---
def tempo_map(chart):
    """[(tick, bpm, beats_per_measure)] sorted by tick, from the control events.

    Every tempo and time-signature event in the sample set sits at tick 0, so
    this degenerates to one constant segment -- but the general form costs
    nothing and keeps the renderer honest about charts that do change tempo.
    """
    bpm, beats = [], []
    for t in chart['tracks']:
        for e in t['notes']:
            if e['type'] == 'bpm':
                bpm.append((e['pos'], e['bpm']))
            elif e['type'] == 'beats':
                beats.append((e['pos'], e['beats']))
    h = chart['header']
    if not bpm:
        bpm = [(0, h['initial_bpm'])]
    seg, seen = [], set()
    for tick, v in sorted(bpm):
        if tick in seen:
            continue
        seen.add(tick)
        b = [x for tk, x in beats if tk <= tick]
        seg.append((tick, v, (b[-1] if b else 4) or 4))
    return seg


def tick_to_seconds(seg, tpm, tick):
    """Piecewise-linear tick -> seconds over the tempo map."""
    cur = 0.0
    prev_tick, prev_bpm, prev_beats = seg[0]
    for i, (t, bpm, beats) in enumerate(seg):
        if tick <= t:
            dt = (t - prev_tick) if i else 0
            cur += dt * 4.0 * (60.0 / prev_bpm) / tpm
            return cur + (tick - t) * 4.0 * (60.0 / bpm) / tpm
        cur += (t - prev_tick) * 4.0 * (60.0 / prev_bpm) / tpm
        prev_tick, prev_bpm, prev_beats = t, bpm, beats
    return cur + (tick - prev_tick) * 4.0 * (60.0 / prev_bpm) / tpm


# ------------------------------------------------------------------ render ---
def render(chart_path, assets_dir=None, rate=DEFAULT_RATE, gain=1.0, normalize=True,
           only=None, use_pan=True, hold=False, tail=TAIL_SECONDS, report=False,
           bed_seconds=10.0, no_bed=False, linear_vel=False):
    data = open(chart_path, 'rb').read()
    chart = sss.parse(data)
    assets_dir = assets_dir or os.path.dirname(os.path.abspath(chart_path))
    table, missing_files = load_samples(chart, assets_dir)
    seg = tempo_map(chart)
    tpm = chart['header']['ticks_per_measure']

    events, unknown_sound, beds = [], 0, []
    for t in chart['tracks']:
        if only is not None and t['index'] not in only:
            continue
        for e in t['notes']:
            if e['type'] != 'note':
                continue
            path = table.get(e['sound'])
            if path is None:
                unknown_sound += 1
                continue
            sec = tick_to_seconds(seg, tpm, e['pos'])
            if bed_seconds and sample_seconds(path) > bed_seconds:
                beds.append((t['index'], e['pos'], os.path.basename(path),
                             sample_seconds(path)))
                if no_bed:
                    continue
            events.append((sec, path, e['velocity'], e['pan'] if use_pan else 64,
                           e['length'], t['index']))

    seconds = chart['header']['duration'] or (
        tick_to_seconds(seg, tpm, chart['header']['total_ticks']))
    n_frames = int(np.ceil((seconds + tail) * rate))
    mix = np.zeros((n_frames, 2), dtype=np.float32)

    cache, used, dropped = {}, 0, 0
    fade = max(1, int(FADE_SECONDS * rate))
    for sec, path, vel, pan, length, slot in events:
        buf = cache.get(path)
        if buf is None:
            try:
                buf = read_keysound(path, rate)
            except Exception as exc:
                missing_files.append('%s (%s)' % (os.path.basename(path), exc))
                buf = cache[path] = np.zeros((0, 2), dtype=np.float32)
            cache[path] = buf
        if buf.shape[0] == 0:
            dropped += 1
            continue
        off = int(round(sec * rate))
        if off >= n_frames:
            dropped += 1
            continue
        if hold and length > DEFAULT_LENGTH:
            want = int(round(length * 4.0 * (60.0 / seg[-1][1]) / tpm * rate))
            if buf.shape[0] < want:                 # sustain: tile, then gate
                reps = -(-want // buf.shape[0])
                buf = np.tile(buf, (reps, 1))[:want]
            else:
                buf = buf[:want]
            env = np.ones((buf.shape[0], 1), dtype=np.float32)
            env[-fade:] *= np.linspace(1.0, 0.0, min(fade, buf.shape[0]))[:, None]
            buf = buf * env
        n = min(buf.shape[0], n_frames - off)
        g = vel_gain(vel, linear=linear_vel)
        gl, gr = pan_gains(pan) if use_pan else (1.0, 1.0)
        mix[off:off + n, 0] += buf[:n, 0] * g * gl
        mix[off:off + n, 1] += buf[:n, 1] * g * gr
        used += 1

    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    if normalize and peak > 0:
        mix *= 0.99 / peak
    mix *= gain
    clipped = int(np.count_nonzero(np.abs(mix) > 1.0))
    np.clip(mix, -1.0, 1.0, out=mix)

    env = np.abs(mix).max(axis=1)
    trail = int(np.argmax(env[::-1] > 1e-6)) if env.size else 0
    if trail:
        mix = mix[:len(mix) - trail + 1]

    stats = dict(
        chart=os.path.basename(chart_path),
        beds=beds,
        events=used, dropped=dropped, keysounds=len({e[1] for e in events}),
        unknown_sound=unknown_sound, missing_files=sorted(set(missing_files)),
        chart_seconds=seconds, rendered_seconds=len(mix) / rate,
        peak=peak, clipped=clipped, tracks=len({e[5] for e in events}),
    )
    if report:
        per = {}
        for sec, path, vel, pan, length, slot in events:
            per[slot] = per.get(slot, 0) + 1
        stats['per_slot'] = dict(sorted(per.items()))
    return mix, rate, stats


def write_audio(path, mix, rate):
    outdir = os.path.dirname(path)
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    ext = os.path.splitext(path)[1].lower().lstrip('.') or 'flac'
    sf.write(path, mix, rate, format=ext.upper() if ext in ('FLAC', 'WAV', 'OGG') else None)


def discover(root):
    return sorted(glob.glob(os.path.join(root, '**', '*.sss'), recursive=True))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog=__doc__.split('Usage\n-----')[1])
    ap.add_argument('chart', nargs='?', help='a .sss chart')
    ap.add_argument('--all', action='store_true', help='render every .sss under CHART')
    ap.add_argument('-o', '--out', help='output file, or a directory with --all')
    ap.add_argument('--assets', help='sample directory (default: the chart\'s own directory)')
    ap.add_argument('--rate', type=int, default=DEFAULT_RATE)
    ap.add_argument('--gain', type=float, default=1.0)
    ap.add_argument('--no-normalize', action='store_true')
    ap.add_argument('--tracks', help='only these slot indices, e.g. 3,4,5,6,7,8,11')
    ap.add_argument('--no-pan', action='store_true', help='ignore the pan byte')
    ap.add_argument('--linear-vel', action='store_true',
                    help="apply velocity as a linear gain instead of the game's dB mapping "
                         "(not correct; kept only to A/B the difference)")
    ap.add_argument('--hold', action='store_true',
                    help='gate/loop long notes to their length field (default: play once)')
    ap.add_argument('--tail', type=float, default=TAIL_SECONDS)
    ap.add_argument('--no-bed', action='store_true',
                    help='drop the long ambience/bass bed samples (see --report)')
    ap.add_argument('--bed-seconds', type=float, default=10.0,
                    help='a sample this long counts as a "bed" (default 10, 0 disables)')
    ap.add_argument('--report', action='store_true', help='per-slot event counts and warnings')
    args = ap.parse_args()

    only = {int(x) for x in args.tracks.split(',')} if args.tracks else None
    kw = dict(assets_dir=args.assets, rate=args.rate, gain=args.gain,
              normalize=not args.no_normalize, only=only, use_pan=not args.no_pan,
              hold=args.hold, tail=args.tail, report=args.report,
              no_bed=args.no_bed, bed_seconds=args.bed_seconds, linear_vel=args.linear_vel)

    if args.all:
        charts = discover(args.chart)
        if not charts:
            sys.exit('no .sss under %s' % args.chart)
        outdir = args.out or 'rendered'
        for c in charts:
            name = os.path.splitext(os.path.basename(c))[0]
            out = os.path.join(outdir, name + '.flac')
            try:
                mix, rate, st = render(c, **kw)
                write_audio(out, mix, rate)
                print('%-22s %5d events / %3d keysounds  %6.2fs -> %6.2fs%s'
                      % (name, st['events'], st['keysounds'], st['chart_seconds'],
                         st['rendered_seconds'], warn(st)))
            except Exception as e:
                print('%-22s SKIP: %s' % (name, e))
        return

    if not args.chart:
        ap.error('give a .sss chart, or --all')
    mix, rate, st = render(args.chart, **kw)
    out = args.out or (os.path.splitext(os.path.basename(args.chart))[0] + '.flac')
    write_audio(out, mix, rate)
    print('%-22s %5d events / %3d keysounds  %6.2fs -> %6.2fs%s'
          % (st['chart'], st['events'], st['keysounds'], st['chart_seconds'],
             st['rendered_seconds'], warn(st)))
    if args.report:
        print('  slots:', st['per_slot'])
        for slot, tick, name, d in st['beds']:
            print('  bed: slot %2d tick %6d  %-24s %7.2fs' % (slot, tick, name, d))
    print('  -> %s  peak %.3f  clipped samples %d' % (out, st['peak'], st['clipped']))


def warn(st):
    bits = []
    if st['unknown_sound']:
        bits.append('%d notes reference a sample index absent from the table'
                    % st['unknown_sound'])
    if st['missing_files']:
        bits.append('%d sample file(s) not found: %s'
                    % (len(st['missing_files']), ', '.join(st['missing_files'][:4])))
    if st['dropped']:
        bits.append('%d notes dropped (past end of render)' % st['dropped'])
    return '  [' + '; '.join(bits) + ']' if bits else ''


if __name__ == '__main__':
    main()
