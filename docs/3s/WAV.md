# `.wav` sample obfuscation

Status: **solved.** Key recovered from `FUN_004043b0` in `3s.exe` and verified
against all 577 sample files shipped with the four songs available locally —
every one decrypts to a fully self-consistent RIFF/WAVE header, and
`encode(decode(x)) == x` for all 577.

Tool: `tools/wav.py` (`info`, `decode`, `encode`, `roundtrip`).

## The scheme

The samples a chart references (third column of the text instrument table) are
not plain WAV files, but they are only *partially* obfuscated:

```
plain[i] = (cipher[i] - KEY[i % 128]) & 0xff     for i < 256
plain[i] =  cipher[i]                            for i >= 256
```

Same subtract-keystream construction as `.sss`, but the game touches only the
first `0x100` bytes. This is the loop in `FUN_004043b0`:

```c
local_68 = fopen(param_2, "r+b");
fseek(local_68, 0, 2); local_60 = ftell(local_68); fseek(local_68, 0, 0);
local_10 = malloc(local_60);
fread(local_10, 1, local_60, local_68);
fclose(local_68);
for (local_c = 0, i = 0; i < 0x100; i++) {
    *(char *)((int)local_10 + i) -= (char)key[local_c];
    if (++local_c > 0x7f) local_c = 0;
}
/* then handed to the multimedia I/O layer as a memory buffer */
local_5c.fccIOProc = 0x204d454d;          /* 'MEM ' */
local_5c.pchBuffer = (HPSTR)param_1[0x24];
local_5c.cchBuffer = local_60;
mmioOpenA(NULL, &local_5c, 0x10000);
```

If `mmioOpenA` fails the game falls back to `FindResourceA(NULL, name, "WAVE")`
and then `"WAV"`, i.e. samples baked into a PE resource. Shipped files never
take that path.

## The keystream

128 bytes, recovered from the stack-resident initialiser in `FUN_004043b0`
(the compiler wrote each byte as its own `mov dword ptr [ebp-0x..], imm`, so
the values are the low bytes of those immediates):

```
05 0b 02 17 a1 9b 87 74 0d 3d 1c 56 18 57 02 54
41 01 02 1f 56 0e 49 a6 23 10 3a 4c 04 07 02 18
06 3d 7d 23 10 fe 0d ec e8 10 d4 4c b8 c5 7e 2e
0f 01 02 21 24 04 20 12 17 1a e4 1a 7c 57 de 0e
05 0b 02 03 3d 29 23 13 d5 06 1c 56 18 57 0c 54
41 01 02 1f 56 04 03 d8 27 06 3a 60 04 07 02 04
05 3d 19 23 06 36 1f 24 d3 06 52 06 54 c5 1a 2e
0f 01 02 21 24 36 1f 11 1f 7e 1c 06 18 57 16 04
```

## Relationship to the `.sss` keystream

This is a *distinct* key, not the chart key. But it is clearly derived from the
same source: **121 of its 128 bytes equal the `.sss` key rotated left by 96**
(`KEY_wav[i] == KEY_sss[(i + 96) % 128]`), and only seven bytes differ:

| index | `.sss` rotated | `.wav` |
| ---: | ---: | ---: |
| 3 | `03` | `17` |
| 22 | `03` | `49` |
| 27 | `06` | `4c` |
| 31 | `04` | `18` |
| 78 | `02` | `0c` |
| 91 | `06` | `60` |
| 109 | `61` | `c5` |

Do **not** substitute the rotated chart key. It decrypts the 44-byte header
perfectly — which is exactly what makes the mistake easy to miss — and corrupts
the audio instead. The seven differing bytes land at file offsets 3 (inside the
magic), 22/27/31 (inside the `fmt ` fields) and 78, 91, 109 (inside the first
212 bytes of PCM). Verified empirically: over 120 files, decoding with the
rotated key raises total sample-to-sample delta by ~26.9 million units and is
worse on *every* file, with clicks appearing at precisely the predicted sample
positions (byte offsets 78/79, 90/91, 108/109, 130/131).

## Two traps

**The on-disk magic is `WTH]`, not a container format.** `0x57 0x54 0x48 0x5d`
is `"RIFF"` plus the first four keystream bytes (`05 0b 02 17`). Every sample
file starts with it, which is why it looks like a signature. It is not: the
first four bytes of every file are the same four ciphertext bytes because they
are the same four plaintext bytes.

**The keystream covers 256 bytes, not 44.** A WAV header is 44 bytes, so bytes
44–255 are *audio* and are obfuscated too. Fixing up only the header leaves 212
bytes of noise at the start of every sample. Measured on `1-kick-02.wav`, mean
absolute sample delta in the region 44–256:

| region | mean \|Δsample\| |
| --- | ---: |
| bytes 44–256, left raw | 16387 |
| bytes 44–256, keystream applied | 3380 |
| bytes 256–468, untouched by the game | 2088 |

The decrypted figure converges on the untouched region, which is what confirms
those bytes really are obfuscated in the file rather than merely "covered by a
loop that happens to be a no-op".

## Sample parameters observed

All 577 files are PCM (`audio_format = 1`), 16-bit, `fmt ` chunk size 16, and
the `data` chunk starts at offset 44:

| sample rate | channels | files |
| ---: | ---: | ---: |
| 44100 | 2 | 521 |
| 22050 | 2 | 22 |
| 22050 | 1 | 31 |
| 44100 | 1 | 3 |

`riff_size == filesize - 8` and `44 + data_size <= filesize` hold for all 577.

## Reproducing the key extraction

The key is not a data blob — it is 128 immediate stores, so pattern-searching
the file for it finds nothing. Read it out of the disassembly instead:

```sh
objdump -dM intel --start-address=0x4043b0 --stop-address=0x404c00 3s.exe \
  | grep -oE 'mov +DWORD PTR \[ebp-0x[0-9a-f]+\],0x[0-9a-f]+' \
  | sed -E 's/.*\[ebp-(0x[0-9a-f]+)\],0x([0-9a-f]+)/\1 \2/'
```

Index *n* lives at `[ebp - 0x268 + 4n]`; take each immediate mod 256. Note the
Ghidra decompiler renders several of these wrong (`0x19b`, `0x17`, `0x60`,
`0xc5`, `0xc`) because it types the array as `undefined4[129]`; the raw
immediates are authoritative. The three audio-region differences were then
confirmed independently from the PCM, so the key does not rest on the
disassembly alone.
