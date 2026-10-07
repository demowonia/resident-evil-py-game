"""
Extra enemies for the greenhouse:

    MR. X    slow, huge, very tanky. Every few seconds he CHARGES at you - shoot him (head = big hit) to push him back.
    LICKER   fast skinless crawler. Scuttles around, then LEAPS at you. Brain = one-shot, body = two hits.
    BIRKIN   mutated brute. Only the glowing EYE on his shoulder hurts him; it shuts after each hit. Spits flesh.

All of them expose the same small interface the Game uses:
    state, hp, max_hp, pos, update(dt), draw(surf), hit_test(p) -> "weak"|"head"|"body"|None,
    hit_info(kind), on_hit(kind), die()
"""
import io
import math
import os
import random

import pygame
from pygame.math import Vector2 as V2

import pixelart

W, H = 1400, 700
FLOOR_Y = (590, 652)
FLOOR_X = (260, 1140)

# ---- difficulty knobs (tweak these to taste) -----------------------------------------------
ENEMY_HP_MULT = 1.5        # all enemies (incl. the plant mutant in main.py) have this much more HP
ENEMY_SPEED_MULT = 1.35    # walking / scuttling speed of every enemy
HITBOX_SCALE = 0.88        # < 1 shrinks every hit region around its centre (1.0 = old size)
MAX_BLOOD = 44             # max blood blotches kept on one enemy
LICKER_BASE_HP = 80        # licker used to have 30 (one brain shot); now ~3-5 brain shots (+5 HP per level)


def lerp(a, b, t):
    return a + (b - a) * t


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


ART_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "enemies")


def _load_png(name):
    """Load assets/enemies/<name>.png (works with non-ASCII Windows paths). None if missing."""
    path = os.path.join(ART_DIR, name + ".png")
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return pygame.image.load(io.BytesIO(f.read()), name + ".png").convert_alpha()


def build_art():
    """Your artwork from assets/enemies/*.png (made by tools/make_enemy_sprites.py).
    Any missing file falls back to the old procedural sprite from pixelart.py."""
    art = {}
    procedural = {
        "mrx0": lambda: pixelart.make_mrx(0), "mrx1": lambda: pixelart.make_mrx(1),
        "licker0": lambda: pixelart.make_licker(0), "licker1": lambda: pixelart.make_licker(1),
        "birkin0": lambda: pixelart.make_birkin(0, True), "birkin1": lambda: pixelart.make_birkin(1, True),
        "birkin_shut0": lambda: pixelart.make_birkin(0, False), "birkin_shut1": lambda: pixelart.make_birkin(1, False),
    }
    for key, make in procedural.items():
        art[key] = _load_png(key) or make()
    # one-frame flinch poses (shown for a split second when the enemy is hit)
    art["mrx_hurt"] = _load_png("mrx_hurt") or art["mrx0"]
    art["licker_hurt"] = _load_png("licker_hurt") or art["licker0"]
    art["birkin_hurt"] = _load_png("birkin_hurt") or art["birkin_shut0"]
    return art


_scale_cache = {}


def scaled(img, k):
    k = round(k * 20) / 20                      # quantise so the cache stays small
    key = (id(img), k)
    if key not in _scale_cache:
        w, h = img.get_size()
        _scale_cache[key] = pygame.transform.scale(img, (max(2, int(w * k)), max(2, int(h * k))))
    return _scale_cache[key]


