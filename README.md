# EZ2DJ / EZ2AC chart formats — and *Sabin Sound Star: Renascence Burst*

Reverse-engineering notes and clean-room tooling for the chart files of the
EZ2DJ family of Korean arcade rhythm games — **EZ2AC: Endless Circulation** (EC)
and **EZ2AC : FINAL EX** (FNEX) — and for **Sabin Sound Star: Renascence Burst**
(3S), which is an EZ2DJ derivative and shares their chart lineage down to the
record layout.

The two were separate repositories until recently. They are one now because
keeping them apart meant restating the same findings twice: the lane map, the
fact that note velocity and pan are dB rather than linear, the `.ez`/`.ezi`
correspondence, the reverse-and-subtract-512-byte-table codec that every game in
the family uses with its own table.

No game content is tracked. Bring your own executables and chart files.

## Status

### 3S — Sabin Sound Star: Renascence Burst

Everything is confirmed by static analysis of `3s.exe` and by byte-exact
round-trip of 36 shipped charts (4 songs, 577 samples). Inferred items are
flagged inline in the docs.

| Area | Status |
| --- | --- |
| `.sss` obfuscation | solved, key recovered |
| Text instrument/sample header | solved |
| EZFF footer (header, tracks, notes) | solved, byte-exact round-trip |
| Track-slot usage per chart type | characterised empirically |
| Difficulty / chart-type naming | solved from the exe's own tables |
| `.wav` sample obfuscation | solved, key recovered; 577/577 samples round-trip |
| Note field semantics (velocity, pan, length) | solved — velocity and pan are dB |
| Slot names and lane map | names read from the file; lane map extracted from the exe |
| Song audio renderer | working; onset alignment verified at lag 0 ms |
| `.rnk` high-score files | partially characterised |
| `.3s` container | **not found on disk** (referenced by the loader) |

### EZ2AC — Endless Circulation and FINAL EX

| Item | State |
| --- | --- |
| EC container codec (`.ez`, `.ezi`, `.ini`) | **solved**; byte-exact round-trip on 7 shipped files |
| EC keystream (512 dwords @ `0x004bf1f0`) | extracted from `EZ2AC.exe` |
| `.ez` payload = EZFF v6 | parsed and rebuilt; matches `ez2stuff`'s documented layout |
| `.ezi` payload = `note flag filename` text | parsed; `flag` semantics read out of `LoadEZI` |
| `.ini` | same codec, ordinary quoted-key ini once decoded |
| **FINAL EX container codec** | **solved**; three keystreams, one per file type; 1 800/1 800 byte-exact round-trips |
| FINAL EX `.ez` = EZFF **v8** | parsed; 13-byte notes, u16 keysound index, four record magics |
| FINAL EX `.ssf` keysound audio | **solved**; 18-byte header + raw PCM, unencrypted; 700/700 rebuild byte-identical |
| `.sss` → EC `.ez` + `.ezi` | **lossless**; 36/36 charts recombine byte-identically |
| `.sss` → EC-loadable chart | reproduces EC's own Firestorm chart to 2 events out of 2012 |
| `.sss` → FINAL EX chart, `.wav` → `.ssf` | working end to end — see `docs/ez2ac/ADD-A-SONG.md` |
| `.es`, `-ez.bin`, `.ezz` on disk | referenced by the loader, not present in the shipped set |

## Layout

```
docs/SSS-VS-EZ2AC.md      the bridge: what differs between a 3S .sss and an EC pair

docs/3s/FORMAT.md         the .sss container + EZFF v6 payload spec
docs/3s/TAXONOMY.md       filename grammar, difficulty ladder, chart types
docs/3s/LANES.md          what the 64 track slots mean per chart type
docs/3s/WAV.md            the partial keystream over 3S sample files
docs/3s/RENDER.md         reconstructing the song audio from a chart
docs/3s/REVERSE.md        how the 3S side was recovered

docs/ez2ac/FORMAT.md      EC container codec + EZFF v6 + .ezi + .ini spec
docs/ez2ac/FINAL-EX.md    FINAL EX: three keystreams, EZFF v8, .ssf, record magics
docs/ez2ac/REVERSE.md     how the EZ2AC side was recovered
docs/ez2ac/ADD-A-SONG.md  recipe for putting a 3S song into FINAL EX, open items
docs/ez2ac/ec_keystream.hex.txt   the EC keystream as hex

keys/*.hex.txt            six recovered keystreams (FNEX ez/ezi/ini, EV, NT, AEIC)

tools/sss.py              3S chart decoder / encoder / round-trip verifier (stdlib)
tools/wav.py              3S sample de-obfuscator (stdlib)
tools/render_song.py      3S song renderer (needs numpy + soundfile)
tools/ez2ac.py            EC codec + EZFF parser/builder + .ezi parser (stdlib)
tools/sss2ez.py           .sss <-> EC .ez + .ezi converter (stdlib)
tools/fnex.py             FINAL EX codec + EZFF v8 + .ssf codec (stdlib)
tools/wav2ssf.py          3S .wav <-> FINAL EX .ssf keysound audio (stdlib)
tools/sss2fnex.py         .sss -> FINAL EX .ez(v8) + .ezi, and audit (stdlib)
```

Everything is stdlib-only except `render_song.py`, which needs numpy and
soundfile:

