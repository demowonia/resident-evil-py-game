"""Atmosphere + juice: drifting leaves, fireflies, rain, fog, lightning, particles, synthesized SFX."""
import math
import random

import numpy as np
import pygame

# ============================================================================================
# helpers
# ============================================================================================


def radial_alpha(size, color, power=2.0, max_alpha=255):
    """Soft round blob with per-pixel alpha (normal blending)."""
    r = size / 2
    y, x = np.ogrid[:size, :size]
    d = np.hypot(x - r + 0.5, y - r + 0.5) / r
    a = np.clip(1 - d, 0, 1) ** power * max_alpha
    arr = np.zeros((size, size, 4), np.uint8)
    arr[..., 0], arr[..., 1], arr[..., 2] = color
    arr[..., 3] = a.astype(np.uint8)
    return pygame.image.frombuffer(arr.tobytes(), (size, size), "RGBA").copy().convert_alpha()


def radial_add(size, color, power=2.0, strength=1.0):
    """Soft round blob meant for additive blending (BLEND_RGB_ADD)."""
    r = size / 2
    y, x = np.ogrid[:size, :size]
    d = np.hypot(x - r + 0.5, y - r + 0.5) / r
    a = np.clip(1 - d, 0, 1) ** power * strength
    arr = np.zeros((size, size, 3), np.uint8)
    for i in range(3):
        arr[..., i] = np.clip(a * color[i], 0, 255).astype(np.uint8)
    return pygame.image.frombuffer(arr.tobytes(), (size, size), "RGB").copy().convert()


def ellipse_alpha(w, h, color, power=2.0, max_alpha=255):
    yy, xx = np.mgrid[:h, :w]
    d = np.hypot((xx - w / 2 + 0.5) / (w / 2), (yy - h / 2 + 0.5) / (h / 2))
    a = np.clip(1 - d, 0, 1) ** power * max_alpha
    arr = np.zeros((h, w, 4), np.uint8)
    arr[..., 0], arr[..., 1], arr[..., 2] = color
    arr[..., 3] = a.astype(np.uint8)
    return pygame.image.frombuffer(arr.tobytes(), (w, h), "RGBA").copy().convert_alpha()


def vignette(size, color=(0, 0, 0), inner=0.5, power=1.7, max_alpha=210):
    w, h = size
    yy, xx = np.mgrid[:h, :w]
    d = np.hypot((xx - w / 2) / (w / 2), (yy - h / 2) / (h / 2)) / 1.2
    a = np.clip((d - inner) / (1.0 - inner), 0, 1) ** power * max_alpha
    arr = np.zeros((h, w, 4), np.uint8)
    arr[..., 0], arr[..., 1], arr[..., 2] = color
    arr[..., 3] = a.astype(np.uint8)
    return pygame.image.frombuffer(arr.tobytes(), (w, h), "RGBA").copy().convert_alpha()


# ============================================================================================
# leaves (pixel-art style so they match the sprites)
# ============================================================================================
LEAF_PALETTES = [
    ((120, 185, 65), (78, 150, 55), (46, 108, 58)),     # fresh green
    ((150, 195, 70), (100, 160, 52), (60, 115, 45)),    # yellow green
    ((70, 150, 90), (45, 115, 75), (28, 80, 60)),       # teal green
    ((240, 165, 55), (222, 118, 36), (170, 80, 28)),    # amber
    ((235, 130, 45), (200, 88, 30), (140, 58, 25)),     # orange
]
LEAF_OUTLINE = (14, 34, 22)


