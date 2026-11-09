#!/usr/bin/env python3
"""Render the README cover images: real btop screens with their graphs refilled from synthetic data.

Input: art/captures/<name>.cells.json, a 160x45 grid of [char, fg, bg, bold] cells captured from the real btop running in a
virtual terminal (pyte). Layout, labels, borders, colors and the log-time axis come from that capture. Every graph, the
per-core mini graphs and the meters are redrawn from a seeded, synthetic hour of activity that is resampled onto the same
non-linear time axis the logtime patch uses, then encoded with btop's braille rules and tokyo-night gradients.

Usage: python3 art/make_covers.py      (needs Pillow; writes assets/cover-gpurig.png and assets/cover-z13.png)
"""
import json, math, random, re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"

#* tokyo-night theme values (btop/themes/tokyo-night.theme)
BG, FG = "#1a1b26", "#cfc9c2"
GRAD = ("#9ece6a", "#e0af68", "#f7768e")      #? start, mid, end (cpu/free/used/download/upload/temp all share it)
METER_BG = "#565f89"


def hexrgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def gradient(i):
    """btop 101-step gradient: start->mid over 0-50, mid->end over 50-100."""
    s, m, e = (hexrgb(c) for c in GRAD)
    a, b, t = (s, m, i / 50) if i <= 50 else (m, e, (i - 50) / 50)
    return "#%02x%02x%02x" % tuple(round(a[k] + (b[k] - a[k]) * t) for k in range(3))


# ---------------------------------------------------------------------------------------------------------------------
#* Synthetic data: one value per second for an hour, oldest first
HIST = 3600


def bursts(rng, base, noise, n, lo, hi, dur, recent_bias=1.0):
    v = [max(0.0, base + rng.gauss(0, noise)) for _ in range(HIST)]
    for _ in range(n):
        start = int(HIST * (1 - rng.random() ** recent_bias))
        length = rng.randint(*dur)
        level = rng.uniform(lo, hi)
        for t in range(start, min(HIST, start + length)):
            ramp = min(1.0, (t - start + 1) / 4, (start + length - t) / 4)
            v[t] = max(v[t], level * ramp + rng.gauss(0, noise))
    return [min(100.0, max(0.0, x)) for x in v]


def llm_turns(rng, n, recent_bias=1.6):
    """GPU-style activity: short prefill spikes to ~100% followed by long decode plateaus."""
    v = [max(0.0, 2 + rng.gauss(0, 1)) for _ in range(HIST)]
    for _ in range(n):
        start = int(HIST * (1 - rng.random() ** recent_bias))
        prefill, decode = rng.randint(3, 12), rng.randint(15, 90)
        for t in range(start, min(HIST, start + prefill)): v[t] = 97 + rng.random() * 3
        for t in range(start + prefill, min(HIST, start + prefill + decode)): v[t] = rng.uniform(70, 92)
    for t in range(HIST - 26, HIST - 4): v[t] = rng.uniform(80, 96)   #? A turn in progress right now
    for t in range(HIST - 4, HIST): v[t] = 99
    return [min(100.0, max(0.0, x)) for x in v]


# ---------------------------------------------------------------------------------------------------------------------
#* The logtime patch's TimeAxis, ported: slot q starts H*expm1(k q/S)/expm1(k) samples back
def resample(series, slots):
    H, n = float(len(series)), len(series)
    k = 0.0
    if H / slots > 1.0:
        lo, hi = 0.0, 60.0
        for _ in range(60):
            mid = (lo + hi) / 2
            (lo, hi) = (mid, hi) if H * math.expm1(mid / slots) / math.expm1(mid) > 1.0 else (lo, mid)
        k = (lo + hi) / 2
    age = lambda q: H * math.expm1(k * q / slots) / math.expm1(k) if k > 0 else float(q)
    P = [0.0]
    for a in range(n): P.append(P[-1] + series[n - 1 - a])
    integ = lambda x: P[n] if x >= n else P[int(x)] + (x - int(x)) * series[n - 1 - int(x)]
    out = []
    for q in range(slots, -1, -1):
        x0, x1 = age(q), min(age(q + 1), float(n))
        if x0 >= n: continue
        out.append((integ(x1) - integ(x0)) / (x1 - x0))
    return out[-slots:]


