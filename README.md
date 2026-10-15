# EZ2AC: Endless Circulation — chart format notes and tools

Reverse-engineering notes for the chart files of **EZ2AC: Endless Circulation**,
plus a working codec and a converter from **Sabin Sound Star: Renascence Burst**
`.sss` charts into EZ2AC `.ez` + `.ezi` pairs.

No game content is tracked. Bring your own `EZ2AC.exe` and chart files.

## Status

| Item | State |
| --- | --- |
| EC container codec (`.ez`, `.ezi`, `.ini`) | **solved**; byte-exact round-trip on 7 shipped files |
| Keystream (512 dwords @ `0x004bf1f0`) | extracted from `EZ2AC.exe` |
| `.ez` payload = EZFF v6 | parsed and rebuilt; matches `ez2stuff`'s documented layout |
| `.ezi` payload = `note flag filename` text | parsed; `flag` semantics read out of `LoadEZI` |
| `.ini` | same codec, ordinary quoted-key ini once decoded |
| `.sss` → `.ez` + `.ezi` conversion | **lossless**; 36/36 charts recombine byte-identically |
| `.sss` → EC-loadable chart | reproduces EC's own Firestorm chart to 2 events out of 2012 |
| **FINAL EX (FNEX) container codec** | **solved**; three keystreams, one per file type; 1 800/1 800 byte-exact round-trips |
| FINAL EX `.ez` = EZFF **v8** | parsed; 13-byte notes, u16 keysound index, four record magics |
| FINAL EX `.ssf` keysound audio | **solved**; 18-byte header + raw PCM, unencrypted; 700/700 rebuild byte-identical |
| `.sss` → FINAL EX chart, `.wav` → `.ssf` | working end to end — see `docs/ADD-A-SONG.md` |
| `.es`, `-ez.bin`, `.ezz` on disk | referenced by the loader, not present in the shipped set |

## Layout

```
FORMAT.md              the file formats and the container codec
docs/REVERSE.md        how it was recovered: functions, addresses, dead ends
docs/SSS-VS-EZ2AC.md   what differs between a 3S .sss and an EC .ez/.ezi pair
docs/ec_keystream.hex.txt  the EC 512-byte keystream as hex
docs/FINAL-EX.md       FINAL EX: three keystreams, EZFF v8, .ssf, record magics
docs/ADD-A-SONG.md     recipe for putting a 3S song into FINAL EX, open items
keys/*.hex.txt         six keystreams (FNEX ez/ezi/ini, EV, NT, AEIC)
tools/ez2ac.py         EC codec + EZFF parser/builder + .ezi parser (stdlib only)
tools/sss2ez.py        .sss <-> EC .ez + .ezi converter (stdlib only)
tools/fnex.py          FINAL EX codec + EZFF v8 + .ssf codec (stdlib only)
tools/wav2ssf.py       3S .wav <-> FINAL EX .ssf keysound audio (stdlib only)
tools/sss2fnex.py      .sss -> FINAL EX .ez(v8) + .ezi, and audit (stdlib only)
```

## Usage

```sh
# inspect a shipped EC chart
python3 tools/ez2ac.py info "/path/Endless Circulation/songs/.../streetmix1p-firestorm.ez" --ec

# decode / encode the container
python3 tools/ez2ac.py decode chart.ez -o chart.plain.ez
python3 tools/ez2ac.py encode chart.plain.ez -o chart.ez

# verify the codec
python3 tools/ez2ac.py roundtrip "/path/Endless Circulation/*.ini"

# 3S .sss -> plain EZ2AC v6 pair
python3 tools/sss2ez.py split /path/3S/songs/Firestorm/Firestorm/firestorm_1n.sss -o out/

# -> EC-container pair (what EC itself would read)
python3 tools/sss2ez.py split x.sss -o out/ --ec

# normalise a 3S chart to EC's own layout
python3 tools/sss2ez.py split x.sss -o out/ --remap 8:10 --shift-notes -192 --retime

# write name strings (most 3S charts carry none; EC's own charts leave the
# header name fields empty and only label track 0 as `untitled`)
python3 tools/sss2ez.py split x.sss -o out/ --title untitled --name1 kamui \
    --track-name 1:Dummy --track-name 2:Dummy2

# or just fill EC's own slot-name template (slots 0..31) into a nameless chart
python3 tools/sss2ez.py split x.sss -o out/ --ec-names

# fold a 3S Percussion-mode chart onto EZ2AC's 5K + scratch lanes
python3 tools/sss2ez.py split kamui_3h.sss -o out/ --remap 8:10 --remap 9:3 \
    --remap 10:4 --remap 17:5 --remap 18:6 --remap 19:7

# prove the split is lossless
python3 tools/sss2ez.py combine out/x.ez out/x.ezi -o back.sss && cmp back.sss x.sss

# see what a .sss puts in each track slot
python3 tools/sss2ez.py audit x.sss
```

Everything is stdlib-only; no venv needed.

## Headline finding

A 3S `.sss` is an EZ2AC chart with its two halves concatenated:

```
[ .ezi payload, as text ][ EZFF v6 payload == the .ez file ]
```

For Firestorm, where both games ship the song, the 3S text header is
**byte-identical** to EC's `.ezi` (2725 bytes, 112 keysounds), and the EZFF
footer is the same v6 structure with the same track slot names. The charts
themselves differ only by a one-measure note offset, one reassigned lane, two
duplicate BPM events, and one extra measure of length. See
`docs/SSS-VS-EZ2AC.md`.

## FINAL EX in one paragraph

FINAL EX reuses EC's *transform* but not its *keystream*, and not just one:
`.ez`, `.ezi` and `.ini` each get their own 512-byte table, recovered from the
512-dword array at file offset `0x1818` (VMA `0x403018`) inside Kasaski's
`ez2djDecoder` binaries in `ez2ac-tools/`. Its `.ez` payload is EZFF **v8**:
13-byte note records with a **u16** keysound index, which is how FINAL EX's own
Finite chart addresses 1 131 keysounds where v6 caps at 255. Its keysound audio
is `.ssf` — an 18-byte header (the WAV `fmt` body with `wFormatTag` dropped, plus
a PCM byte count) followed by unencrypted raw PCM. Renaming a 3S `.wav` to
`.ssf` fails twice over: the bytes are still 3S-obfuscated *and* the container is
WAV. `tools/wav2ssf.py` fixes both in one step. See `docs/FINAL-EX.md`, and
`docs/ADD-A-SONG.md` for the import recipe.

## Related

* `3s-re` — the 3S side: `.sss` codec, `.wav` sample obfuscation, chart
  taxonomy, lane maps, and a song renderer.
* [`freem/ez2stuff`](https://github.com/freem/ez2stuff) — the EZFF/EZTR/EZIF
  layouts, and `ezdec_715.c` / `ezdec_720.c`, which encode EZ2DJ 7th Trax
  charts the same way (reverse + subtract a 512-byte table) with different
  tables. EC's scheme is a member of that family.

## AI usage disclosure

This repository was generated by locally hosted Qwen3.8-Flash-Next. All output was reviewed by a human.