class Enemy:
    NAME = "?"
    BONUS = 300
    DIE_TIME = 1.1
    DIE_ANGLE = 0
    # region fractions inside the sprite rect:  name -> (x, y, w, h)
    REGIONS = {}
    PAD = 6
    HIT_SHAKE = 0                                # px of flinch jitter when hit
    GORE = 0                                     # blood droplets in the death burst (0 = none)
    SPRITE_BLOOD = False                         # persistent wounds are baked into the sprite only for gore-capable enemies

    def __init__(self, game, level, x=None):
        self.g = game
        self.level = level
        self.pos = V2(x if x is not None else random.uniform(450, 950), random.uniform(*FLOOR_Y))
        self.target = V2(self.pos)
        self.pause = random.uniform(0.3, 1.2)
        self.state = "spawn"
        self.t = random.uniform(0, 5)
        self.spawn_t = 0.0
        self.die_t = 0.0
        self.flash = 0.0
        self.stun = 0.0
        self.knock = V2(0, 0)
        self.phase = 0.0
        self.moving = False
        self.facing = -1
        self.alpha = 255
        self.zoom = 1.0
        self.bob = 0.0
        self.lift = 0.0                          # extra vertical offset (leaps)
        self.rect = pygame.Rect(0, 0, 10, 10)
        self.img = None
        self.passive = False
        self.hp = self.max_hp = 100
        self.blood = []                          # [u, v, r, born, dark] blotches in sprite space (u,v = 0..1, r = fraction of width)
        self.blood_revision = 0
        self._blood_cache = {}
        self.hit_pos = None                      # screen position of the last bullet (set by Game.hit_enemy)
        self.flash_col = (170, 170, 170)         # additive hit-flash colour
        self.drawn_flip = False

    # ---- blood ---------------------------------------------------------------------------
    def uv_of(self, p):
        r = self.rect
        u = (p[0] - r.x) / max(1, r.w)
        v = (p[1] - r.y) / max(1, r.h)
        if self.drawn_flip:
            u = 1 - u
        return clamp(u, 0.06, 0.94), clamp(v, 0.06, 0.94)

    def screen_of(self, u, v):
        if self.drawn_flip:
            u = 1 - u
        return V2(self.rect.x + u * self.rect.w, self.rect.y + v * self.rect.h)

    def add_blood(self, u, v, r, dark=0.0, satellites=0):
        self.blood.append([u, v, r, self.t, dark])
        aspect = self.rect.w / max(1, self.rect.h)
        for _ in range(satellites):
            a = random.uniform(0, math.tau)
            d = r * random.uniform(1.4, 2.6)
            self.blood.append([clamp(u + math.cos(a) * d, 0.03, 0.97), clamp(v + math.sin(a) * d * aspect, 0.03, 0.97),
                               r * random.uniform(0.18, 0.4), self.t, dark])
        del self.blood[:-MAX_BLOOD]
        self.blood_revision += 1
        self._blood_cache.clear()

    def bake_blood(self, img):
        """Bake persistent blood into the sprite pixels, rather than drawing a separate layer.

        The stain is made from several soft, irregular rings and blended into the existing
        sprite colours.  That makes it read like wet/dried blood soaked into the Licker's
        flesh instead of a decal sitting on top of the artwork.
        """
        if not self.SPRITE_BLOOD or not self.blood:
            return img
        cache_key = (id(img), self.blood_revision, bool(self.drawn_flip))
        cached = self._blood_cache.get(cache_key)
        if cached is not None:
            return cached

        out = img.copy()
        w, h = out.get_size()
        px = pygame.PixelArray(out)
        try:
            for u, v, r, born, dark in self.blood:
                age = max(0.0, self.t - born)
                dry = clamp(age / 7.0, 0.0, 1.0)
                # Blood gradually settles from vivid wet red to a darker maroon.
                target = (
                    int(185 - 75 * dry),
                    int(24 - 12 * dry),
                    int(34 - 13 * dry),
                )
                cx = int((1 - u if self.drawn_flip else u) * w)
                cy = int(v * h)
                R = max(2, int(r * w))
                aspect = 0.72

                # Work directly on sprite pixels.  Irregular offsets avoid the old
                # "red circle pasted on top" appearance.
                samples = ((0.00, 1.00), (-0.32, 0.78), (0.29, 0.84),
                           (-0.16, 0.52), (0.21, 0.47))
                for ox, scale in samples:
                    rr = max(1, int(R * scale))
                    ox_px = int(ox * R)
                    oy_px = int(math.sin((u + v + ox) * 17.0) * R * 0.16)
                    for yy in range(-rr, rr + 1):
                        sy = cy + int(yy * aspect) + oy_px
                        if sy < 0 or sy >= h:
                            continue
                        for xx in range(-rr, rr + 1):
                            sx = cx + xx + ox_px
                            if sx < 0 or sx >= w or xx * xx + yy * yy > rr * rr:
                                continue
                            # Feather the edge and vary opacity for a soaked-in texture.
                            d = math.sqrt(xx * xx + yy * yy) / max(1, rr)
                            strength = (1.0 - d) ** 1.8
                            if strength <= 0.03 or random.random() > strength * 0.92:
                                continue
                            old = out.unmap_rgb(px[sx, sy])
                            # Preserve shading/highlights: tint toward blood instead of
                            # replacing the underlying artwork with a flat red blob.
                            mix = 0.38 + 0.38 * strength
                            if old[3] == 0:
                                continue
                            nr = int(old[0] * (1 - mix) + target[0] * mix)
                            ng = int(old[1] * (1 - mix) + target[1] * mix)
                            nb = int(old[2] * (1 - mix) + target[2] * mix)
                            px[sx, sy] = (nr, ng, nb, old[3])
        finally:
            del px

        self._blood_cache[cache_key] = out
        # Keep this tiny; old frame surfaces naturally fall out as animation changes.
        if len(self._blood_cache) > 8:
            self._blood_cache.pop(next(iter(self._blood_cache)))
        return out

    def gore(self):
        c = V2(self.rect.center)
        P = self.g.particles
        P.blood(c, self.GORE, direction=-math.pi / 2, spread=math.pi * 1.3, speed=(150, 640), size=(2, 6), life=(0.7, 1.4))
        P.smoke(c, 6, (120, 10, 18), (20, 40), (0.6, 1.1))
        P.ring(c, (220, 30, 40), 90, 0.35)

    # ---- shared behaviour ------------------------------------------------------------------
    @property
    def depth(self):
        return clamp((self.pos.y - FLOOR_Y[0]) / (FLOOR_Y[1] - FLOOR_Y[0]), 0, 1)

    @property
    def attacking(self):
        return self.g.state == "play" and not self.passive and self.state == "alive"

    def wander(self, dt, speed):
        self.moving = False
        if self.pause > 0:
            self.pause -= dt
            return
        d = self.target - self.pos
        if d.length() < 8:
            self.pause = random.uniform(0.5, 1.6)
            tx = self.pos.x
            for _ in range(8):
                tx = random.uniform(*FLOOR_X)
                if abs(tx - self.pos.x) > 160:
                    break
            self.target = V2(tx, random.uniform(*FLOOR_Y))
            return
        v = d.normalize() * speed
        self.pos += v * dt
        self.moving = True
        if abs(v.x) > 8:
            self.facing = 1 if v.x > 0 else -1

    def common_update(self, dt):
        self.t += dt
        self.flash = max(0.0, self.flash - dt * 5)
        self.stun = max(0.0, self.stun - dt)
        if self.state == "spawn":
            self.spawn_t += dt
            if random.random() < dt * 30:
                self.g.particles.smoke((self.pos.x + random.uniform(-70, 70), self.pos.y + 4), 1, (70, 70, 80), (10, 20), (0.5, 1.0))
            if self.spawn_t >= 0.9:
                self.state = "alive"
        elif self.state == "dying":
            self.die_t += dt
            if self.die_t >= self.DIE_TIME:
                self.state = "dead"
        if self.blood and self.state == "alive" and random.random() < dt * 2.5:        # fresh wounds drip
            u, v, r, born, _ = random.choice(self.blood)
            if self.t - born < 9 and r > 0.02:
                self.g.particles.blood(self.screen_of(u, v), 1, direction=math.pi / 2, spread=0.5,
                                       speed=(10, 50), size=(2, 3), life=(0.6, 0.9))
        self.pos += self.knock * dt
        self.knock *= (1 - min(1, 6 * dt))
        self.pos.x = clamp(self.pos.x, 150, W - 150)
        self.pos.y = clamp(self.pos.y, FLOOR_Y[0] - 5, 700)
        self.alpha = 255
        if self.state == "spawn":
            self.alpha = int(255 * clamp(self.spawn_t / 0.9, 0, 1))

    def die(self):
        self.state = "dying"
        self.die_t = 0.0
        self.flash = 1.0
        if self.GORE and self.img is not None:
            self.gore()

    def place(self, img, zoom):
        """Compute where the sprite sits on screen (also used for hit testing)."""
        self.zoom = zoom
        self.img = scaled(img, zoom)
        w, h = self.img.get_size()
        self.rect = pygame.Rect(0, 0, w, h)
        self.rect.midbottom = (round(self.pos.x), round(self.pos.y - self.bob - self.lift))

    def region(self, name):
        fx, fy, fw, fh = self.REGIONS[name]
        r = self.rect
        if self.facing == 1 and getattr(self, "MIRROR", False):
            fx = 1 - fx - fw
        box = pygame.Rect(r.x + fx * r.w, r.y + fy * r.h, fw * r.w, fh * r.h)
        return self.shrink(box).inflate(self.PAD, self.PAD)

    @staticmethod
    def shrink(box):
        """Shrink a rect around its centre by HITBOX_SCALE."""
        return box.inflate(-box.w * (1 - HITBOX_SCALE), -box.h * (1 - HITBOX_SCALE))

    def hit_test(self, p):
        if self.state != "alive":
            return None
        for name in self.REGIONS:                    # order matters: first = highest priority
            if self.region(name).collidepoint(p):
                return name
        if self.shrink(self.rect).inflate(self.PAD, self.PAD).collidepoint(p):
            return "body"
        return None

    def hit_info(self, kind):
        raise NotImplementedError

    def on_hit(self, kind):
        self.flash = 1.0

    def draw_shadow(self, surf, width):
        w = max(10, int(width * self.zoom))
        sh = pygame.transform.smoothscale(self.g.shadow_img, (w, max(4, int(w * 0.2))))
        sh.set_alpha(int(self.alpha * 0.8))
        surf.blit(sh, sh.get_rect(center=(self.pos.x, self.pos.y + 4)))

    def draw_sprite(self, surf, flip=False):
        self.drawn_flip = flip
        img = self.img
        if flip:
            img = pygame.transform.flip(img, True, False)
        if self.SPRITE_BLOOD and self.blood:
            img = self.bake_blood(img)
        if self.flash > 0.02:
            if img is self.img:
                img = img.copy()
            fc = self.flash_col
            img.fill((int(fc[0] * self.flash), int(fc[1] * self.flash), int(fc[2] * self.flash), 0),
                     special_flags=pygame.BLEND_RGB_ADD)
        r = self.rect
        a = self.alpha
        if self.state == "dying":
            k = self.die_t / self.DIE_TIME
            if self.DIE_ANGLE:
                img = pygame.transform.rotate(img, self.DIE_ANGLE * min(1, k * 1.6) * -self.facing)
                r = img.get_rect(midbottom=self.rect.midbottom)
            a = int(255 * clamp(1.6 - k * 1.6, 0, 1))
        if self.HIT_SHAKE and self.flash > 0.05 and self.state == "alive":              # flinch
            s = self.HIT_SHAKE * self.flash
            r = r.move(round(random.uniform(-s, s)), round(random.uniform(-s, s) * 0.4))
        if a < 255:
            if img is self.img:
                img = img.copy()
            img.set_alpha(a)
        surf.blit(img, r)

    def warn(self, surf, color=(255, 70, 50), dy=-6):
        if int(self.t * 8) % 2 == 0:
            return
        f = self.g.font_fn(54)
        t = f.render("!", True, color)
        o = f.render("!", True, (20, 5, 5))
        c = (self.rect.centerx, self.rect.top + dy)
        for ox, oy in ((-2, 0), (2, 0), (0, 2), (0, -2)):
            surf.blit(o, o.get_rect(center=(c[0] + ox, c[1] + oy)))
        surf.blit(t, t.get_rect(center=c))