#* Braille cells: fill levels 0-4 per half column, dots bottom-up (graph grows up) or top-down (inverted graph)
UP_L, UP_R = (0x40, 0x04, 0x02, 0x01), (0x80, 0x20, 0x10, 0x08)
DN_L, DN_R = (0x01, 0x02, 0x04, 0x40), (0x08, 0x10, 0x20, 0x80)


def braille(l, r, invert):
    L, R = (DN_L, DN_R) if invert else (UP_L, UP_R)
    return chr(0x2800 + sum(L[:l]) + sum(R[:r]))


def graph_cells(values, width, height, invert=False, no_zero=True):
    """btop Graph::_create: two values per character, rows colored by their height in the gradient."""
    vals = [0.0] * max(0, width * 2 - len(values)) + values[-width * 2:]
    rows = []
    for hz in range(height):
        hi = round(100 * (height - hz) / height) if height > 1 else 100
        lo = round(100 * (height - hz - 1) / height) if height > 1 else 0
        row = []
        for c in range(width):
            lv = []
            for v in vals[2 * c:2 * c + 2]:
                floor = 1 if (no_zero and hz == height - 1) else 0
                lv.append(4 if v >= hi else floor if v <= lo else max(floor, min(4, round((v - lo) * 4 / (hi - lo) + 0.1))))
            row.append(braille(lv[0], lv[1], invert))
        rows.append(row)
    if invert: rows.reverse()
    colors = [gradient(round(i * 100 / height)) if invert else gradient(100 - round((i - 1) * 100 / height)) for i in range(1, height + 1)]
    return rows, colors


# ---------------------------------------------------------------------------------------------------------------------
class Screen:
    def __init__(self, cells):
        self.c = cells

    def text(self, y):
        return "".join(cell[0] for cell in self.c[y])

    def put(self, y, x, ch, fg=None, bold=None):
        cell = self.c[y][x]
        cell[0] = ch
        if fg is not None: cell[1] = fg.lstrip("#")
        if bold is not None: cell[3] = bold

    def write(self, y, x, s, fg=None):
        for i, ch in enumerate(s): self.put(y, x + i, ch, fg)

    def graph(self, x0, x1, y0, y1, values, invert=False):
        """Redraw braille/blank cells of a graph area; labels drawn over the graph stay."""
        width, height = x1 - x0, y1 - y0
        rows, colors = graph_cells(resample(values, width * 2), width, height, invert)
        for r in range(height):
            for c in range(width):
                ch = self.c[y0 + r][x0 + c][0]
                if ch == " " or 0x2800 <= ord(ch) <= 0x28FF:
                    self.put(y0 + r, x0 + c, rows[r][c] if rows[r][c] != "⠀" else " ", colors[r])

    def mini(self, y, x, width, values):
        """Height-1 graph: each character colored by its value."""
        vals = resample(values, width * 2)
        vals = [0.0] * (width * 2 - len(vals)) + vals
        for c in range(width):
            a, b = vals[2 * c], vals[2 * c + 1]
            lv = [max(1, min(4, round(v * 4 / 100 + 0.3))) for v in (a, b)]
            self.put(y, x + c, braille(lv[0], lv[1], False), gradient(round(max(a, b))))

    def meter(self, y, value):
        """Recolor the run of ■ on row y for <value> percent and rewrite the percentage after it."""
        t = self.text(y)
        m = re.search("■+", t)
        x0, w = m.start(), m.end() - m.start()
        for i in range(1, w + 1):
            step = round(i * 100 / w)
            self.put(y, x0 + i - 1, "■", gradient(step) if value >= step else METER_BG)
        p = re.match(r"\s*\d+%", t[m.end():])
        if p: self.write(y, m.end(), f"{round(value):>{len(p.group(0)) - 1}}%", FG)
        return m.end() + (len(p.group(0)) if p else 0)

    def temp(self, y, value):
        """Rewrite the last 'NN°C' on row y, right-aligned in the same cells."""
        m = list(re.finditer(r"\s*\d+°C", self.text(y)))[-1]
        self.write(y, m.start(), f"{value}°C".rjust(m.end() - m.start()), FG)

    def cores(self, rows, rng, label_re=r"C\d+\s*"):
        """Per-core mini graphs: 'C12 ⣀⣀⣀⣀⣀⣀ 34%' cells."""
        for y in rows:
            t = self.text(y)
            for m in re.finditer(label_re + r"([⠀-⣿]+)(\s*\d+%)", t):
                busy = rng.random() < 0.55
                series = bursts(rng, 3, 2, rng.randint(2, 9), 25, 98 if busy else 45, (10, 160), 1.4)
                if busy: series[-6:] = [rng.uniform(45, 99)] * 6
                self.mini(y, m.start(1), len(m.group(1)), series)
                pct = m.group(2)
                self.write(y, m.start(2), f"{round(series[-1]):>{len(pct) - 1}}%", FG)


