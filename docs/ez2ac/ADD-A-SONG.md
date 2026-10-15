# Adding a 3S song to EZ2AC : FINAL EX — the working recipe

Four steps. Everything except the chart itself is verified end to end on the
material in this workspace.

```sh
cd ez2ac-re

# 1. audio: 3S .wav (obfuscated RIFF) -> FINAL EX .ssf
python3 tools/wav2ssf.py convert /path/finite_audio -o out/ssf/

# 2. chart: .sss -> FNEX .ez (v8) + .ezi, wrapped in the FNEX container
python3 tools/sss2fnex.py convert finite_1n.sss -o out/chart/ \
    --stem 5keymix1p-15finite3s

# 3. optional lane fold (see SSS-VS-EZ2AC.md); --slot is a simultaneous
#    permutation, so flag order never matters
python3 tools/sss2fnex.py convert finite_3n.sss -o out/chart/ \
    --stem 5keymix1p-15finite3s --slot 8:10 --slot 9:3 --slot 10:4 \
    --slot 17:5 --slot 18:6 --slot 19:7

# 4. sanity check the output the way the game would read it
python3 tools/fnex.py info out/chart/5keymix1p-15finite3s.ez
python3 tools/fnex.py info out/chart/5keymix1p-15finite3s.ezi
```

Then place the files as FINAL EX expects:

```
Sound/<songdir>/5keymix1p-15finite3s.ez      # FNEX-wrapped EZFF v8
Sound/<songdir>/5keymix1p-15finite3s.ezi     # FNEX-wrapped keysound table
Sound/<songdir>/*.ssf                        # the audio from step 1
```

The `.ezi` must list every keysound the chart references, with the stem matching
the on-disk `.ssf` stem but the extension written as `.wav` — which is what
FINAL EX's own shipped charts do; the game swaps the extension itself.

## Verified

| Check | Result |
| --- | --- |
| FNEX container round-trip on shipped files | 1 800 / 1 800 byte-exact |
| `.ssf` parse→rebuild on shipped audio | 700 / 700 byte-identical |
| `.ssf` header consistency across the install | 178 471 / 178 475 |
| `finite_audio/` → `.ssf` | 256 / 256 converted, 256 / 256 valid |
| converted `.ez` reads back with `strict=True` | clean, 0 anomalies, 0 trailing |
| converted `.ez` vs a real FINAL EX chart | same version, header shape, name1 convention, 13-byte records |

Converting `kamui_1un.sss` produced a 47 509-byte v8 payload, 162 keysounds
(index range 1..254), 3 259 notes preserved exactly, `name1` set to the chart
stem — structurally indistinguishable from `5keymix1p-15finite.ez` apart from the
song's own tempo, tick count and note data.

## Open items — read before trusting a bulk import

* **A 3S chart's keysound table must be complete.** 3S `.sss` keysound entries
  use `C#0`-style names that map to `octave*12 + semitone`, capped at 255. The
  converter emits decimal indices, which is what FINAL EX wants. Notes that
  reference an index above the table are reported by `sss2fnex.py audit`. Both kamui
  charts checked carry a slot-22 note pointing at keysound 255 with no table
  entry, so the referenced sample simply does not exist. Silence, not a crash, is the usual symptom.
* **Filename casing.** 3S resolves keysound filenames case-insensitively on
  Windows. Write `.ssf` stems that match the `.ezi` entries exactly.
* **A minority of shipped FNEX charts do not parse cleanly** (248 of 400 needed
  a resync). Do not assume a parse of an existing FINAL EX chart is complete
  unless `fnex.py info` reports zero anomalies. This does not affect output this
  tool writes.
* **`total_ticks` / `duration` are carried over unchanged.** FINAL EX's own
  Finite declares 16 416 ticks at 178 BPM; a 3S chart carries its own values.
  Mismatch against the audio length is a chart-design problem, not a format one.
* **Difficulty selection is driven by filename**, as in EC: `%s%dp-%s.ez`, with
  FINAL EX prefixing a numeric slot (e.g. `15finite`) and suffixing `-hd`,
  `-shd`, `-ex`. There is also a per-chart `.ini` beside each chart. Whether a
  new song also needs an entry in FINAL EX's song database (`system/`, `.str` and
  `.abm` files) is **not established** — that is the likeliest place an import
  could stall.
