# The `.sss` chart format

Format of a 3S chart file, e.g. `kamui_1n.sss`. Everything below is verified
against 36 shipped charts from four songs; each one round-trips byte-for-byte
through `tools/sss.py`.

A `.sss` file is two things concatenated, and the whole thing is obfuscated:

```
.ssss (on disk)  =  enc( text_header || EZFF_footer )
```

There is no separator and no length prefix: the text header is ASCII and ends
where the four bytes `EZFF` begin, which cannot otherwise occur inside it.

---

## 1. Obfuscation

A fixed 128-byte keystream, subtracted per byte. Decryption:

```
plain[i] = (cipher[i] - K[i % 128]) & 0xFF
```

Encryption is the inverse (`+`). The same keystream is used for every `.sss`
file — confirmed by a 3397-byte common ciphertext prefix shared by all nine
`kamui` charts, which have completely different plaintexts.

The key lives as immediate operands in the decryptor at `0x00444ce0` in
`3s.exe` (`FUN_00444ce0`):

```
06 3d 7d 23 10 fe 0d ec e8 10 d4 4c b8 c5 7e 2e
0f 01 02 21 24 04 20 12 17 1a e4 1a 7c 57 de 0e
05 0b 02 03 3d 29 23 13 d5 06 1c 56 18 57 02 54
41 01 02 1f 56 04 03 d8 27 06 3a 06 04 07 02 04
05 3d 19 23 06 36 1f 24 d3 06 52 06 54 61 1a 2e
0f 01 02 21 24 36 1f 11 1f 7e 1c 06 18 57 16 04
05 0b 02 03 a1 9b 87 74 0d 3d 1c 56 18 57 02 54
41 01 02 1f 56 0e 03 a6 23 10 3a 06 04 07 02 04
```

This is obfuscation, not encryption. Sample (`.wav`) files use a *separate*
128-byte keystream, applied to only their first 256 bytes; it is recovered in
`docs/WAV.md`. The two keys are related — the sample key equals the chart key
rotated left by 96 in 121 of 128 positions — but they are not interchangeable.

---

## 2. Text header (instrument / sample table)

Plain ASCII, CRLF-terminated lines, one per sample slot:

```
<note-name> <flag> <filename.wav>\r\n
```

Example, start of `kamui_1n.sss` (3173 bytes, 162 entries):

```
C#0 1 drumloop_01.wav
D0 0 drumloop_02.wav
...
F#2 0 piano11.wav
...
F13 0 piano25.wav
D21 0 strings_s.wav
```

* `<note-name>` is `[A-G](#?)[0-9]` — a letter name plus octave, **not** a MIDI
  number. The sample index is derived from it, not stored:

  ```
  index = octave * 12 + semitone      # C=0, C#=1, D=2, D#=3, E=4, F=5, F#=6,
                                      # G=7, G#=8, A=9, A#=10, B=11
  ```

  So `C#0 -> 1`, `D0 -> 2`, `B0 -> 11`, `C1 -> 12`, `D21 -> 254`. Index 0 (`C0`)
  is legal but usually absent, which is why tables look sparse at the front.
  Parsing of this rule is done by `FUN_004456c0`.

* `<flag>` is `0` or `1` in every chart seen. `1` is rare (the first entry of
  `kamui`); its meaning is **not determined**.

* The table is a *sparse* mapping from index to file. `kamui` has 162 entries
  spanning indices 1..254.

Notes in the EZFF footer reference samples by this numeric index (the `sound`
byte), so the table is what makes a chart self-contained: the music is
synthesised from the note stream rather than played from a single audio file.

---

## 3. EZFF footer — file header (0x96 bytes)