# ---------------------------------------------------------------------------------------------------------------------
#* Drawing: box-drawing characters and braille are drawn as shapes so lines join and dots stay crisp at any size
SEG = {  # up, down, left, right, rounded, heavy-up
    "─": (0, 0, 1, 1, 0, 0), "│": (1, 1, 0, 0, 0, 0), "┌": (0, 1, 0, 1, 0, 0), "┐": (0, 1, 1, 0, 0, 0),
    "└": (1, 0, 0, 1, 0, 0), "┘": (1, 0, 1, 0, 0, 0), "├": (1, 1, 0, 1, 0, 0), "┤": (1, 1, 1, 0, 0, 0),
    "┬": (0, 1, 1, 1, 0, 0), "┴": (1, 0, 1, 1, 0, 0), "┼": (1, 1, 1, 1, 0, 0), "╭": (0, 1, 0, 1, 1, 0),
    "╮": (0, 1, 1, 0, 1, 0), "╰": (1, 0, 0, 1, 1, 0), "╯": (1, 0, 1, 0, 1, 0), "┸": (1, 0, 1, 1, 0, 1),
}


def render(cells, title, out, scale=2):
    fs = 15 * scale
    font, fontb = ImageFont.truetype(FONT, fs), ImageFont.truetype(FONT_B, fs)
    cw, ch = round(font.getlength("M")), round(fs * 1.28)
    rows, cols = len(cells), len(cells[0])
    term = Image.new("RGB", (cols * cw, rows * ch), BG)
    d = ImageDraw.Draw(term)
    lw = max(1, round(scale * 1.1))
    col = lambda c, default: "#" + c if re.fullmatch(r"[0-9a-fA-F]{6}", str(c)) else default
    for y, row in enumerate(cells):
        for x, (glyph, fg, bg, bold) in enumerate(row):
            X, Y = x * cw, y * ch
            if col(bg, None): d.rectangle([X, Y, X + cw, Y + ch], fill=col(bg, BG))
            color = col(fg, FG)
            cx, cy = X + cw / 2, Y + ch / 2
            if glyph in SEG:
                u, dn, l, r, rnd, heavy = SEG[glyph]
                if rnd:
                    rad = cw / 2
                    box = {(0, 1, 0, 1): (cx, cy, cx + 2 * rad, cy + 2 * rad, 180, 270), (0, 1, 1, 0): (cx - 2 * rad, cy, cx, cy + 2 * rad, 270, 360),
                           (1, 0, 0, 1): (cx, cy - 2 * rad, cx + 2 * rad, cy, 90, 180), (1, 0, 1, 0): (cx - 2 * rad, cy - 2 * rad, cx, cy, 0, 90)}[(u, dn, l, r)]
                    d.arc(box[:4], box[4], box[5], fill=color, width=lw)
                    if dn: d.line([cx, cy + rad, cx, Y + ch], fill=color, width=lw)
                    if u: d.line([cx, Y, cx, cy - rad], fill=color, width=lw)
                    if r: d.line([cx + rad, cy, X + cw, cy], fill=color, width=lw)
                    if l: d.line([X, cy, cx - rad, cy], fill=color, width=lw)
                else:
                    if l: d.line([X, cy, cx, cy], fill=color, width=lw)
                    if r: d.line([cx, cy, X + cw, cy], fill=color, width=lw)
                    if u: d.line([cx, Y, cx, cy], fill=color, width=lw * (3 if heavy else 1))
                    if dn: d.line([cx, cy, cx, Y + ch], fill=color, width=lw)
            elif 0x2800 < ord(glyph) <= 0x28FF:
                bits = ord(glyph) - 0x2800
                order = [(0x01, 0, 0), (0x02, 0, 1), (0x04, 0, 2), (0x40, 0, 3), (0x08, 1, 0), (0x10, 1, 1), (0x20, 1, 2), (0x80, 1, 3)]
                rr = cw * 0.15
                for bit, dx, dy in order:
                    if bits & bit:
                        px, py = X + cw * (0.3 + 0.42 * dx), Y + ch * (0.14 + 0.24 * dy)
                        d.ellipse([px - rr, py - rr, px + rr, py + rr], fill=color)
            elif glyph == "■":
                d.rectangle([X + cw * 0.12, Y + ch * 0.28, X + cw * 0.88, Y + ch * 0.72], fill=color)
            elif glyph.strip():
                d.text((X, Y + ch * 0.08), glyph, font=fontb if bold else font, fill=color)

    #? Window chrome: gradient backdrop, soft shadow, rounded window with a title bar
    pad, bar, rad = 56 * scale, 34 * scale, 14 * scale
    W, Hh = term.width + 2 * pad, term.height + bar + 2 * pad
    canvas = Image.new("RGB", (W, Hh))
    c1, c2, c3 = hexrgb("#7aa2f7"), hexrgb("#bb9af7"), hexrgb("#1a1b26")
    for yy in range(Hh):
        t = yy / Hh
        base = tuple(round(c1[k] + (c2[k] - c1[k]) * t) for k in range(3))
        ImageDraw.Draw(canvas).line([(0, yy), (W, yy)], fill=tuple(round(base[k] * 0.55 + c3[k] * 0.45) for k in range(3)))
    shadow = Image.new("L", (W, Hh), 0)
    ImageDraw.Draw(shadow).rounded_rectangle([pad, pad + 10 * scale, W - pad, Hh - pad + 10 * scale], rad, fill=170)
    canvas.paste(Image.new("RGB", (W, Hh), (8, 8, 16)), (0, 0), shadow.filter(ImageFilter.GaussianBlur(18 * scale)))
    win = Image.new("RGB", (term.width, term.height + bar), "#16161e")
    wd = ImageDraw.Draw(win)
    for i, dot in enumerate(("#f7768e", "#e0af68", "#9ece6a")):
        cx = 22 * scale + i * 22 * scale
        wd.ellipse([cx - 7 * scale, bar / 2 - 7 * scale, cx + 7 * scale, bar / 2 + 7 * scale], fill=dot)
    tf = ImageFont.truetype(FONT_B, 13 * scale)
    wd.text(((term.width - tf.getlength(title)) / 2, bar / 2 - 9 * scale), title, font=tf, fill="#a9b1d6")
    win.paste(term, (0, bar))
    mask = Image.new("L", win.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, win.width - 1, win.height - 1], rad, fill=255)
    canvas.paste(win, (pad, pad), mask)
    canvas.save(out, optimize=True)
    print("wrote", out.relative_to(ROOT), canvas.size)


