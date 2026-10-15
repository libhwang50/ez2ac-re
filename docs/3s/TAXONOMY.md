# Filename grammar, difficulty ladder, chart types

Difficulty and chart type are **not stored inside the chart file**. They are
encoded entirely in the filename, and the game reconstructs the filename from
two index tables compiled into `3s.exe`. Nothing in the EZFF payload varies with
difficulty: every chart of a given song has identical header values apart from
`total_ticks` / `duration` where the chart is actually a different length.

## Filename grammar

From `FUN_004457a0` in `3s.exe`:

```c
sprintf(buf, "%s_%s%s.sss",
        songName,
        (&PTR_DAT_004f80c0)[DAT_0091cf30],   // chart-type character
        (&PTR_DAT_004f8098)[DAT_00921068]);  // difficulty label
```

So:

```
<song> _ <type><difficulty> . sss
   kamui _ 1 n .sss
   bleed _ 3 hell .sss
```

## The difficulty ladder — `PTR_DAT_004f8098` @ `0x004f8098`

Four pointers to one-character strings at `0x004cd298`:

| index | label | tier |
| --- | --- | --- |
| 0 | `e` | EZ |
| 1 | `n` | NM |
| 2 | `h` | HD |
| 3 | `s` | **SHD** (Super Hard) |

This is exactly the EZ2DJ four-tier ladder, which fits: 3S is an EZ2DJ-derived
engine. The table is hard-wired to four entries — the four dwords following it
are zero — so the base loader cannot address a fifth tier.

`DAT_00921068` holds the current difficulty index; it is written only by
menu/selection code (`FUN_004566e0`, `FUN_004189a0`, `FUN_00441330`,
`FUN_00443260`), never by the loader.

**SHD is vestigial.** Of 898 `.sss` files in the shipped listing, only 8 use the
`s` label:

```
Aquaris_1s   climax_1s   complex_1s   go_1s
night_1s     ppm_1s      spell_1s     ZEROIZE_1s
```

All eight are chart type `1`; no type `2` or `3` chart has an SHD variant. A
carried-over slot from the EZ2DJ lineage that 3S barely populated.

## The chart types — `PTR_DAT_004f80c0` @ `0x004f80c0`

Four pointers to one-character strings at `0x004cd2a8`, indexed by
`DAT_0091cf30`:

| index | filename char | shipped files | lane set (see `LANES.md`) |
| --- | --- | --- | --- |
| 0 | `3` | 280 | 3 + 3 lanes |
| 1 | `1` | 391 | 5 keys + 1 + 1 |
| 2 | `2` | 226 | 10 keys + 3 + 1 |
| 3 | `4` | **0** | — |

Note the internal index order is `3, 1, 2, 4`, not `1, 2, 3, 4`.

The fourth slot (`"4"`) has **zero** files among the 898 shipped charts: a
scrapped or unshipped chart type.

The three shipped types line up with the three difficulty ratings 3S publishes
per song (Percussion, Arcade, Professional), and with the lane counts observed
in the charts themselves. Which internal index maps to which named mode is
inferred, not proven — see `LANES.md`.

## Non-base difficulty labels

`FUN_004457a0` has a second branch, taken when `DAT_00bdfcdc >= 1`:

```c
sprintf(buf, "%s_%s%s.sss",
        songName,
        (&DAT_00bdfd04)[DAT_0091cdf0],   // type char, remapped
        param_2);                        // difficulty label passed in as a string
```

Here the label is not table-indexed at all — it is an arbitrary string taken
from the game's internal chart database. That database block in `.rdata` holds a
4-byte-stride array of inline label strings from roughly `0x004c9f80` to
`0x004ca940`, running parallel to a song-key array at `0x004ca0c0`–`0x004ca6dc`
(`d001`…`d050`, then song keys such as `kamui`, `bleed`, `firestorm`, `eraser`).

Labels found there, with counts across the 898 shipped charts:

```
n 327   h 250   e 205   ax 52   s 8    os 6    xd 5    sur 4   era 4
rm 4    ah 4    as 4    ms 4   hell 3  rmx 3   un 2    cb 2    or 2
ss 1    amb 1   ln 1    mr 1   cv 1    dd 1    a 1     h1 1
```

plus `rnd` (random) entries in the database. These are chart *variants* —
remixes, quest/extra charts, special sets — not additional ladder tiers. Note
that `e`, `n`, `h`, `s` appear in this array too, so the database stores the
label string per chart entry rather than an index.

## The orphaned uppercase set — likely the scrapped EX ladder

30 shipped files use **uppercase** `E` / `N` / `H`, covering exactly five songs:

```
Aquaris:  aquaris_2E  aquaris_3E  aquaris_3N
Envy:     envy_1E envy_1N envy_1H  envy_2E envy_2N envy_2H  envy_3E envy_3N envy_3H
Future:   future_2E future_2N future_3E future_3N future_3H
Go:       go_2E go_2H go_3E go_3N go_3H
JMJ:      jmj_1E jmj_1N jmj_1H  jmj_2E jmj_2N jmj_2H  jmj_3E jmj_3N jmj_3H
```

`Envy` and `JMJ` have a *complete* parallel ladder: all three chart types ×
`E`/`N`/`H`. That is a second full chart set per song, not a stray rename.

Crucially, **no uppercase label table exists anywhere in the binary.** Scanning
all of `.rdata` and `.data` for pointer tables of one-character uppercase
strings, and scanning the chart-database label block for inline uppercase
labels, returns nothing. The base loader therefore cannot name these files: they
are reachable only through the `param_2` path, and nothing in the static tables
feeds it those strings.

That is the signature of a scrapped feature: the chart data shipped, the
selection wiring never did. It is the strongest candidate for the planned-but-
dropped EX ladder. (The community wiki describes an EX difficulty in the context
of Renascence Burst and an EXTEND variant tested at one Japanese location, so
some EX content may have shipped in a different build than this one; the
build analysed here has the files but no way to reach them.)

## Difficulty *level* numbers

The numeric level (3S uses 1–12, extended to 1–14 in Renascence Burst) is also
**not** in the chart file. It lives in the song database in the executable
(`FUN_00411ff0` enumerates songs with their per-mode ratings). A chart file
carries no level, no difficulty, and no song title — the filename is the only
key.

## Extension fallbacks

The loader tries, in order:

```
<song>_<type><diff>.3s      # never present in the shipped listing
<song>_<type><diff>.sss     # what actually ships
<song>_<type><diff>.ez      # EZ2AC legacy
<song>_<type><diff>.ezi     # EZ2AC legacy
```

The `.ez` / `.ezi` fallbacks are reached only when the `.3s` open fails. Since no
`.3s` file exists in the file listing, that failure is the normal path, and a
plain EZ2AC `.ez`/`.ezi` chart is in principle loadable — untested here, as no
such file was available.