# ============================================================================================
class MrX(Enemy):
    NAME = "MR. X"
    BONUS = 900
    DIE_TIME = 1.6
    DIE_ANGLE = 88
    REGIONS = {"head": (0.33, 0.06, 0.36, 0.24)}      # fractions of the 274x456 sprite canvas (hat + face)
    PAD = 8
    HIT_SHAKE = 5
    GORE = 0
    SPRITE_BLOOD = False

    def __init__(self, game, level, x=None):
        super().__init__(game, level, x)
        self.hp = self.max_hp = int((150 + 25 * min(level, 10)) * ENEMY_HP_MULT)
        self.speed = (36 + 2 * min(level, 10)) * ENEMY_SPEED_MULT
        self.charge = 0.0                       # 0..1 progress of his lunge at you
        self.charging = False
        self.next_charge = random.uniform(4.5, 6.5)
        self.charge_time = max(3.2, 4.6 - 0.1 * level)

    def update(self, dt):
        self.common_update(dt)
        if self.state in ("alive", "spawn"):
            if self.charging:
                self.charge = min(1.0, self.charge + dt / self.charge_time * (0.2 if self.stun > 0 else 1))
                self.pos.x += (W / 2 - self.pos.x) * min(1, dt * 0.8)
                # sway left and right while he swells towards you (wider the bigger he gets)
                sway = (70 + 130 * self.charge) * (0.3 if self.stun > 0 else 1)
                self.pos.x += math.cos(self.t * 2.6) * sway * dt
                self.pos.y = lerp(self.pos.y, 652, min(1, dt * 1.5))
                self.moving = False
                if self.charge >= 1.0 and self.attacking:
                    self.charging = False
                    self.charge = 0.0
                    self.next_charge = random.uniform(4.5, 6.5)
                    self.g.damage_player(V2(W / 2, H * 0.55), "PUNCH!")
                    self.knock = V2(0, 0)
            else:
                if self.stun <= 0:
                    self.wander(dt, self.speed if self.state == "alive" else 10)
                else:
                    self.moving = False
                if self.attacking:
                    self.next_charge -= dt
                    if self.next_charge <= 0:
                        self.charging = True
                        self.charge = 0.0
                        self.g.sfx.play("roar", 0.8)
            self.phase += dt * (5.5 if self.moving or self.charging else 1.5)
        frame = 1 if (int(self.phase) % 2) else 0
        hurt = self.flash > 0.3 and self.state != "spawn"
        self.bob = abs(math.sin(self.phase * math.pi)) * 5 if (self.moving or self.charging) else math.sin(self.t * 1.6) * 1.5
        zoom = lerp(0.85, 1.0, self.depth) * (1 + 0.6 * self.charge)
        if self.state == "spawn":
            zoom *= lerp(0.7, 1.0, clamp(self.spawn_t / 0.9, 0, 1))
        self.place(self.g.enemy_art["mrx_hurt" if hurt else f"mrx{frame}"], zoom)

    def hit_info(self, kind):
        if kind == "head":
            return dict(dmg=18, pts=150, label="HEADSHOT", sfx="head", color=(255, 120, 100))
        return dict(dmg=5, pts=20, label=None, sfx="body", color=(255, 240, 160))

    def on_hit(self, kind):
        self.flash = 1.0
        p = self.hit_pos if self.hit_pos is not None else V2(self.rect.center)
        P = self.g.particles
        if kind == "head":
            # Mr. X takes impact damage, but never gets a blood effect.
            self.flash_col = (190, 190, 190)
            P.ring(p, (190, 190, 190), 50, 0.18)
        else:
            self.flash_col = (170, 170, 170)
            P.smoke(p, 3, (110, 110, 105), (10, 20), (0.3, 0.6))     # dust puff off the coat
        if kind == "head":
            self.stun = 0.7
            self.charge = max(0.0, self.charge - 0.35)
        else:
            self.charge = max(0.0, self.charge - 0.12)
        self.knock += V2(random.choice((-1, 1)) * 40, 0)

    def draw(self, surf):
        if self.state == "dead":
            return
        self.draw_shadow(surf, 300)
        self.draw_sprite(surf)
        if self.charging and self.state == "alive":
            self.warn(surf)


