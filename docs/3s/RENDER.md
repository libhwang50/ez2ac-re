# Rendering a song from a chart

A 3S song is not stored anywhere. It is a render of the chart: every type-1
note on every slot triggers its keysound at its scheduled tick. `tools/
render_song.py` does exactly that.

```sh
uv venv && uv pip install numpy soundfile

python3 tools/render_song.py path/to/kamui_1n.sss -o kamui_1n.flac
python3 tools/render_song.py path/to/songs --all -o rendered/
python3 tools/render_song.py path/to/x.sss --report
```

A render is self-contained: the chart carries its own instrument table, the
`sound` byte indexes it, the table names the `.wav`, and the samples sit next to
the chart. Samples are partially obfuscated, so they go through `tools/wav.py`
on the way in — see `docs/WAV.md`.

## What has to be right

**All slots, not just the lanes.** The melody lives in the player slots (3–21)
as much as in the backing slots (22–39). Rendering only the lanes gives a dry,
unfinished song; rendering only the backing gives karaoke without the tune.
Lane notes and backing notes do not collide — 0 or 1 shared `(tick, sample)`
pairs per chart — so summing every slot does not double the melody.

**Sample lookup must be case-insensitive.** Two instrument entries name
`0-cymbal.wav` / `0-bomb.wav` while the files on disk are `0-CYMBAL.wav` /
`0-BOMB.wav`. The game is Windows and does not care; a case-sensitive lookup
silently drops them.

**Velocity is dB.** See `FORMAT.md`. Applying `velocity/127` as a linear gain
puts the 24% of notes below 127 anywhere from 2 to 17 dB too loud, which is what
makes keysound volumes sound off in a first-pass render. `--linear-vel`
reproduces the wrong behaviour for A/B.

**Pan is a dB balance**, `(pan - 64) * 156` in 1/100 dB, not equal-power.

**Keysounds play once.** `length` is a tick field but not a playback gate.
`--hold` exists only as an experiment against that reading.

**The long samples are beds.** Slots 22 (or 38/39 in kamui) trigger one sample
that runs most of the song. They are low-frequency beds, not full-song bounces,
and `--report` lists them. `--no-bed` drops them.

## Verification

* **Onset alignment.** Rendering a single slot and correlating the render's
  onset envelope against an impulse train at that slot's scheduled note times
  gives correlation **1.000 at lag 0 ms** (slots 3, 8, 24, 29 tested; baseline
  0.45–0.63 at random shifts). Timing and sample placement are exact.
* **Coverage.** All 36 sample charts render with no missing files and no
  clipping. 6786 instrument entries, no duplicate indices, all resolving once
  lookup is case-insensitive.
* **Duration.** Rendered length matches the header's derived `duration` field
  to within the trailing-silence trim (kamui 123.43 s header → 123.05 s audio).
* **Rebalancing check.** Per-slot RMS relative to slot 3 moves by 2–4 dB for
  slots whose mean velocity is 110–115 once the dB mapping replaces the linear
  one, and by 0 dB for slots at velocity 127 — i.e. the change lands exactly
  where the velocity data says it should.

## Known gaps

* 10 notes across the kamui charts reference sample index 255 (and one 171)
  with no matching entry in that chart's table. They are skipped and reported.
* `--hold` is unverified and probably wrong.
* The renderer assumes the shipped build's constant `lanevol = 127`. If a build
  ever populates `DAT_00bdd9e4`, per-lane gains would need adding.
