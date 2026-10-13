# How the EC codec was recovered

Two passes. The first was pure cryptanalysis and got most of the way there but
drew two wrong conclusions; the second read the executable and settled it. Both
are recorded because the failure mode is instructive.

## Pass 1 — cryptanalysis (partly wrong)

Observed in the shipped `.ez` files: a 16-byte ciphertext run recursed at
exactly 512-byte intervals, which pins a 512-byte keystream and reveals a
per-file phase (0, 9, 20 bytes). Consensus voting over the three charts plus the
`.ezi` and `EZ2AC.ini` recovered a keystream that decoded the text files to
readable ASCII.

Wrong inferences from that pass:

* **"There is a random junk prefix of zeros."** The apparent prefixes were
  artifacts. There is no prefix; the file is reversed.
* **The recovered keystream was `K` reversed and misaligned**, because the
  reversal was unknown at the time. Consensus confidence was only 46%, which was
  the tell: if the plaintext were really mostly zeros the mode would be far
  sharper.

A trigram-model coordinate-ascent refinement of that keystream collapsed into a
repetitive attractor (`-0l e0a v0\r \n0F #01` over and over). Soft language
models over ~5 samples per keystream position are not enough; the structure has
to come from the binary.

## Pass 2 — the executable (authoritative)

`EZ2AC.exe` imported into Ghidra, fully analysed.

There is no plaintext `EZFF` string xref to a decoder, because the loader never
sees obfuscated bytes. The chain is:

| Address | Role |
| --- | --- |
| `0x0041a9b6` | Chart entry point. Builds the two temp filenames, decrypts, loads `.ezi` then `.ez`, `DeleteFileA`s both. |
| `0x0041a58e` | **The container codec.** Reverses the file, subtracts the table, applies the 8/16 span permutation, writes a `.ezz` temp file. |
| `0x004bf1f0` | The keystream: 512 dwords. |
| `0x00418c8b` | `LoadEZI` — the `.ezi` text loader. |
| `0x00418ed3` | Note name → keysound index (`octave*12 + semitone`, `#` = +1). |
| `0x00419691` | `LoadEZ` — the EZFF v6 parser. |
| `0x0049e8e3`, `0x0049e9eb`, `0x0049e88d`, `0x0049f038` | CRT `fread` / `fopen` / `fclose` / `fscanf`. Not part of the codec — an earlier guess that decryption lived in the read path was wrong. |

### Reading the codec out of `FUN_0041a58e`

The decompiled loop alternates chunk lengths of 8 and 16, and inside a chunk
reads the input backwards while the keystream index runs forwards:

```c
out[s + j] = in[s + (L - j) - 1] - (char)*(u32 *)(&DAT_004bf1f0 + idx * 4);
idx = base - 1 + (L - j);
```

Substituting `q = s + L - 1 - j` gives `out[s + L - 1 - k] = in[s + k] - K[base + k]`,
and since `base` and `s` both advance by `L`, `base == s` always. So the chunk
machinery is exactly "subtract the keystream linearly, then reverse within
spans" — an obfuscation, not extra entropy. Confirmed by byte-exact round-trip
on all seven reference files.

### Strings that pinned the rest

| Address | String | What it settled |
| --- | --- | --- |
| `0x004bfbac` | `EZFF` | the magic `LoadEZ` compares against |
| `0x004bfb10` | `%s %d` | `.ezi` record syntax |
| `0x004bfb18` | `\n` | comment skip (`;` at line start) |
| `0x004bfb1c` | `Error on LoadEZI(%s) - note number exception %d` | index range check `0..0xff` |
| `0x004bfc2c`, `0x004bfc34` | `.ezi`, `.ezz` | temp names for the keysound table and the chart |
| `0x004bfc3c`, `0x004bfc40` | `.ez`, `.es` | source extensions tried |
| `0x004c225c` | `%s%dp-%s.ez` | EC chart filename shape |
| `0x004bfbb4` | `Illegal EZ file %s` | magic mismatch path |

### Searching for the table in the raw image

A 512-byte contiguous copy of the keystream does **not** exist in `EZ2AC.exe`,
`2EZ.dll`, `ddraw.dll` or `ez_crk_vsync.exe` — checked for `K`, reversed,
negated, XOR-`0xff`, XOR/± index, and byte-pair-swapped, by full-image
cross-correlation (best score 20/512, i.e. noise). It is also not built from
runs of `mov [ebp-disp], imm` stores the way 3S builds its sample keystream:
scanning for chains of `C7 85` / `C7 45` / `C7 84` with a decrementing
displacement and small immediates found no chain longer than 64. The table is
data at a fixed RVA, so Ghidra's image-wide correlation should have found a
plain copy if one existed — the correlation was over the file image, which for a
PE maps 1:1 over the sections of interest.

Practical takeaway: when a keystream resists both blob search and
immediate-store search, stop guessing the transform and go read the loader.