# ---------------------------------------------------------------------------------------------------------------------
def gpurig():
    rng = random.Random(7950)
    s = Screen(json.load(open(ROOT / "art/captures/gpurig.cells.json")))
    cpu = bursts(rng, 6, 2.5, 26, 30, 92, (20, 240), 1.3)
    cpu[-40:] = [min(100, 55 + rng.gauss(0, 6)) for _ in range(40)]   #? Busy right now, like the cores
    s.graph(1, 60, 1, 5, cpu)                         #? cpu total, mirrored below
    s.graph(1, 60, 5, 9, cpu, invert=True)
    end = s.meter(2, cpu[-1])
    s.mini(2, end + 1, 5, cpu)
    s.temp(2, 61)
    s.cores(range(3, 8), rng)
    gpu = llm_turns(rng, 22)
    s.graph(1, 95, 11, 15, gpu)                       #? gpu0 box, mirrored
    s.graph(1, 95, 15, 18, gpu, invert=True)
    end = s.meter(11, gpu[-1])
    s.mini(11, end + 1, 6, gpu)
    s.temp(11, 71)
    s.meter(12, 87)                                   #? power meter: rewrite the watt text by hand
    t = s.text(12); w = re.search(r"\s+\d+W", t); s.write(12, w.start(), f"{287:>{len(w.group(0)) - 1}}W")
    p = s.text(12).find("P8"); s.write(12, p, "P2")
    #? A model being served: clocks up and most of the 48 GB in use (text widths grow, so the border joins move left)
    m = s.text(10).find("210 Mhz"); s.write(10, m - 2, "┐"); s.write(10, m - 1, "1740", FG)
    m = s.text(13).find("405 Mhz"); s.write(13, m - 2, "┐"); s.write(13, m - 1, "9751", FG)
    m = s.text(13).find("841 MiB"); s.write(13, m - 1, "41.2 GiB", FG)
    m = s.text(14).rfind("2%"); s.write(14, m - 1, "86%", FG)
    io = bursts(rng, 1, 1, 30, 20, 95, (3, 40), 1.2)
    s.mini(22, 86, 72, io)
    s.graph(81, 159, 23, 33, io)
    down = bursts(rng, 4, 3, 40, 20, 96, (5, 60), 1.3)
    up = bursts(rng, 2, 2, 25, 10, 70, (5, 40), 1.3)
    s.graph(1, 132, 35, 40, down)
    s.graph(1, 132, 40, 44, up, invert=True)
    render(s.c, "btop 1.3.0 + logtime  ·  gpurig  ·  Linux  ·  Ryzen 9 7950X + RTX A6000", ROOT / "assets/cover-gpurig.png")