The footer is an **EZ2AC v6** payload, matching `ezfile.h` in
[freem/ez2stuff](https://github.com/freem/ez2stuff). Offsets are relative to the
start of the footer (i.e. to the `EZFF` magic).

| Offset | Size | Field | Observed |
| --- | --- | --- | --- |
| `0x00` | 4 | magic `"EZFF"` | always |
| `0x04` | u8 | (unknown, probably 0) | always `0` |
| `0x05` | u8 | format version | always `6` → v6 note records |
| `0x06` | 64 | `name1` | empty in all 36 |
| `0x46` | 64 | `name2` | empty in all 36 |
| `0x86` | u16 | ticks per measure | always `192` |
| `0x88` | f32 | initial BPM | 210 / 167 / 155 / 175 |
| `0x8c` | u16 | number of track slots | always `64` |
| `0x8e` | u32 | total ticks | e.g. `20736` (= 108 measures) |
| `0x92` | f32 | duration, seconds | e.g. `123.428` |
| `0x96` | — | first track magic `"EZTR"` | |

`kamui_1n.sss`, footer bytes `0x80..0x99`:

```
0000 00 00 00 00 00 00 c0 00 00 00 52 43 40 00 00 51
0010 00 00 24 db f6 42 45 5a 54 52
              ^^^^^ tpm=192  ^^^^^^^^^^^ bpm=210.0  ^^^^ nt=64
                                     ^^^^^^^^^^^ tt=20736  ^^^^^^^^^^^ dur=123.428
                                                              ^^^^^ EZTR
```

**The `0x92` float is a derived value, not a second BPM.** It is exactly the
musical length of the chart at the initial tempo, assuming 4 beats per measure:

```
duration = total_ticks / ticks_per_measure * 4 * 60 / initial_bpm
```

This holds to float precision for all 36 charts. Equivalently
`total_ticks / duration` is the tick rate (168.0 ticks/s for `kamui`).

---

## 4. Track slot header (0x4E bytes each)

64 of them, in slot order, immediately following the file header.

| Offset | Size | Field |
| --- | --- | --- |
| `0x00` | 4 | magic `"EZTR"` |
| `0x04` | u16 | padding, always `0` |
| `0x06` | 64 | track name (empty in all 36) |
| `0x46` | u32 | `numTicks` — always equals the file's `total_ticks` |
| `0x4a` | u32 | `dataSize` — byte length of the note array that follows |

Then `dataSize` bytes of notes, then the next `"EZTR"`. In all 36 charts
`dataSize % 11 == 0`, and there are no trailing bytes after the last track
(the footer tail is empty).

Track slot *index* is what carries meaning; names are never used. See
`docs/LANES.md`.

---

## 5. Note record (11 bytes, v6)

| Offset | Size | Field |
| --- | --- | --- |
| `0x00` | u32 | position, in ticks |
| `0x04` | u8 | type |
| `0x05` | 6 | type-dependent payload |

Types seen:

| Type | Name | Payload layout | Notes |
| --- | --- | --- | --- |
| `1` | note | `sound:u8, velocity:u8, pan:u8, zero:u8, length:u16` | `sound` indexes the text-header sample table |
| `2` | volume | `volume:u8`, then 5 further bytes | the 5 trailing bytes are **not** always zero — see below |
| `3` | bpm | `bpm:f32`, then `u16` | |
| `4` | beats | `beats:u8`, then 5 zero bytes | time-signature numerator |

`FUN_00446c60` converts each 11-byte record into the internal 0x24-byte note
struct, which fixes the field mapping:

```c
case 1:  /* note */
    dst[1] = 1;                        /* internal type */
    dst[0xd] = rec[5];                 /* sound   */
    dst[0xe] = rec[6];                 /* velocity */
    dst[0xf] = rec[7];                 /* pan      */
    *(u16*)&dst[0x10] = rec[8];        /* always 0 in every shipped chart */
    *(u16*)&dst[0x12] = rec[9] | rec[10]<<8;   /* "length", ticks */
    break;
case 2:  /* volume */
    dst[1] = 4;
    dst[0xd] = rec[5];                 /* volume lands in the same field as sound */
    break;
case 3:  dst[1] = 5; *(u32*)&dst[3] = rec[5..8];  break;   /* bpm  */
case 4:  dst[1] = 6; dst[0xd] = rec[5];           break;   /* beats */
```

Note payload byte 3 was `0` in all 99,254 notes of the 36 sample charts.

### `length` is not a playback gate

`length` is a tick value — 6 for 96% of notes, always a multiple of 6, and it
never overruns the next note on the same slot (98,129 shorter, 333 exactly
equal, 3 longer). That looks like a sustain, but it cannot gate audio:
Firestorm's 118.6 s ambience bed is triggered by a single note whose `length`
is 6, which would cut it to 35 ms. So keysounds play once through, and
`length` must feed judgement or visuals instead. See `docs/LANES.md`.

### Velocity and pan are dB, not linear

This is the part that most affects an audio render. `FUN_00417320` is the
keysound play path, and it hands both values to DirectSound, which takes them
in 1/100 dB:

```c
FUN_00417320(sample, 0, velocity * lanevol[lane] / 0x7f, pan, 1)
  iVar3 = -(10000 - (param_3 * 10000) / 0x7f);   /* 1/100 dB */
  if (iVar3 < 0) iVar3 = iVar3 / 2;              /* -> 0 .. -50 dB */
  iVar1 = (param_4 - 0x40) * 0x9c;               /* (pan-64)*156, 1/100 dB */
  SetVolume(iVar3);   /* vtable +0x3c */
  SetPan(iVar1);      /* vtable +0x40 */
```

So velocity is an attenuation in dB, not an amplitude gain:

| velocity | game gain | naive `v/127` | error |
| ---: | ---: | ---: | ---: |
| 127 | 1.000 | 1.000 | 0 dB |
| 120 | 0.728 | 0.945 | −2.3 dB |
| 117 | 0.635 | 0.921 | −3.2 dB |
| 115 | 0.581 | 0.906 | −3.9 dB |
| 111 | 0.484 | 0.874 | −5.1 dB |
| 90 | 0.187 | 0.709 | −11.6 dB |
| 70 | 0.075 | 0.551 | −17.3 dB |

Only 76% of notes are 127, so this dominates the mix balance. Pan is a
DirectSound balance in 1/100 dB: `(pan - 64) * 156`, positive attenuating the
left channel. 64 is centre; pan 96 is +49.9 dB of left attenuation, i.e.
effectively hard right. Observed pan values are 64 (95%), then 0, 127, 96, 32,
10, 117 — consistent with hard-panned layers.

### There is no per-instrument volume table

`lanevol` above is `DAT_00bdd9e4`, a 42-entry per-lane volume array indexed
through the per-track lane map `DAT_00921150`. It looks like the per-instrument
volume control one would hope for, but `FUN_00406c30` initialises all 42
entries to `0x7f` and no shipped code writes it again, so it is a constant 127.

The text instrument table's `flag` column is dead code too: `FUN_00445b70`
parses it with `fscanf(f, "%s %d", name, &flag)` and then evaluates
`flag != 1 && flag == 2` into a local that is never read. Exactly one entry per
chart has `flag = 1` — always the `C#0` / index-1 entry, which in the newer
songs is the `MR` bed sample (`2-<song>-mr.wav`).

That column is not decorative in the format's place of origin. EZ2AC EC's
`LoadEZI` acts on it: `flag == 1` passes a boolean through to `CreateSample`,
and `flag == 2` makes it read a **second filename** from the next token. 3S
inherited the syntax and dropped the behaviour.

**Preserve the raw 6 payload bytes.** For type `2` the bytes after `volume` are
meaningful: `kamui_3n.sss` has a volume event whose payload is
`75 fb 12 00 01 00`, and rebuilding it as "volume then zeros" corrupts the
file. `tools/sss.py` therefore keeps the payload verbatim in `raw` and treats
the decoded fields as display-only; `_pack_data()` exists only for
hand-authored events that have no `raw`.

---

## 6. Observed quirks worth knowing

* **All tempo and time-signature events sit at tick 0.** Across the 36 charts
  there are 1586 type-3 events and 36 type-4 events, and *every one* has
  position `0`. A single chart carries ~40 duplicate BPM events at tick 0, all
  with the same value (modulo float noise: `firestorm` mixes `167.0` and
  `167.0002`). This looks like an authoring-tool artifact. No 3S chart in this
  sample set changes tempo mid-song.
* Tempo/time events live in **track slot 0**. Slots 1, 2 and 21 were empty in
  every chart examined.
* `ticks_per_measure` is always 192 and `num_tracks` always 64, so those fields
  are effectively constants in practice — but the loader honours them, so a
  decoder should read rather than assume them.
* `name1`, `name2`, track names and the `0x04` byte are all zero in shipped
  content. Difficulty is **not** stored anywhere in the file; see
  `docs/TAXONOMY.md`.

---

## 7. How the game loads it

`FUN_004457a0` builds the candidate filenames and drives the load:

```c
sprintf(buf, "%s_%s%s.3s",  song, typeTable[typeIdx], diffTable[diffIdx]);  // tried first
sprintf(buf, "%s_%s%s.sss", song, typeTable[typeIdx], diffTable[diffIdx]);
/* if the .3s is missing, also tries .ez and .ezi with the same stem */
FUN_00444ce0(sssName);      // decrypt -> writes tmp.tmp
FUN_004468b0("tmp.tmp");    // parse the EZFF payload
DeleteFileA("tmp.tmp");
```

So the text-header portion is consumed by the decryptor stage, which writes the
EZFF payload to a temporary file, and `FUN_004468b0` parses that.
`FUN_00446c60` then converts the 11-byte v6 records into the game's internal
0x24-byte note structure.

No `.3s` file exists anywhere in the shipped file listing, but the loader tries
that extension first — see `docs/TAXONOMY.md`.