```sh
python3 -m venv .venv && .venv/bin/pip install numpy soundfile
```

## Usage — 3S

```sh
# human-readable dump (measure:beat notation, sample names resolved)
python3 tools/sss.py decode path/to/kamui_1n.sss
python3 tools/sss.py decode path/to/kamui_1n.sss --raw    # decrypted bytes instead

# lossless JSON, and rebuild a .sss from it
python3 tools/sss.py json   path/to/kamui_1n.sss -o chart.json
python3 tools/sss.py encode chart.json rebuilt.sss

# regression test — run after any change to the codec
python3 tools/sss.py roundtrip 'path/to/*.sss'

# the .wav samples are only obfuscated in their first 256 bytes
python3 tools/wav.py info      'path/to/sound/*.wav'
python3 tools/wav.py decode    path/to/1-kick-02.wav -o kick.wav
python3 tools/wav.py roundtrip 'path/to/sound/*.wav'

# there is no BGM file: the song is a render of the chart
python3 tools/render_song.py path/to/kamui_1n.sss -o kamui_1n.flac
python3 tools/render_song.py path/to/songs --all -o rendered/
```

`roundtrip` is the regression test. It checks two independent paths —
`parse -> build` and `parse -> JSON -> build` — and each must reproduce the
input byte-for-byte. It currently reports all 36 sample charts identical.

## Usage — EZ2AC: Endless Circulation

```sh
python3 tools/ez2ac.py info "/path/Endless Circulation/songs/.../streetmix1p-firestorm.ez" --ec
python3 tools/ez2ac.py decode chart.ez -o chart.plain.ez
python3 tools/ez2ac.py encode chart.plain.ez -o chart.ez
python3 tools/ez2ac.py roundtrip "/path/Endless Circulation/*.ini"

# 3S .sss -> plain EZ2AC v6 pair
python3 tools/sss2ez.py split /path/3S/songs/Firestorm/Firestorm/firestorm_1n.sss -o out/
python3 tools/sss2ez.py split x.sss -o out/ --ec          # EC-container wrapped

# normalise a 3S chart to EC's own layout
python3 tools/sss2ez.py split x.sss -o out/ --remap 8:10 --shift-notes -192 --retime

# write name strings (most 3S charts carry none; EC leaves header names empty and
# labels only track 0 as `untitled`), or fill EC's own slot-name template
python3 tools/sss2ez.py split x.sss -o out/ --title untitled --name1 kamui \
    --track-name 1:Dummy --track-name 2:Dummy2
python3 tools/sss2ez.py split x.sss -o out/ --ec-names

# fold a 3S Percussion-mode chart onto EZ2AC's 5K + scratch lanes
python3 tools/sss2ez.py split kamui_3h.sss -o out/ --remap 8:10 --remap 9:3 \
    --remap 10:4 --remap 17:5 --remap 18:6 --remap 19:7

# prove the split is lossless; and see what a .sss puts in each track slot
python3 tools/sss2ez.py combine out/x.ez out/x.ezi -o back.sss && cmp back.sss x.sss
python3 tools/sss2ez.py audit x.sss
```

## Usage — EZ2AC : FINAL EX

```sh
python3 tools/wav2ssf.py convert ./finite_audio -o out/ssf/        # 3S .wav -> .ssf
python3 tools/sss2fnex.py convert finite_1n.sss -o out/chart/ \
    --stem 5keymix1p-15finite3s                                    # .sss -> EZFF v8
python3 tools/fnex.py info out/chart/5keymix1p-15finite3s.ez
python3 tools/fnex.py roundtrip "/path/FINAL EX/Sound/*/*.ez" "/path/FINAL EX/Sound/*/*.ezi"
```

## Headline finding

A 3S `.sss` **is** an EZ2AC chart with its two halves concatenated:

```
[ .ezi payload, as text ][ EZFF v6 payload == the .ez file ]
```

For Firestorm, where both games ship the song, the 3S text header is
**byte-identical** to EC's `.ezi` (2 725 bytes, 112 keysounds), and the EZFF
footer is the same v6 structure with the same track slot names. The charts differ
only by a one-measure note offset, one reassigned lane, two duplicate BPM events,
and one extra measure of length. See `docs/SSS-VS-EZ2AC.md`.

The same lineage shows up further out: `ez2stuff`'s `ezdec_715.c` and
`ezdec_720.c` decode EZ2DJ 7th Trax charts with the same reverse-and-subtract
construction over a different 512-byte table. Every game in the family uses that
codec; only the table changes — and FINAL EX changes it per file type.

## Legal note

These games are abandonware but not free software. The binaries, music and charts
are still copyrighted. This repository contains only format documentation and
clean-room tooling written from observation of the file layout, plus keystreams
recovered from the games' own binaries.

## Related

* [`freem/ez2stuff`](https://github.com/freem/ez2stuff) — the EZFF/EZTR/EZIF
  layouts, and `ezdec_715.c` / `ezdec_720.c`, which encode EZ2DJ 7th Trax charts
  the same way with different tables.
* `ez2ac-tools/Kasaskis-ez2Tools/` — closed-source third-party encode/decode
  utilities whose embedded tables gave up FINAL EX's three keystreams.

## AI usage disclosure

This repository was generated by locally hosted Qwen3.8-Flash-Next. All output was reviewed by a human.