def make_leaf_pixels(palette, variant=0):
    """A tiny 16x10 leaf, tip pointing right. Drawn without anti-aliasing = pixel art."""
    w, h = 16, 10
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    light, mid, dark = palette
    cy = (h - 1) / 2
    top, bot = [], []
    n = 15
    for i in range(n + 1):
        t = i / n
        if variant == 1:        # slimmer, willow-like
            prof = math.sin(math.pi * t ** 0.9) * 0.40
        else:                   # classic oval
            prof = math.sin(math.pi * t ** 0.75) * 0.50
        x = 0.5 + t * (w - 3)
        top.append((x, cy - prof * (h - 1)))
        bot.append((x, cy + prof * (h - 1)))
    poly = top + bot[::-1]
    pygame.draw.polygon(s, LEAF_OUTLINE, poly)
    inner_top = [(x, y + 1) for x, y in top[1:-1]]
    inner_bot = [(x, y - 1) for x, y in bot[1:-1]]
    if len(inner_top) > 2:
        pygame.draw.polygon(s, mid, inner_top + inner_bot[::-1])
        pygame.draw.polygon(s, light, inner_top + [(x, cy) for x, _ in inner_top[::-1]])
        pygame.draw.polygon(s, dark, inner_bot + [(x, cy + 0.5) for x, _ in inner_bot[::-1]])
    pygame.draw.line(s, light, (1, cy), (w - 2, cy))              # midrib
    for vx in (5, 8, 11):                                           # veins
        pygame.draw.line(s, dark, (vx, cy), (vx + 2, cy - 2))
        pygame.draw.line(s, dark, (vx, cy), (vx + 2, cy + 2))
    pygame.draw.line(s, LEAF_OUTLINE, (0, cy), (1, cy))             # stem
    return s


class LeafBank:
    """Pre-built leaves at a few pixel sizes."""

    def __init__(self):
        self.images = {}   # (palette_idx, variant, scale) -> surface
        for pi, pal in enumerate(LEAF_PALETTES):
            for v in (0, 1):
                base = make_leaf_pixels(pal, v)
                for sc in (1, 2, 3, 4):
                    w, h = base.get_size()
                    self.images[(pi, v, sc)] = pygame.transform.scale(base, (w * sc, h * sc)).convert_alpha()

    def get(self, pi, v, sc):
        return self.images[(pi, v, sc)]


class Leaf:
    __slots__ = ("x", "y", "vy", "t", "ph", "amp", "sf", "spin", "flip", "flip_sp", "pi", "v", "sc",
                 "depth", "alpha", "angle0", "front")

    def __init__(self, bank, width, height, front, first=False):
        self.reset(bank, width, height, front, first)

    def reset(self, bank, width, height, front, first=False):
        self.front = front
        self.pi = random.choices(range(len(LEAF_PALETTES)), weights=[5, 4, 4, 3, 3])[0]
        self.v = random.choice((0, 0, 1))
        if front:
            self.sc = random.choice((3, 4, 4))
            self.vy = random.uniform(70, 130)
            self.depth = 1.4
            self.alpha = random.randint(215, 245)
        else:
            self.sc = random.choice((1, 2, 2, 3))
            self.vy = random.uniform(28, 70)
            self.depth = 0.7
            self.alpha = random.randint(150, 215)
        self.x = random.uniform(-60, width + 60)
        self.y = random.uniform(-height, height) if first else random.uniform(-120, -20)
        self.t = random.uniform(0, 100)
        self.ph = random.uniform(0, math.tau)
        self.amp = random.uniform(10, 38) * (1.3 if front else 1.0)
        self.sf = random.uniform(0.9, 2.2)
        self.spin = random.uniform(-70, 70)
        self.flip = random.uniform(0, math.tau)
        self.flip_sp = random.uniform(1.5, 4.0)
        self.angle0 = random.uniform(0, 360)


class LeafSystem:
    """Two layers of falling leaves (behind and in front of the action) pushed around by gusts of wind."""

    def __init__(self, size, back=34, front=7):
        self.w, self.h = size
        self.bank = LeafBank()
        self.back = [Leaf(self.bank, self.w, self.h, False, True) for _ in range(back)]
        self.front = [Leaf(self.bank, self.w, self.h, True, True) for _ in range(front)]
        self.time = 0.0
        self.wind = 0.0

    def wind_at(self, t):
        gust = max(0.0, math.sin(t * 0.13 + 1.0)) ** 5 * 150      # a strong gust every ~45 s
        gust += max(0.0, math.sin(t * 0.31 + 4.0)) ** 7 * 90
        return 22 * math.sin(t * 0.37) + 14 * math.sin(t * 0.91 + 1.3) + 12 + gust

    def update(self, dt):
        self.time += dt
        self.wind = self.wind_at(self.time)
        for group, front in ((self.back, False), (self.front, True)):
            for lf in group:
                lf.t += dt
                lf.flip += lf.flip_sp * dt
                lf.x += (self.wind * lf.depth + math.cos(lf.t * lf.sf + lf.ph) * lf.amp * lf.sf) * dt
                lf.y += (lf.vy + math.sin(lf.t * lf.sf * 0.5 + lf.ph) * 16 + abs(self.wind) * 0.12) * dt
                lf.angle0 += lf.spin * dt
                if lf.y > self.h + 80 or lf.x > self.w + 140 or lf.x < -200:
                    lf.reset(self.bank, self.w, self.h, front)
                    if self.wind > 40 and random.random() < 0.5:     # during a gust leaves also blow in from the left
                        lf.x = random.uniform(-150, 0)
                        lf.y = random.uniform(0, self.h * 0.7)

    def draw(self, surf, front):
        for lf in (self.front if front else self.back):
            img = self.bank.get(lf.pi, lf.v, lf.sc)
            squash = abs(math.cos(lf.flip))
            if squash < 0.999:
                w, h = img.get_size()
                img = pygame.transform.scale(img, (w, max(2, int(h * (0.25 + 0.75 * squash)))))
            angle = lf.angle0 * 0.25 + math.sin(lf.t * lf.sf + lf.ph) * 38
            img = pygame.transform.rotate(img, angle)
            if lf.alpha < 255:
                img.set_alpha(lf.alpha)
            surf.blit(img, img.get_rect(center=(lf.x, lf.y)))


