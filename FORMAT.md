# EZ2AC: Endless Circulation chart file format

Everything here was recovered from `EZ2AC.exe` (20,889,600 bytes, PE32 i386)
and verified against shipped files: three `.ez` charts, one `.ezi`, and
`EZ2AC.ini`. The codec round-trips all seven byte-for-byte, and the decoded
`.ez` files parse as clean EZ2AC v6 EZFF.

## 1. The container codec

EC stores `.ez`, `.ezi` and `.ini` in an obfuscated container form. All three
use the **same** transform. Decoding:

```
1. reverse the whole file
2. plain[i] = rev[i] - K[i mod 512]          (mod 256 subtraction)
3. reverse within each span of an alternating 8 / 16 / 8 / 16 ... split
```

`K` is 512 dwords at `0x004bf1f0` in the image. Only the low byte of each dword
is used — the consumer assigns `(char)*(undefined4 *)(...)`. A handful of
entries exceed `0xff` (`0x1b8`, `0x1f3`, `0x1a7`, `0x1bd`, `0x1ca`, `0x1ec`) and
their low bytes are what matter. The table is reproduced in
`docs/ec_keystream.hex.txt` and embedded in `tools/ez2ac.py`.

Encoding is the exact inverse: undo the span reversal, add `K`, reverse.

Step 3 looks like a separate transform but the loop that performs it also
reverses the *input* read within each span, and the keystream index equals the
span start, so the pair is equivalent to: subtract the keystream straight
through, then reverse within spans. That is what `tools/ez2ac.py` implements,
and it is byte-exact on every reference file.

There is **no** random junk prefix and no per-file key. An earlier cryptanalytic
pass inferred one; that inference was an artifact of assuming the plaintext was
mostly zeros, and it produced a keystream that was `K` reversed and misaligned.
The framing is fully determined by the three steps above.

### Why the file is reversed

`FUN_0041a58e` decrypts into a temporary file and `LoadEZ` then reads that
normally, so the reversal is pure obfuscation — the payload on disk is the
payload in memory, backwards. `ez2stuff`'s `ezdec_720.c` does the same thing for
EZ2DJ 7th Trax v2.0 with a different 512-byte table, so this is a long-standing
family trait, not an EC invention.

## 2. `.ez` — the EZFF payload

Once decoded, an `.ez` is a plain **EZ2AC v6** EZFF file, identical in layout to
what `ez2stuff` documents and to the footer inside a 3S `.sss`:

| Offset | Size | Field |
| ---: | ---: | --- |
| `0x00` | 4 | `"EZFF"` |
| `0x04` | 1 | string terminator / padding, always 0 |
| `0x05` | 1 | format version, always 6 |
| `0x06` | 0x40 | internal name 1 (empty in every shipped chart) |
| `0x46` | 0x40 | internal name 2 (empty) |
| `0x86` | u16 | ticks per measure (192 in all four reference charts) |
| `0x88` | f32 | initial BPM |
| `0x8c` | u16 | number of tracks (64) |
| `0x8e` | u32 | total ticks |
| `0x92` | f32 | duration, seconds |

Track records follow from `0x96`, each `0x4e` bytes of header then the notes:

| Offset | Size | Field |
| ---: | ---: | --- |
| `0x00` | 4 | `"EZTR"` |
| `0x04` | u16 | padding, 0 |
| `0x06` | 0x40 | track name |
| `0x46` | u32 | number of ticks |
| `0x4a` | u32 | note data size, bytes |

Notes are 11 bytes: `u32 position`, `u8 type`, then 6 payload bytes.

| Type | Name | Payload |
| ---: | --- | --- |
| 1 | note | `sound:u8 velocity:u8 pan:u8 zero:u8 length:u16` |
| 2 | volume | `volume:u8` + 5 further bytes |
| 3 | bpm | `bpm:f32` + `u16` |
| 4 | beats | `beats:u8` + 5 bytes |

`LoadEZ` (`0x00419691`) checks the magic against `"EZFF"`, requires version 6,
computes the note count as `dataSize / 11`, and **clamps the declared track
count to 46 (`0x2e`) when it is 47 or more** — so tracks 46..63 are declared but
never read. All four reference charts declare 64.

### The duration field

`0x92` is seconds, and it agrees with

```
duration = total_ticks / ticks_per_measure * 4 * 60 / bpm
```

to about 2e-4 s, but it is **not** bit-exact under any single float32 evaluation
order tried (direct chain, `tt*240/(bpm*tpm)`, `tt/(bpm*tpm/240)`, or an
incremental per-measure accumulation). For `streetmix1p-firestorm.ez` the stored
value is `116.40699768066406` where every chain gives `116.407188416`. Treat it
as written by the authoring tool rather than recomputed by the game, and do not
expect to reproduce it exactly.

