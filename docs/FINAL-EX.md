# EZ2AC : FINAL EX (FNEX)

Everything here was recovered from files in `EZ2AC FINAL EX 1.50/` plus the
closed-source authoring tools in `ez2ac-tools/Kasaskis-ez2Tools/`, and verified
against the shipped set: 12 363 `.ez`, 12 362 `.ezi`, 12 522 `.ini` and 178 475
`.ssf`.

## 1. The container codec: three keystreams, not one

The transform is identical to Endless Circulation's — reverse the file, subtract
a 512-byte keystream, then reverse within an alternating 8/16/8/16 span split —
but the keystream differs, **and FINAL EX uses a different one per file type**:

| File | Keystream | First bytes |
| --- | --- | --- |
| `.ez` | `FNEX_KEY_EZ` | `12 5d 94 62 5f a4 b5 c9` |
| `.ezi` | `FNEX_KEY_EZI` | `f5 ff d3 9d 76 f6 34 6d` |
| `.ini` | `FNEX_KEY_INI` | `2e c8 1a 48 17 97 c8 1b` |

None of these is EC's table, and EC's table decodes nothing in FINAL EX. All six
recovered tables (FNEX .ez/.ezi/.ini, EZ2AC Everlasting [EV], NT, AEIC) are in
`keys/` and embedded in `tools/fnex.py`.

Verification: **1 800 / 1 800 byte-exact decode→encode round-trips** over the
first 600 `.ez`, 600 `.ezi` and 600 `.ini` files found in the install, with every
decoded `.ez` starting `EZFF` and every decoded `.ezi` starting with digits.

### Where the tables came from

Kasaski's `FNEX-EncryptTools/{Decode,Encode}-FNEX{,-EZ,-EZI}.exe` are all the
same MSVC console binary (`ez2djDecoder`) built with a different embedded table.
The keystream is the 512-dword array at **file offset 0x1818 = VMA 0x403018**.
The codec reads it as `sub dl, [esi*4 + 0x403018]` — low byte of each dword,
index modulo 512 — the same construction EC uses at `DAT_004bf1f0`.

The dword one slot earlier, at `0x403014`, is a constant `1` used by an unrelated
check. Extracting from `0x1814` instead of `0x1818` shifts the whole keystream by
one byte and decodes nothing; that off-by-one-dword is the trap here.

Decode and Encode tools carry the **same** table — only the sign of the
operation differs. EV/NT and EV-INI share tables across two different tool
directories, so NT and Everlasting Circulation share a keystream.

## 2. `.ez` payload: EZFF version 8

FINAL EX writes **version 8**, not 6. What changes and what does not:

| Structure | v6 (3S, EC) | v8 (FINAL EX) |
| --- | --- | --- |
| file header | 0x96 bytes | 0x96 bytes, unchanged |
| `name1` at `0x06` | empty | **populated with the chart stem**, e.g. `5keymix1p-15finite` |
| track record header | 0x4e bytes | 0x4e bytes, unchanged |
| note record | **11 bytes** | **13 bytes** |
| keysound index | u8 | **u16** |

The 13-byte v8 record is: `u32 position`, `u8 type`, `u16 sound`, `u8 velocity`,
`u8 pan`, `u8 pad`, `u16 length`, `u8 tail`. That is exactly what `ez2stuff`
labels "v7 and later"; FINAL EX's version byte is 8 and the layout is identical.
Empirically the type-1 payload `02 00 7f 40 …` decodes as sound=2, velocity=0x7f,
pan=0x40 — velocity and pan keep the dB interpretation established on the 3S side.

The u16 index is not cosmetic: FINAL EX's own Finite chart addresses **1 131
keysounds**, which v6's u8 cannot express (max 255). 3S charts cap at 255, so
converting one into v8 leaves headroom rather than needing it.

### Four record magics, and corruption in the shipped set

A v8 track table uses four record magics with an identical header shape
(`magic`, `u16 pad`, 0x40-byte name, `u32 numTicks`, `u32 dataSize`):