# ============================================================================================
# fireflies / spores floating in the air
# ============================================================================================
class Fireflies:
    def __init__(self, size, n=30):
        self.w, self.h = size
        self.glows = [radial_add(s, (150, 255, 90), 2.2, 1.0) for s in (14, 22, 34)]
        self.items = []
        for _ in range(n):
            self.items.append({
                "x": random.uniform(0, self.w), "y": random.uniform(120, self.h - 40),
                "p": random.uniform(0, 100), "s": random.uniform(0.15, 0.6),
                "g": random.choice((0, 0, 1, 2)), "f": random.uniform(0.8, 2.4),
            })

    def update(self, dt):
        for it in self.items:
            it["p"] += dt * it["s"]
            it["x"] += (math.sin(it["p"] * 2.1) * 18 + 6) * dt
            it["y"] += math.cos(it["p"] * 1.7) * 14 * dt
            if it["x"] > self.w + 30:
                it["x"] = -30
            it["y"] = min(max(it["y"], 100), self.h - 20)

    def draw(self, surf, t):
        for it in self.items:
            k = 0.5 + 0.5 * math.sin(t * it["f"] + it["p"] * 5)
            if k < 0.12:
                continue
            g = self.glows[it["g"]]
            if k < 0.9:
                g = g.copy()
                g.fill((int(255 * k),) * 3, special_flags=pygame.BLEND_RGB_MULT)
            surf.blit(g, g.get_rect(center=(it["x"], it["y"])), special_flags=pygame.BLEND_RGB_ADD)


# ============================================================================================
# rain on the glass dome, drifting fog, lightning
# ============================================================================================
class Rain:
    def __init__(self, size, region_h=300, n=80):
        self.w = size[0]
        self.rh = region_h
        self.layer = pygame.Surface((self.w, region_h))
        self.layer.set_colorkey((0, 0, 0))
        self.layer.set_alpha(70)
        self.drops = [[random.uniform(0, self.w), random.uniform(0, region_h), random.uniform(500, 850),
                       random.randint(10, 24)] for _ in range(n)]

    def update(self, dt):
        for d in self.drops:
            d[1] += d[2] * dt
            d[0] -= d[2] * 0.2 * dt
            if d[1] > self.rh:
                d[0] = random.uniform(0, self.w + 120)
                d[1] = random.uniform(-40, 0)

    def draw(self, surf):
        self.layer.fill((0, 0, 0))
        for x, y, v, ln in self.drops:
            pygame.draw.line(self.layer, (170, 200, 225), (x, y), (x - ln * 0.2, y - ln), 1)
        surf.blit(self.layer, (0, 0))


class Fog:
    def __init__(self, size):
        self.w, self.h = size
        self.blobs = [ellipse_alpha(720, 190, (120, 160, 130), 1.6, 46) for _ in range(2)]
        self.items = [{"x": random.uniform(-300, self.w), "y": random.uniform(self.h * 0.72, self.h * 0.9),
                       "v": random.uniform(6, 16), "b": i % 2} for i in range(7)]

    def update(self, dt):
        for it in self.items:
            it["x"] += it["v"] * dt
            if it["x"] > self.w + 100:
                it["x"] = -760

    def draw(self, surf):
        for it in self.items:
            surf.blit(self.blobs[it["b"]], (it["x"], it["y"]))


