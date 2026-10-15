# 3S PNG artwork: same obfuscation as the samples, different key rotation

Every `.png` supplied here — the `img/skin_data/` set plus its `Flare/`
subdirectory, 116 files — is an ordinary PNG whose **first 256 bytes** have a
fixed keystream subtracted from them, and whose remaining bytes are untouched.

```
plain[i] = (cipher[i] - KEY[i % 128]) & 0xff      for i < 256
plain[i] =  cipher[i]                             for i >= 256
```

It is the same construction as `docs/3s/WAV.md`: 0x100 bytes covered, a 128-byte
key, counter wrapping mod 0x80, everything past 256 left alone. What differs is
which key.

**The image key is the `.sss` chart keystream, unrotated** — `sss.KEY` in
`tools/sss.py`. The sample key is that same table rotated left by 96, so the two
are not interchangeable here. On disk a 3S PNG begins:

```
8f 8d cb 6a 1d 08 27 f6 e8 10 d4 59 01 0d c2 80
```

which is `\x89PNG\r\n\x1a\n` + `\x00\x00\x00\rIHDR` with the chart key added.
Put differently: the on-disk magic is `PNG\x1a` smeared by the first eight chart
key bytes, and because the first 16 plaintext bytes are identical in every PNG,
those 16 ciphertext bytes are identical across all 116 files — a good quick
test for "is this file 3S-obfuscated at all".

Subtracting the known PNG prefix from the ciphertext recovers the keystream
directly, and it matches the chart key byte for byte from offset 0. The
`rot96` variant does not match at offset 0 at all, so unlike the sample case
there is no subtle near-miss to fall into; using the wrong key here fails
immediately.

## Why this is confirmed rather than guessed

A PNG is unusually good for verifying a keystream, because it carries its own
checksums:

* **Every chunk CRC verifies in all 116 files.** Chunk CRCs are CRC-32 over the
  chunk type and body, and these files contain `iCCP` chunks of ~2.6 KB that
  straddle the 256-byte boundary. That cuts both ways: apply the key too short
  and the CRC fails; apply it too far into IDAT and the CRC also fails. So the
  256-byte coverage is pinned by the data, not assumed.
* **The IDAT streams inflate.** `zlib` rejects a stream with a single wrong
  byte, and after decoding, every IDAT inflates to exactly
  `height × (width × bytes-per-pixel + 1)` raw scanline bytes — checked in all
  116.
* **Re-obfuscating reproduces the input byte for byte**, so the transform is the
  exact inverse of what the game stores, not merely a plausible one.
* The decoded images are visibly correct: the `SKIN_*_pannel` files are playfield
  panels (500×768 RGBA, key lanes, `MAX COMBO`/`SCORE` furniture, the 3S logo),
  `Flare/Flare_000xx.png` are 300×300 note-flare frames, `SKIN_char_N.png` are
  24×24 digits.

Tool: `tools/png.py` (`info`, `audit`, `decode`, `encode`, `roundtrip`).

```sh
python3 tools/png.py audit  'img/skin_data/*.png'    # CRC + inflate check, writes nothing
python3 tools/png.py decode 'img/skin_data/*.png' -o out/
python3 tools/png.py roundtrip 'img/skin_data/*.png' # 116/116 identical
```

## Scope: verified vs assumed

Verified: the 116 files in `3s_skin_data/` (92 loose plus 24 in `Flare/`), which
correspond to `img/skin_data/` in the shipped listing.

**Not verified, but expected to behave the same:** the other ~1 780 PNGs in the
game. The full listing has 1 894 `.png` paths, mostly under `img/`:
`img/musicselect_char` (646), `img/modeselect/modeselectfontanimation` (256),
`img/result/place` (155), `img/skin_data` (114), `img/musicselect` (104),
`img/cardsystem` (86), `img/modeselect` (44), `img/combinechar/com0{1,2}`
(40 each). Run `tools/png.py audit` on any of them: it is non-destructive and
will say in one line whether the same 256-byte/chart-key reading holds. If a
directory uses a different key or full-file coverage, the audit will say so
rather than silently producing a broken image.

Also not addressed here: `.bng` (260 files, unknown format), `.bik` (208, RAD
Video — its own container, usually not keystream-obfuscated), `.del` (91) and
`.rnk` (212, partially characterised in `docs/3s/TAXONOMY.md`).

## On the "original 3S and Renascence Burst share executables" claim

These skin files decode with **the Renascence Burst build's chart keystream**,
recovered from the RB executable. If they came from a build that used a
different table, the chunk CRCs would not verify — a CRC over ~2.6 KB of
`iCCP` data does not pass by accident. So this is consistent with, and mild
evidence for, the claim: same key lineage. It does not prove the executables are
identical, and it says nothing about whether the *artwork* is the original 3S's
or RB's.