# ============================================================================================
class Licker(Enemy):
    NAME = "LICKER"
    BONUS = 250
    DIE_TIME = 0.9
    DIE_ANGLE = 180
    MIRROR = True
    REGIONS = {"head": (0.37, 0.27, 0.27, 0.42)}      # the exposed brain, centre of the 356x186 canvas
    PAD = 6
    HIT_SHAKE = 8
    GORE = 45
    SPRITE_BLOOD = True

    def __init__(self, game, level, x=None):
        super().__init__(game, level, x)
        self.hp = self.max_hp = LICKER_BASE_HP + 5 * min(level, 10)
        self.speed = (120 + 6 * min(level, 10)) * ENEMY_SPEED_MULT
        self.leap_timer = random.uniform(3.5, 6.5)
        self.leaping = False
        self.leap_t = 0.0
        self.leap_dur = max(1.25, 1.7 - 0.04 * level)
        self.leap_from = V2(self.pos)
        self.leap_to = V2(W / 2, 640)
        self.screech = False

    def update(self, dt):
        self.common_update(dt)
        if self.state in ("alive", "spawn"):
            if self.leaping:
                self.leap_t += dt
                p = clamp(self.leap_t / self.leap_dur, 0, 1)
                self.pos = self.leap_from.lerp(self.leap_to, p)
                self.lift = math.sin(p * math.pi) * 150
                self.facing = -1 if self.leap_to.x < self.leap_from.x else 1
                self.moving = True
                if p >= 1.0:
                    self.leaping = False
                    self.lift = 0
                    if self.attacking:
                        self.g.damage_player(self.pos + V2(0, -80), "BITTEN!")
                    self.state = "dead"
            else:
                self.wander(dt, self.speed if self.state == "alive" else 0)
                if self.attacking:
                    self.leap_timer -= dt
                    if self.leap_timer <= 0:
                        self.leaping = True
                        self.leap_t = 0.0
                        self.leap_from = V2(self.pos)
                        self.leap_to = V2(W / 2 + random.uniform(-160, 160), 660)
                        self.g.sfx.play("screech", 0.7)
            self.phase += dt * (11 if self.moving else 2)
        frame = 1 if (int(self.phase) % 2) else 0
        hurt = self.flash > 0.3 and self.state != "spawn"
        self.bob = abs(math.sin(self.phase * 1.5)) * 3 if self.moving and not self.leaping else 0
        p = clamp(self.leap_t / self.leap_dur, 0, 1) if self.leaping else 0
        zoom = lerp(0.8, 1.0, self.depth) * (1 + 1.4 * p)
        if self.state == "spawn":
            zoom *= lerp(0.6, 1.0, clamp(self.spawn_t / 0.9, 0, 1))
        self.place(self.g.enemy_art["licker_hurt" if hurt else f"licker{frame}"], zoom)

    def die(self):
        super().die()
        self.leaping = False
        self.lift = 0

    def hit_info(self, kind):
        if kind == "head":
            return dict(dmg=30, pts=150, label="BRAIN SHOT", sfx="head", color=(255, 150, 160))
        return dict(dmg=15, pts=50, label=None, sfx="body", color=(255, 240, 160))

    def on_hit(self, kind):
        self.flash = 1.0
        p = self.hit_pos if self.hit_pos is not None else V2(self.rect.center)
        u, v = self.uv_of(p)
        P = self.g.particles
        if kind == "head":                                         # brain shot: it gets properly bloody
            self.flash_col = (215, 40, 40)
            P.blood(p, 34, direction=-math.pi / 2, spread=math.pi * 1.1, speed=(160, 560), size=(2, 6), life=(0.5, 1.2))
            P.smoke(p, 5, (130, 8, 16), (12, 26), (0.5, 0.9))
            P.ring(p, (210, 25, 35), 56, 0.22)
            self.add_blood(u, v, random.uniform(0.04, 0.06), satellites=5)
            self.add_blood(0.505 + random.uniform(-0.1, 0.1), 0.48 + random.uniform(-0.12, 0.12),
                           random.uniform(0.05, 0.08), satellites=2)         # keeps coating the brain
        else:
            self.flash_col = (170, 170, 170)
            P.blood(p, 12, direction=-math.pi / 2, spread=math.pi, speed=(100, 340), size=(2, 4), life=(0.4, 0.9))
            self.add_blood(u, v, random.uniform(0.02, 0.035), satellites=2)
        self.knock += V2(random.choice((-1, 1)) * 120, 0)
        if self.leaping:                                       # a wounded licker hesitates in the air
            self.leap_t = max(0.0, self.leap_t - 0.25)

    def draw(self, surf):
        if self.state == "dead":
            return
        self.draw_shadow(surf, 300 * (1 + 0.5 * (self.lift / 150)))
        flip = self.facing == 1                               # the artwork is symmetrical, the flip only matters for the leap lean
        # (the tongue is part of the artwork now, so the old procedural tongue is gone)
        self.draw_sprite(surf, flip)
        if self.leaping and self.state == "alive":
            self.warn(surf)