class Lightning:
    """Rare double flash + delayed thunder."""

    def __init__(self, size):
        self.flash = 0.0
        self.timer = random.uniform(9, 16)
        self.sequence = []
        self.target = 0.0
        self.seq_t = 0.0
        self.thunder_in = None
        self.overlay = pygame.Surface(size)

    def update(self, dt, on_thunder):
        self.timer -= dt
        if self.timer <= 0:
            self.timer = random.uniform(14, 28)
            self.sequence = [(0.0, 0.9), (0.09, 0.0), (0.17, 0.65), (0.45, 0.0)]
            self.seq_t = 0.0
            self.thunder_in = random.uniform(0.5, 1.6)
        if self.sequence:
            self.seq_t += dt
            while self.sequence and self.seq_t >= self.sequence[0][0]:
                _, self.target = self.sequence.pop(0)
        self.flash += (self.target - self.flash) * min(1.0, dt * 22)
        if self.thunder_in is not None:
            self.thunder_in -= dt
            if self.thunder_in <= 0:
                self.thunder_in = None
                on_thunder()

    def draw(self, surf):
        if self.flash > 0.02:
            v = int(95 * self.flash)
            self.overlay.fill((v * 0.8, v * 0.95, v))
            surf.blit(self.overlay, (0, 0), special_flags=pygame.BLEND_RGB_ADD)


# ============================================================================================
# particles + floating text
# ============================================================================================
class Particles:
    def __init__(self, leaf_bank):
        self.items = []
        self.bank = leaf_bank
        self.glow = radial_add(30, (255, 190, 80), 2.0, 1.0)
        self.glow_green = radial_add(30, (120, 255, 110), 2.0, 1.0)

    # kind: spark | dot | leaf | smoke | ring
    def sparks(self, pos, n, colors=((255, 220, 120), (255, 150, 40)), speed=(140, 420), life=(0.25, 0.6),
               gravity=600, spread=math.tau, direction=0.0):
        for _ in range(n):
            a = direction + random.uniform(-spread / 2, spread / 2)
            v = random.uniform(*speed)
            lf = random.uniform(*life)
            self.items.append(["spark", pos[0], pos[1], math.cos(a) * v, math.sin(a) * v,
                               lf, lf, random.choice(colors), gravity, 0])

    def leaves(self, pos, n, speed=(100, 380), life=(0.7, 1.4)):
        for _ in range(n):
            a = random.uniform(0, math.tau)
            v = random.uniform(*speed)
            life_v = random.uniform(*life)
            self.items.append(["leaf", pos[0], pos[1], math.cos(a) * v, math.sin(a) * v - 120, life_v, life_v,
                               (random.randrange(len(LEAF_PALETTES)), random.choice((0, 1))), 380,
                               random.uniform(0, 360)])

    def smoke(self, pos, n, color=(120, 130, 110), size=(10, 22), life=(0.5, 1.0)):
        for _ in range(n):
            a = random.uniform(0, math.tau)
            v = random.uniform(20, 90)
            lf = random.uniform(*life)
            self.items.append(["smoke", pos[0], pos[1], math.cos(a) * v, math.sin(a) * v - 30, lf, lf,
                               (color, random.uniform(*size)), -20, 0])

    def ring(self, pos, color=(255, 230, 150), r1=60, life=0.3):
        self.items.append(["ring", pos[0], pos[1], 0, 0, life, life, (color, r1), 0, 0])

    def update(self, dt):
        out = []
        for p in self.items:
            p[5] -= dt
            if p[5] <= 0:
                continue
            p[1] += p[3] * dt
            p[2] += p[4] * dt
            p[4] += p[8] * dt
            if p[0] in ("smoke", "spark"):
                p[3] *= (1 - min(1, 2.2 * dt))
            if p[0] == "leaf":
                p[9] += 300 * dt
                p[3] *= (1 - min(1, 1.2 * dt))
            out.append(p)
        self.items = out

    def draw(self, surf):
        for kind, x, y, vx, vy, life, maxlife, data, g, ang in self.items:
            k = life / maxlife
            if kind == "spark":
                col = tuple(int(c * min(1, k * 1.6)) for c in data)
                pygame.draw.line(surf, col, (x, y), (x - vx * 0.03, y - vy * 0.03), 2 if k > 0.4 else 1)
            elif kind == "leaf":
                img = self.bank.get(data[0], data[1], 1 if k < 0.35 else 2)
                img = pygame.transform.rotate(img, ang)
                if k < 0.4:
                    img.set_alpha(int(255 * k / 0.4))
                surf.blit(img, img.get_rect(center=(x, y)))
            elif kind == "smoke":
                color, size = data
                r = int(size * (1.6 - k))
                s = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
                pygame.draw.circle(s, (*color, int(90 * k)), (r, r), r)
                surf.blit(s, (x - r, y - r))
            elif kind == "ring":
                color, r1 = data
                r = int(r1 * (1 - k) + 4)
                col = tuple(int(c * k) for c in color)
                pygame.draw.circle(surf, col, (int(x), int(y)), r, max(1, int(5 * k)))


