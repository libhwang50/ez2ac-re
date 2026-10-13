# 3S `.sss` vs EZ2AC EC `.ez` + `.ezi`

A `.sss` is an EZ2AC chart with its two halves concatenated into one file:

```
[ .ezi payload, as text ][ EZFF v6 payload == the .ez file ]
```

That is not an analogy — for the one song where both exist, the halves are
**byte-identical** to EC's separate files.

## Evidence

`Firestorm` is the overlap: 3S ships `firestorm_1n.sss`, EC ships
`streetmix1p-firestorm.ez` / `.ezi`.

| Comparison | Result |
| --- | --- |
| 3S text header vs EC `.ezi` payload | **byte-identical**, 2725 bytes, 112 keysounds, indices 1..112 |
| 3S EZFF footer vs EC `.ez` payload | same v6 layout; 64 tracks; identical track names (Firestorm is the only song in the set whose 3S charts carry track names at all) |
| note payloads on shared lanes | identical `sound`, `velocity`, `pan`, `length` byte-for-byte |

So the conversion is a split, not a translation. `tools/sss2ez.py` copies both
halves verbatim and only re-wraps them in EC's container codec on request.

## The four real differences

Converting `firestorm_1n.sss` with `--remap 8:10 --shift-notes -192 --retime`
reproduces EC's `streetmix1p-firestorm.ez` to within **2 events out of 2012**,
across 62 of 64 slots. What remains:

1. **A uniform 192-tick (one measure) offset.** Every 3S note sits one measure
   later than EC's. Control events (type 2/3/4) are *not* offset — 3S pins them
   at tick 0 while EC puts them at tick 192. So the shift applies to type-1
   notes only, which is why the tool separates `--shift-notes` from
   `--shift-events`.
2. **The scratch lane moves.** 3S puts those notes on slot 8 (`(1P)Line 6`); EC
   puts them on slot 10 (`(1P)Scratch`). Counts: 3S 85 on slot 8 and 1 on slot
   10; EC 0 on slot 8 and 86 on slot 10. Hence `--remap 8:10`.
3. **Two duplicate BPM events.** 3S's control track carries 11 events, EC's 9 —
   3S emits `bpm 167.0` at tick 0 twice more than EC does.
4. **One extra measure of length.** 3S declares `total_ticks` 15744 against EC's
   15552, and its trailing volume event on slot 22 sits at 15744 rather than
   15552.

None of these are format differences. They are a port: 3S took EC's chart,
shifted the notes out by a measure, and reassigned one lane.

## What this settles about the lane question

The track slot names in 3S `.sss` files are **the same strings** EC writes into
its own `.ez` files — `untitled`, `Dummy`, `Dummy2`, `(1P)Line 1..7`,
`(1P)Scratch`, `(1P)Pedal`, `(2P)…`, `Lights`, `BG 1..10`. 3S did not rename
anything; it inherited EZ2AC's authoring template verbatim, which is why the
names make no sense against 3S's hardware (three capacitive percussion buttons
per side, no turntable).

The slot-8-vs-slot-10 move is the concrete fingerprint of that mismatch: 3S
needed a lane for its percussion input and used slot 8, where EZ2AC's own
Street Mix charts leave `(1P)Line 6` empty.

Do **not** read `ez2stuff`'s v6 lane table (slots 8, 9, 12, 13 = Effector 1–4)
as authoritative for these files. It describes EZ2DJ's runtime lane semantics;
the names actually stored in EC's and 3S's charts put `(1P)Line 6` at slot 8 and
`(1P)Scratch` at slot 10. The two disagree, and the files are the primary
source.

## Converting Percussion mode to EZ2AC 5K + scratch

3S Percussion mode uses slots `8,9,10` (1P) and `17,18,19` (2P) — six lanes,
three per side. EZ2AC's own playable set, read straight out of EC's shipped
charts, is slots `3,4,5,6,7` (five keys) + `10` (scratch) + `11` (pedal); slots
8, 9 and 12–20 are unused there. So the fold is:

```sh
python3 tools/sss2ez.py split kamui_3h.sss -o out/ \
    --remap 8:10 --remap 9:3 --remap 10:4 \
    --remap 17:5 --remap 18:6 --remap 19:7
```

Leftmost percussion lane (8) becomes scratch; the other five become the key row.
Verified across all 11 type-3 charts in this set: note counts are exactly
conserved and every chart lands on `{3,4,5,6,7,10}`, with `Eraser_3or` keeping
its single pedal note on slot 11 — which is a valid EZ2AC lane.

`--remap` is a **simultaneous permutation**, not a sequence of moves. That
matters here because slot 10 is both a source (`10:4`) and a destination
(`8:10`). A sequential implementation applied in argument order would move
slot 8's notes into 10, then carry them along `10:4`, and produce a chart with
an empty scratch lane and a doubled key 2 — same total note count, silently
wrong. Order of the `--remap` flags is now irrelevant.

Two things not to do:

* **Do not add `--shift-notes -192`.** That one-measure offset is specific to
  Firestorm, which 3S ported from EZ2AC. kamui, bleed and Eraser charts are
  native 3S authoring and need no shift.
* **Do not drop the BG slots.** Slots 22+ carry the melody and the bed sample;
  they are what makes the song audible. The remap only touches playable lanes.

`firestorm_3h` and `firestorm_3n` already have notes on slots 3–7, so the fold
merges two lanes onto one destination. The tool reports it, e.g.
`lane 3 <- 9 (+55 notes already on the destination)`.

Which physical button slot 8 is remains the one soft spot. `DAT_004c34f0` gives
six lanes for Percussion mode, which selects the lane-map row `8 9 10 17 18 19`
— leftmost first — but the branch that picks among the four variant tables is
still unresolved, so confirm the left-to-right order by ear on one chart before
batch-converting.

## Converting in practice

```sh
# plain EZ2AC v6 pair (loadable by editors, ez2stuff, EZ2ON-family tools)
python3 tools/sss2ez.py split firestorm_1n.sss -o out/

# EC-container pair (loadable by EZ2AC EC itself)
python3 tools/sss2ez.py split firestorm_1n.sss -o out/ --ec

# prove the split is lossless
python3 tools/sss2ez.py combine out/firestorm_1n.ez out/firestorm_1n.ezi -o back.sss
cmp back.sss firestorm_1n.sss
```

Verified over all 36 available `.sss` charts: every split recombines to a
byte-identical `.sss`, and EC-wrapped halves decode back to the same payloads.

Caveats when feeding output to EC:

* EC clamps the declared track count to 46, so slots 46..63 are inert. All 3S
  charts declare 64 and keep slots 41..63 empty, so this is harmless — but do
  not put content above slot 45.
* 3S's `.sss` keysound filenames are resolved case-insensitively by the game on
  Windows. Two entries in the Firestorm set name `0-cymbal.wav` / `0-bomb.wav`
  where the files on disk are `0-CYMBAL.wav` / `0-BOMB.wav`. EC's `.ezi` loader
  hands the name straight to `CreateSample`, so preserve the on-disk casing.
* 3S never populates EC's `flag == 2` second-filename form. If a chart needs it,
  the semantics are unestablished.
