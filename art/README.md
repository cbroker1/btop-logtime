# Cover art

`make_covers.py` renders `assets/cover-gpurig.png` and `assets/cover-z13.png`.

1. **Captures.** `captures/*.cells.json` are 160×45 grids of `[char, fg, bg, bold]` cells taken from the real btop on each
   machine, running in a virtual terminal (pyte) on 2026-11-08. The Z13's LAN address was replaced with `192.168.0.42`.
2. **Synthetic data.** Each graph gets a seeded hour of per-second activity: bursty CPU, GPU "LLM turns" (a short
   prefill spike, then a long decode plateau), disk and network bursts. The data is resampled with a Python port of the
   logtime patch's `TimeAxis`, encoded with btop's braille rules (two samples per character, no-zero baseline, mirrored
   graphs) and coloured with tokyo-night's gradients. Meters, per-core mini graphs, percentages and a few labels are
   rewritten to match. Everything else (layout, box titles, the time ruler, memory and disk text) is the real capture.
3. **Drawing.** Box-drawing characters and braille dots are drawn as shapes, so lines join and dots stay round. Text uses
   DejaVu Sans Mono. Output is 2× scale with a window frame.

```bash
python3 -m venv .venv && .venv/bin/pip install pillow
.venv/bin/python art/make_covers.py            # both, or: gpurig | z13
```