`EZTR` (dominant), `EZTK`, `EZMR`, `ESTR`.

All four parse identically and never mismatch their `dataSize` — 43 of 43
non-`EZTR` records in a 250-file sample were exactly consistent. What the magics
*mean* is not established; the names inside them are ordinary lane labels such as
`(1P)Line 6` and `BG 6`.

There is a genuine irregularity in the shipped data, and it is worth knowing
before trusting any parse of an existing FNEX chart:

* some records carry a leading magic of `>ZTR` — `EZTR` with `0x45` replaced by
  `0x3e`, i.e. reduced by 7;
* elsewhere a `dataSize` is short by exactly 7 bytes (e.g. declared 864 where
  871 = 67×13 bytes of notes follow);
* over a 400-file sample, 152 files walk with zero anomalies and 248 need at
  least one resync (~1.65 per such file). `tools/fnex.py` resyncs on the next
  plausible magic and reports every case in `chart["anomalies"]` rather than
  failing or hiding it.

Whether this is authoring-tool corruption or an undocumented rule is **not
settled**. What is settled: charts *written* by `tools/sss2fnex.py` walk with
zero anomalies, so authoring is unaffected either way.

## 3. `.ezi` payload: decimal indices, `.wav` names

Same `flag` column position as EC, but the first column is a **plain decimal
keysound index**, not EC's `C#0`-style note name:

```
1 0 00-MR.wav
2 0 01-1-Drums_Kick_01.wav
3 0 01-1-Drums_Kick_02.wav
```

`streetmix`/`5keymix`/`7streetmix` variants of one chart usually share one
`.ezi`. FINAL EX's Finite set has 1 131 lines, indices 1..1133, flag 0 on
essentially every entry.

**The `.ezi` names audio with a `.wav` extension while the files on disk are
`.ssf`.** That is true of FINAL EX's own shipped charts — the game swaps the
extension itself. Keep `.wav` in the `.ezi` and provide `.ssf` on disk, matching
what the shipped charts do.

## 4. `.ssf`: a header-stripped WAV, unencrypted

18-byte header, then raw PCM. The header is the WAV `fmt` chunk body with
`wFormatTag` dropped and a PCM byte count appended:

| Offset | Size | Field |
| ---: | ---: | --- |
| `0x00` | u16 | channels |
| `0x02` | u32 | sample rate |
| `0x06` | u32 | average bytes per second = rate × block align |
| `0x0A` | u16 | block align = channels × bits / 8 |
| `0x0C` | u16 | bits per sample |
| `0x0E` | u32 | PCM byte count = filesize − 18 |

Verified across **all 178 475 `.ssf`** in the install: 178 471 fully consistent.
The four outliers are odd 24-bit/33 389 Hz files and four 8-bit ones. Formats in
use: stereo/mono at 44 100 Hz and 22 050 Hz, 16-bit; a handful at 48 000 Hz.

`.ssf` is **not obfuscated**. The headers decode as clean integers (44 100, 176
400, 59 460 …) with no keystream applied.

Parsing 700 sampled `.ssf` and rebuilding them byte-for-byte reproduced
**700 / 700 exactly**.

## 5. Why renaming 3S `.wav` files to `.ssf` does not work

A 3S keysound `.wav` is a normal RIFF/WAVE whose **first 0x100 bytes are
obfuscated** with a fixed 128-byte keystream (see `3s-re/docs/WAV.md`). So a
renamed 3S file fails for two independent reasons:

1. the bytes are still 3S-obfuscated — the header reads `57 54 48 5d` where
   `RIFF` is expected;
2. the container is WAV, not `.ssf`.

Check: subtracting the 3S keysream from `finite_audio/acid_00.ssf` gives
`RIFF\x189\x00\x00WAVEfmt ` — fmt tag 1, 2 channels, 44 100 Hz, 16-bit. So those
files really are 3S's obfuscated keysounds.

`tools/wav2ssf.py` does the de-obfuscation and the re-wrap in one step. All 256
files in `finite_audio/` converted and every output validated.