def z13():
    rng = random.Random(395)
    s = Screen(json.load(open(ROOT / "art/captures/z13.cells.json")))
    cpu = bursts(rng, 5, 2, 22, 25, 85, (20, 200), 1.3)
    cpu[-40:] = [min(100, 48 + rng.gauss(0, 6)) for _ in range(40)]   #? Busy right now, like the cores
    gpu = llm_turns(rng, 26)
    s.graph(1, 78, 1, 7, cpu)                         #? upper: cpu total
    s.graph(1, 78, 8, 14, gpu, invert=True)           #? lower: gpu (Radeon 8060S), below the cpu ▲▼ gpu divider
    s.meter(2, cpu[-1])
    s.cores(range(3, 11), rng)
    end = s.meter(12, gpu[-1])
    s.mini(12, end + 1, 5, gpu)
    s.temp(12, 58)
    mhz = s.text(13).find("Mhz"); s.write(13, mhz - 6, "┘"); s.write(13, mhz - 5, "2900 ", FG)
    io = bursts(rng, 1, 1, 30, 20, 95, (3, 40), 1.2)
    s.mini(17, 86, 72, io)
    s.graph(81, 159, 18, 32, io)
    down = bursts(rng, 4, 3, 40, 20, 96, (5, 60), 1.3)
    up = bursts(rng, 2, 2, 25, 10, 70, (5, 40), 1.3)
    s.graph(1, 132, 34, 39, down)
    s.graph(1, 132, 39, 44, up, invert=True)
    render(s.c, "btop4win 1.0.5 + logtime + Radeon GPU  ·  ROG Flow Z13  ·  Windows 11  ·  Ryzen AI Max+ 395", ROOT / "assets/cover-z13.png")


if __name__ == "__main__":
    import sys
    (ROOT / "assets").mkdir(exist_ok=True)
    for name in (sys.argv[1:] or ["gpurig", "z13"]):
        {"gpurig": gpurig, "z13": z13}[name]()
