# Track slots: what the 64 lanes mean

Every chart declares exactly 64 track slots (`num_tracks` is always 64), each
with an `"EZTR"` header. Slot index is what carries meaning. Some charts also
name their slots, and where a name is present it is authoritative for what the
authoring tool thought that slot was — but **most charts name nothing at all**.

## Slot names, read straight out of the track headers

**Only the nine `firestorm_*` charts have names.** In all 27 other sample charts
— every kamui, bleed and eraser chart — every track name field is empty: no
`untitled`, no `Dummy`, no `(1P)Line N`, nothing. An earlier revision of this
file claimed the names were identical across all 36 charts; that was read off
the Firestorm set and is wrong. Slot *index* is the reliable key. Slot *name* is
present only for the one song in this set that was ported from EZ2AC.

| Slots | Name (the nine Firestorm charts) | Notes (all 36 charts) |
| ---: | --- | ---: |
| 0 | `untitled` | 0 (carries only control events) |
| 1, 2 | `Dummy`, `Dummy2` | 0 |
| 3–9 | `(1P)Line 1` … `(1P)Line 7` | 3840, 3144, 3743, 3213, 3059, 4672, 1644 |
| 10 | `(1P)Scratch` | 1867 |
| 11 | `(1P)Pedal` | 1793 |
| 12–18 | `(2P)Line 1` … `(2P)Line 7` | 821, 692, 687, 713, 450, 1898, 1659 |
| 19 | `(2P)Scratch` | 1571 |
| 20 | `(2P)Pedal` | **0 — never used in any shipped chart** |
| 21 | `Lights` | 0 |
| 22–31 | `BG 1` … `BG 10` | 2076 … 2595 |
| 32–40 | *(unnamed)* | 1786 … 1585 |
| 41–63 | *(unnamed)* | 0 |

So the authoring layout is **9 slots per player** (7 lines + scratch + pedal),
then a `Lights` slot, then 19 backing slots. Slots 32–40 are unnamed but carry
plenty of notes, so they are effectively `BG 11`–`BG 19`.

**These names are stale EZ2DJ/EZ2AC labels, not 3S's controls.** 3S has three
percussion buttons per side (six total, capacitive); nothing in the naming
reflects that, and in EZ2AC v6 the slots `1P Line 6`, `1P Line 7`, `2P Line 1`,
`2P Line 2` were the effector buttons. Treat the names as telling you which
*authored lane* a slot is, never which *button* it is.

They are not merely similar to EZ2AC's: they are *the same strings* EZ2AC:
Endless Circulation writes into its own `.ez` files. For Firestorm — the one
song both games ship — the track names match slot for slot.

## Which slots each chart type uses

Charts containing notes on that slot, across all 36 sample charts:

| slot | type 1 (Arcade) | type 2 (Professional) | type 3 (Percussion) |
| ---: | ---: | ---: | ---: |
| 3–7 | 16 | 9 | 1–2 |
| 8 | 16 | 7 | 11 |
| 9 | 1 | 2 | 11 |
| 10 | — | — | 11 |
| 11 | 16 | 9 | 1 |
| 12–16 | 1 (slot 14 only) | 8 | — |
| 17, 18 | — | — | 11 |
| 19 | — | 8 | 11 |
| 22–31 | 16 | 9 | 11 |
| 32–40 | 3–11 | 2–6 | 2–6 |

Percussion mode is a clean `8,9,10` + `17,18,19`: three lanes per side, six
total — which is exactly 3S's three percussion buttons per side. That those
slots are named `Line 6`, `Line 7`, `Scratch` is the stale-naming point above.

EC settles the slot-8 question outright. In `streetmix1p-firestorm.ez` EC puts
the scratch lane's notes on slot 10 and leaves slot 8 empty; in
`firestorm_1n.sss` 3S puts the same notes on slot 8 — same song, same keysound
table, same note payloads byte-for-byte. 3S moved that lane. See
`ez2ac-re/docs/SSS-VS-EZ2AC.md`.

## The lane map is in the binary after all

An earlier pass here recorded `FUN_00406c30` as a dead end because it builds
keyboard scancode tables. That was **wrong, and half wrong at that**: the same
function also writes `DAT_00921150`, the display-lane → chart-slot map the note
processor uses, from 18-entry per-mode stack tables. It really is the lane map;
the scancodes are just also in there.