The same field exists in 3S `.sss` charts and satisfies the same formula there,
which is what originally identified it as duration rather than a second BPM.

### Track slot names

The names in the shipped charts are:

| Slots | Name |
| ---: | --- |
| 0 | `untitled` (control events) |
| 1, 2 | `Dummy`, `Dummy2` |
| 3–9 | `(1P)Line 1` … `(1P)Line 7` |
| 10, 11 | `(1P)Scratch`, `(1P)Pedal` |
| 12–18 | `(2P)Line 1` … `(2P)Line 7` |
| 19, 20 | `(2P)Scratch`, `(2P)Pedal` |
| 21 | `Lights` |
| 22–31 | `BG 1` … `BG 10` |
| 32–40 | unnamed, but carry notes |

These are **the same names the 3S `.sss` charts carry for the same song** — 3S
inherited them wholesale. Note they are authoring labels, not the runtime lane
semantics `ez2stuff` tabulates for v6 (where slots 8, 9, 12, 13 are Effector
1–4). The names and that table disagree, and the names are what the files
actually contain.

Track names are **optional and inconsistently applied**. EC's own three
Firestorm charts name 32 of 64 slots. Of the 36 3S charts examined, only the
nine Firestorm ones name anything at all — the other 27 leave every track name
field empty. So never key on a name; key on the slot index.

### Name fields, and writing them

There are three places a name string can live, and EC populates only the third:

| Field | Offset | Size | In EC's shipped charts |
| --- | ---: | ---: | --- |
| header `name1` | `0x06` | 0x40 | empty |
| header `name2` | `0x46` | 0x40 | empty |
| track 0 `name` | `0x96+0x06` | 0x40 | `untitled` |

So the only human-readable label EC itself writes is track 0's name, and the
header name fields are dead weight in every file we have. `tools/sss2ez.py`
will write any of them:

```sh
python3 tools/sss2ez.py x.sss --title untitled --name1 kamui \
    --track-name 1:Dummy --track-name 2:Dummy2
```

`--title STR` is shorthand for `--track-name 0:STR`. Writing names does not
change the file length, and the result still parses and round-trips.

## 3. `.ezi` — the keysound table

A plain-text list, CRLF terminated, one keysound per line:

```
<note name> <flag> <filename>
```

`LoadEZI` (`0x00418c8b`) reads it with `fscanf(f, "%s %d", name, &flag)`, then
`fscanf(f, "%s", filename)`. A line whose first character is `;` is skipped as a
comment.

The note name maps to a keysound index exactly as `ez2stuff`'s `ezifile.h`
describes, and as `FUN_00418ed3` confirms: `index = octave * 12 + semitone` with
`C=0, D=2, E=4, F=5, G=7, A=9, B=11` and `#` adding 1. The index must land in
`0..0xff` or loading fails with `note number exception %d`.

`streetmix1p-firestorm.ezi` holds 112 entries, contiguous indices 1..112,
ascending, starting `C#0 1 2-firestorm-mr.wav`.

### The flag column is live in EC

`flag` is not decorative here:

* `flag == 1` → `CreateSample(filename, true, 0)` — a boolean is passed through.
* `flag == 2` → a **second filename** is read from the next token.
* anything else → `CreateSample(filename, false, 0)`.

3S parses this same column and then discards it — the comparison into a local
that is never read. So the column is a real EC feature that 3S inherited in
syntax only. No entry in the reference set uses `flag == 2`, so the second
filename's purpose is not established.

## 4. `.ini`

`EZ2AC.ini` and the per-song option files (`%s1p-%s.ini`,
`catch1p-%s.ini`, `%s1p-%s-hd.ini`, `%s1p-%s-shd.ini`, `%s1p-%s-ez.ini`) use the
same container codec. Decoded, `EZ2AC.ini` is ordinary quoted-key ini:

```
"Window Y" = 0
"Window X" = 0
"Window Width" = 640
"Window Height" = 480
"UseIOCard" = 1
```

## 5. Chart file naming

`0x004c225c` builds chart filenames as `%s%dp-%s.ez` — song directory, player
digit, then a literal `p-`, then the difficulty suffix. So
`streetmix1p-firestorm.ez` is song `streetmix`, player `1`, difficulty
`firestorm`, with `-hd` / `-shd` appended for the other two. 3S instead uses
`{song}_{player}{difficulty}.sss`.

At load time EC rewrites the extension to `.ezz` for the decrypted temporary
chart and `.ezi` for the decrypted temporary keysound table, loads them, then
`DeleteFileA`s both. Decrypted copies therefore exist transiently on disk during
playback.