class FloatingText:
    def __init__(self):
        self.items = []

    def add(self, text, pos, color=(255, 240, 160), size=34, life=0.9, vy=-70):
        self.items.append([text, pos[0], pos[1], vy, life, life, color, size])

    def update(self, dt):
        out = []
        for it in self.items:
            it[4] -= dt
            if it[4] <= 0:
                continue
            it[2] += it[3] * dt
            it[3] *= (1 - min(1, 1.8 * dt))
            out.append(it)
        self.items = out

    def draw(self, surf, font_fn):
        for text, x, y, vy, life, maxlife, color, size in self.items:
            k = life / maxlife
            pop = 1.0 + max(0.0, (k - 0.82)) * 2.2           # quick pop-in
            f = font_fn(int(size * pop))
            img = f.render(text, True, color)
            shadow = f.render(text, True, (10, 20, 12))
            a = int(255 * min(1.0, k * 2.2))
            img.set_alpha(a)
            shadow.set_alpha(a)
            r = img.get_rect(center=(x, y))
            for ox, oy in ((-2, 0), (2, 0), (0, -2), (0, 2), (2, 2)):
                surf.blit(shadow, r.move(ox, oy))
            surf.blit(img, r)


# ============================================================================================
# synthesized sound effects (no audio files needed)
# ============================================================================================
SR = 44100


def _t(n):
    return np.arange(n) / SR


def _env(n, decay):
    return np.exp(-np.linspace(0, 1, n, endpoint=False) * decay)


def _noise(n):
    return np.random.uniform(-1, 1, n)


def _lowpass(x, k):
    if k <= 1:
        return x
    c = np.cumsum(np.insert(x, 0, 0))
    out = (c[k:] - c[:-k]) / k
    return np.concatenate([np.full(k - 1, out[0]), out])[:len(x)]


def _sweep(n, f0, f1):
    f = np.linspace(f0, f1, n)
    return np.sin(2 * np.pi * np.cumsum(f) / SR)


def _sound(x, vol=0.7):
    x = np.clip(x, -1, 1) * vol
    s16 = (x * 32767).astype(np.int16)
    return pygame.sndarray.make_sound(np.ascontiguousarray(np.column_stack([s16, s16])))