# ============================================================================================
class Birkin(Enemy):
    NAME = "BIRKIN"
    BONUS = 1200
    DIE_TIME = 2.0
    DIE_ANGLE = 0
    REGIONS = {"weak": (0.21, 0.14, 0.20, 0.17)}      # around the big eye on his shoulder (400x436 canvas)
    PAD = 8

    def __init__(self, game, level, x=None):
        super().__init__(game, level, x)
        self.hp = self.max_hp = int((170 + 30 * min(level, 10)) * ENEMY_HP_MULT)
        self.speed = 30 * ENEMY_SPEED_MULT
        self.eye_shut = 0.0
        self.spit_t = random.uniform(3.5, 5.0)

    def region(self, name):
        return super().region(name)

    def hit_test(self, p):
        res = super().hit_test(p)
        if res == "weak" and self.eye_shut > 0:
            return "body"
        return res

    def update(self, dt):
        self.common_update(dt)
        self.eye_shut = max(0.0, self.eye_shut - dt)
        if self.state in ("alive", "spawn"):
            self.wander(dt, self.speed if self.state == "alive" else 0)
            self.phase += dt * (3.0 if self.moving else 1.2)
            if self.attacking and self.eye_shut <= 0:
                self.spit_t -= dt
                if self.spit_t <= 0:
                    self.spit_t = max(3.0, 5.2 - 0.2 * self.level) * random.uniform(0.85, 1.15)
                    self.spit()
        frame = 1 if (int(self.phase * 1.3) % 2) else 0
        self.bob = abs(math.sin(self.phase * math.pi * 0.7)) * 4 if self.moving else math.sin(self.t * 1.4) * 2
        zoom = lerp(0.78, 0.95, self.depth)
        if self.state == "spawn":
            zoom *= lerp(0.7, 1.0, clamp(self.spawn_t / 0.9, 0, 1))
        if self.state == "dying":
            zoom *= 1 - 0.25 * (self.die_t / self.DIE_TIME)
        if self.eye_shut > 1.55 and self.state == "alive":               # just took an eye shot: flinch
            key = "birkin_hurt"
        elif self.eye_shut > 0 or self.state == "dying":
            key = f"birkin_shut{frame}"
        else:
            key = f"birkin{frame}"
        self.place(self.g.enemy_art[key], zoom)

    def eye_pos(self):
        r = self.rect
        return V2(r.x + r.w * 0.31, r.y + r.h * 0.225)

    def spit(self):
        self.g.spawn_spore_at(self.eye_pos(), "flesh", max(2.6, 3.9 - 0.08 * self.level))
        self.g.sfx.play("roar", 0.5)

    def hit_info(self, kind):
        if kind == "weak":
            return dict(dmg=44, pts=250, label="EYE SHOT", sfx="orb", color=(255, 200, 90))
        return dict(dmg=4, pts=15, label=None, sfx="body", color=(255, 240, 160))

    def on_hit(self, kind):
        self.flash = 1.0
        if kind == "weak":
            self.eye_shut = 1.8
            self.stun = 0.6
            self.knock += V2(random.choice((-1, 1)) * 80, 0)

    def draw(self, surf):
        if self.state == "dead":
            return
        self.draw_shadow(surf, 380)
        self.draw_sprite(surf)
        if self.state == "alive" and self.eye_shut <= 0:                   # pulsing glow on the open eye
            pulse = 1 + 0.15 * math.sin(self.t * 5)
            size = int(150 * self.zoom * pulse)
            glow = pygame.transform.smoothscale(self.g.orb_glow, (size, size))
            surf.blit(glow, glow.get_rect(center=self.eye_pos()), special_flags=pygame.BLEND_RGB_ADD)
            if self.spit_t < 1.0 and self.attacking:
                self.warn(surf, (255, 190, 60), -10)


KINDS = {"mrx": MrX, "licker": Licker, "birkin": Birkin}