```c
for (i = 0; i < 0x12; i++)
    DAT_00921150[i] = table[mode * 0x12 + i];
DAT_009210a8 = DAT_004c34f0[mode];
```

`DAT_004c34f0 = {6, 7, 13}` — lane counts that identify the row index as the
chart type, in the same internal enum order as the chart-type character table:

| row | chart type | lanes |
| ---: | --- | ---: |
| 0 | Percussion | 6 = 3 + 3 |
| 1 | Arcade | 7 = 5 keys + percussion + pedal |
| 2 | Professional | 13 = P1 7 + P2 6 |

Four variant tables exist, selected by an outer branch. Extracted from the
disassembly (`mov dword ptr [ebp-0x…], imm` runs inside `FUN_00406c30`; the
lane-map entries are the stores whose values fall in 3..19):

| table | row 0 (Percussion) | row 1 (Arcade) | row 2 (Professional) |
| --- | --- | --- | --- |
| A | `8 9 10 17 18 19` | `3 4 5 6 7 11 8 9 10` | `3 4 5 6 7 11 8 12 13 14 15 16 19` |
| B | `9 10 17 18` | `3 4 5 6 7 8 9 10` | `3 4 5 6 7 8 12 13 14 15 16 19` |
| C | `8 9 18 19` | `3 4 5 6 7 11` | `3 4 5 6 7 11 12 13 14 15 16` |
| D | `8 9 10 17 18 19` | `3 4 5 6 7` | `3 4 5 6 7 12 13 14 15 16` |

Reading across the rows, the tables differ by whether the **pedal** (slot 11)
and the **percussion** (slots 8, 9, 10) are included in the lane set:

* A — pedal yes, percussion yes (three separate lanes)
* B — pedal no, percussion yes
* C — pedal yes, percussion no
* D — pedal no, percussion no

Table A row 1 is `3 4 5 6 7 11 8 9 10`: five keys, one pedal, and three
*separate* percussion lanes — nine lanes, which is precisely the wiki's
description of Renascence Burst's **Enhanced Arcade** mode (3 percussion + 5
keys + 1 pedal, percussion split rather than combined). Table C row 1 is five
keys plus pedal, matching plain Arcade once you allow that its combined
percussion lane is slot 8.

**What is not settled:** which outer branch picks A/B/C/D. The pedal ×
percussion pattern fits all three rows of tables A–D, but the Percussion rows of
B and C drop to four lanes, which that theory does not explain. Pinning it down
means tracing the outer branch conditions, or running the game.

## What the slots play

Lane notes are not fixed-keysound triggers: the `sound` byte selects any sample
from the chart's own instrument table, and the melody is distributed across the
playable slots. In `kamui_1n.sss`, slots 3–7 carry pitched `piano*`/`lead_*`/
`drumloop_*` material, slot 8 is weighted to vocal chops (`voia_*`, `voib_*`),
and slot 11 (`(1P)Pedal`) is the only lane using scratch (`scrc_x12.wav`), kick
and effect samples. Slots 22–40 hold the rest of the audio.

Lane notes and backing notes do not overlap: the `(tick, sample)` pairs shared
between slots 3–21 and slots 22–40 number 0 or 1 per chart. Summing every slot
therefore reconstructs the song without doubling the melody.

## Long samples are beds, not bounces

Some slots trigger samples that run most of the song:

| chart | slot | tick | sample | length |
| --- | ---: | ---: | --- | ---: |
| firestorm_* | 22 | 192 | `2-firestorm-mr.wav` | 118.6 s |
| bleed_* | 22 | 192 | `255.wav` | 100.8 s |
| Eraser_* | 22 | 192 | `0-MR.wav` | 109.7 s |
| kamui_* | 39 | 2304 | `m_bass.wav` | 109.7 s |
| kamui_* | 38 | 10752 | `strings_s.wav` | 57.0 s |

Each is triggered by a **single** note. They are not full-song bounces: their
energy is concentrated in the lowest frequency band (roughly 10× the mean,
against a fairly flat mix), i.e. a low-frequency bed/ambience layer. This is the
same role the `MR` keysound plays in EZ2ON.

They also settle the `length` question — see `FORMAT.md`: Firestorm's 118.6 s
bed is triggered by a note whose `length` is 6 ticks, which would cut it to
35 ms if `length` gated playback. It does not.