class Sfx:
    def __init__(self, enabled=True):
        self.enabled = False
        self.sounds = {}
        if not enabled:
            return
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(44100, -16, 2, 512)
            pygame.mixer.set_num_channels(24)
            self._build()
            self.enabled = True
        except Exception as e:                                   # noqa: BLE001
            print("[sfx] audio disabled:", e)

    def _build(self):
        S = self.sounds
        n = int(SR * 0.30)
        click = np.zeros(n)
        click[:90] = _noise(90) * 1.3
        S["shot"] = _sound(click + _lowpass(_noise(n), 6) * _env(n, 16) * 0.9 +
                           _sweep(n, 190, 45) * _env(n, 11) * 0.9, 0.75)

        n = int(SR * 0.55)
        t = _t(n)
        ding = (np.sin(2 * np.pi * 660 * t) + 0.6 * np.sin(2 * np.pi * 990 * t) + 0.3 * np.sin(2 * np.pi * 1480 * t))
        S["orb"] = _sound(ding * _env(n, 7) * 0.45 + _noise(n) * _env(n, 35) * 0.35, 0.8)

        n = int(SR * 0.22)
        S["body"] = _sound(_sweep(n, 150, 60) * _env(n, 16) + _lowpass(_noise(n), 10) * _env(n, 20) * 0.7, 0.8)

        n = int(SR * 0.30)
        S["head"] = _sound(_sweep(n, 700, 200) * _env(n, 12) * 0.7 + _noise(n) * _env(n, 24) * 0.55 +
                           _sweep(n, 120, 50) * _env(n, 14) * 0.6, 0.8)

        n = int(SR * 0.20)
        S["pop"] = _sound(_sweep(n, 260, 1200) * _env(n, 14) * 0.8 + _lowpass(_noise(n), 3) * _env(n, 30) * 0.4, 0.7)

        n = int(SR * 0.55)
        t = _t(n)
        saw = 2 * ((t * 70) % 1) - 1
        S["hurt"] = _sound(saw * _env(n, 4.5) * 0.7 + _sweep(n, 120, 40) * _env(n, 5) * 0.8 +
                           _lowpass(_noise(n), 8) * _env(n, 7) * 0.5, 0.85)

        n = int(SR * 0.6)
        r = np.zeros(n)
        for at, f in ((0.02, 1900), (0.40, 1500)):
            i = int(at * SR)
            m = n - i
            r[i:] += (_noise(m) * _env(m, 70) * 0.8 + np.sin(2 * np.pi * f * _t(m)) * _env(m, 45) * 0.5)
        S["reload"] = _sound(_lowpass(r, 2), 0.7)

        n = int(SR * 0.09)
        S["empty"] = _sound(_noise(n) * _env(n, 60) * 0.5 + np.sin(2 * np.pi * 1300 * _t(n)) * _env(n, 50) * 0.5, 0.6)

        n = int(SR * 1.6)
        S["collapse"] = _sound(_lowpass(_noise(n), 60) * _env(n, 2.6) * 1.6 + _sweep(n, 130, 30) * _env(n, 2.2) * 0.9, 0.9)

        n = int(SR * 3.0)
        env = np.minimum(np.linspace(0, 1, n) * 12, 1) * np.exp(-np.linspace(0, 1, n) * 2.2)
        rumble = _lowpass(_noise(n), 120) * 4
        S["thunder"] = _sound(rumble * env * (1 + 0.4 * np.sin(2 * np.pi * 3 * _t(n))), 0.9)

        n = int(SR * 0.55)
        t = _t(n)
        S["screech"] = _sound(_sweep(n, 1400, 2600) * _env(n, 3) * 0.5 * (0.6 + 0.4 * np.sin(2 * np.pi * 40 * t)) +
                              _lowpass(_noise(n), 2) * _env(n, 4) * 0.35, 0.6)

        n = int(SR * 0.9)
        t = _t(n)
        saw = 2 * ((t * 55) % 1) - 1
        S["roar"] = _sound((saw * 0.6 + _lowpass(_noise(n), 6) * 0.8) * np.sin(np.pi * np.linspace(0, 1, n)) ** 0.7 *
                           (0.8 + 0.2 * np.sin(2 * np.pi * 22 * t)), 0.8)

        n = int(SR * 0.6)
        S["charge"] = _sound(_sweep(n, 110, 420) * np.sin(np.pi * np.linspace(0, 1, n)) *
                             (0.7 + 0.3 * np.sin(2 * np.pi * 16 * _t(n))), 0.5)

        n = int(SR * 0.9)
        t = _t(n)
        chime = sum(np.sin(2 * np.pi * f * t) * _env(n, 4 + i) * np.clip(t * 6 - i * 0.6, 0, 1)
                    for i, f in enumerate((523, 659, 784, 1046)))
        S["win"] = _sound(chime * 0.3, 0.8)

        n = int(SR * 4.0)
        rain = _lowpass(_noise(n), 3) - _lowpass(_noise(n), 40) * 0.5
        fade = int(SR * 0.4)
        rain[:fade] *= np.linspace(0, 1, fade)
        rain[-fade:] *= np.linspace(1, 0, fade)
        S["rain"] = _sound(rain * 0.5, 0.35)

    def play(self, name, vol=1.0):
        if not self.enabled:
            return
        snd = self.sounds.get(name)
        if snd:
            snd.set_volume(min(1.0, vol))
            snd.play()

    def loop_rain(self):
        if self.enabled:
            self.sounds["rain"].set_volume(0.30)
            self.sounds["rain"].play(loops=-1, fade_ms=1500)
