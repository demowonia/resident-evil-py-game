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
    PAD = 16

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
        return pygame.Rect(r.x + fx * r.w, r.y + fy * r.h, fw * r.w, fh * r.h).inflate(self.PAD, self.PAD)

    def hit_test(self, p):
        if self.state != "alive":
            return None
        for name in self.REGIONS:                    # order matters: first = highest priority
            if self.region(name).collidepoint(p):
                return name
        if self.rect.inflate(self.PAD, self.PAD).collidepoint(p):
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
        img = self.img
        if flip:
            img = pygame.transform.flip(img, True, False)
        if self.flash > 0.02:
            img = img.copy()
            v = int(170 * self.flash)
            img.fill((v, v, v, 0), special_flags=pygame.BLEND_RGB_ADD)
        r = self.rect
        a = self.alpha
        if self.state == "dying":
            k = self.die_t / self.DIE_TIME
            if self.DIE_ANGLE:
                img = pygame.transform.rotate(img, self.DIE_ANGLE * min(1, k * 1.6) * -self.facing)
                r = img.get_rect(midbottom=self.rect.midbottom)
            a = int(255 * clamp(1.6 - k * 1.6, 0, 1))
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
    PAD = 20

    def __init__(self, game, level, x=None):
        super().__init__(game, level, x)
        self.hp = self.max_hp = 150 + 25 * min(level, 10)
        self.speed = 36 + 2 * min(level, 10)
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
    PAD = 20

    def __init__(self, game, level, x=None):
        super().__init__(game, level, x)
        self.hp = self.max_hp = 30
        self.speed = 120 + 6 * min(level, 10)
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
    PAD = 22

    def __init__(self, game, level, x=None):
        super().__init__(game, level, x)
        self.hp = self.max_hp = 170 + 30 * min(level, 10)
        self.speed = 30
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
