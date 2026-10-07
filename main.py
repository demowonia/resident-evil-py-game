"""
RESIDENT EVIL - Greenhouse  (pygame, controlled with hand gestures)

    python main.py            hand-gesture mode (webcam)
    python main.py --mouse    mouse mode (click = shoot)

Hand gestures (finger gun):
    point index finger ........ aim
    raise thumb, then drop it . FIRE
    open palm (hold 0.5 s) .... RELOAD
Keyboard: SPACE = fire at the crosshair, R = reload, M = switch hand/mouse, P = pause, F11 = fullscreen, ESC = quit
"""
import argparse
import math
import os
import random
import sys

import pygame
from pygame.math import Vector2 as V2

import effects as fx
import enemies
import sprites
from hand_input import HandTracker

W, H = 1400, 700
FPS = 60
BASE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(BASE, "assets")
S0 = 0.58                      # pre-scale of the mob sprites
FLOOR_Y = (588, 652)           # where the mob's feet may walk (far, near)
FLOOR_X = (250, 1150)
MAX_HEARTS = 5
MAG = 8

# ============================================================================================
# small drawing helpers
# ============================================================================================
_fonts = {}


def font(size, bold=False):
    key = (int(size), bold)
    if key not in _fonts:
        name = pygame.font.match_font("bahnschrift,impact,arialblack,arial,verdana,dejavusans", bold=bold)
        _fonts[key] = pygame.font.Font(name, int(size))
    return _fonts[key]


def text(surf, s, size, pos, color=(255, 255, 255), anchor="topleft", shadow=True, bold=False, alpha=255,
         outline=None):
    f = font(size, bold)
    img = f.render(s, True, color)
    r = img.get_rect(**{anchor: pos})
    if outline:
        o = f.render(s, True, outline)
        o.set_alpha(alpha)
        for ox, oy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-2, -2), (2, 2), (-2, 2), (2, -2)):
            surf.blit(o, r.move(ox, oy))
    elif shadow:
        sh = f.render(s, True, (4, 10, 6))
        sh.set_alpha(alpha)
        surf.blit(sh, r.move(2, 3))
    img.set_alpha(alpha)
    surf.blit(img, r)
    return r


def draw_heart(surf, cx, cy, size, fill, outline=(30, 10, 14)):
    r = size * 0.27
    for col, grow in ((outline, 2), (fill, 0)):
        pygame.draw.circle(surf, col, (cx - r, cy - size * 0.18), r + grow)
        pygame.draw.circle(surf, col, (cx + r, cy - size * 0.18), r + grow)
        pygame.draw.polygon(surf, col, [(cx - size * 0.5 - grow, cy - size * 0.05),
                                        (cx, cy + size * 0.5 + grow * 1.5),
                                        (cx + size * 0.5 + grow, cy - size * 0.05)])
    if fill != (60, 55, 55):
        pygame.draw.circle(surf, (255, 190, 190), (cx - r - 2, cy - size * 0.28), max(2, size * 0.08))


def draw_arc(surf, color, center, radius, a0, a1, width=3):
    n = max(4, int(abs(a1 - a0) * radius / 4))
    pts = [(center[0] + radius * math.cos(a0 + (a1 - a0) * i / n),
            center[1] + radius * math.sin(a0 + (a1 - a0) * i / n)) for i in range(n + 1)]
    pygame.draw.lines(surf, color, False, pts, width)


def lerp(a, b, t):
    return a + (b - a) * t


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def ease_out(t):
    return 1 - (1 - t) ** 3


# ============================================================================================
# the mutant
# ============================================================================================
WAVE_PLAN = [("thorn",), ("licker", "licker"), ("mrx",), ("thorn", "licker", "licker"), ("birkin",),
             ("mrx", "licker", "licker"), ("birkin", "licker", "licker"), ("thorn", "mrx"), ("birkin", "mrx")]
WAVE_TIPS = [("birkin", "BIRKIN - only the glowing eye hurts him, it shuts after each hit"),
             ("mrx", "MR. X - aim for the head, shots push him back"),
             ("licker", "LICKERS - shoot the brain, they leap at you"),
             ("thorn", "shoot the glowing orbs")]


class Mob:
    def __init__(self, game, wave, passive=False):
        self.g = game
        self.wave = wave
        self.passive = passive              # title-screen mob: walks around, can't be hurt, doesn't shoot
        self.max_hp = 90 + 18 * (wave - 1)
        self.hp = self.max_hp
        self.disabled = set()
        self.pos = V2(random.uniform(500, 900), 600)
        self.target = V2(self.pos)
        self.pause = 0.6
        self.t = 0.0
        self.phase = 0.0
        self.moving = False
        self.state = "spawn"                # spawn | alive | dying | dead
        self.spawn_t = 0.0
        self.die_t = 0.0
        self.react = []                     # [(pose_name, duration), ...]
        self.react_t = 0.0
        self.flash = 0.0
        self.knock = V2(0, 0)
        self.lean = 0.0
        self.dash = 1.0
        self.spore_t = random.uniform(4.0, 5.5)
        self.smoke_t = 0.0
        self.angle = 0.0
        self.zoom = 1.0
        self.alpha = 255
        self.P = V2(self.pos)
        self.speed_base = 52 + 6 * (wave - 1)
        self.ref = game.idle[frozenset()]
        self.pick_target()

    # ---- geometry --------------------------------------------------------------------------
    @property
    def depth(self):
        return clamp((self.pos.y - FLOOR_Y[0]) / (FLOOR_Y[1] - FLOOR_Y[0]), 0, 1)

    @staticmethod
    def _anchor_center(frame):
        return V2(frame.anchor) - V2(frame.center)

    def to_screen(self, q):
        """Sprite-space point (850x728 idle sprite) -> screen position."""
        f = self.ref
        c = self.P - self._anchor_center(f).rotate(-self.angle) * self.zoom
        return c + (V2(q) * S0 - V2(f.center)).rotate(-self.angle) * self.zoom

    def to_sprite(self, p):
        f = self.ref
        c = self.P - self._anchor_center(f).rotate(-self.angle) * self.zoom
        rel = (V2(p) - c).rotate(self.angle) / self.zoom
        return (rel + V2(f.center)) / S0

    def hit_test(self, p):
        if self.state != "alive":
            return None
        best = None
        for limb, (ox, oy, r) in sprites.ORBS.items():
            if limb in self.disabled:
                continue
            d = (V2(p) - self.to_screen((ox, oy))).length()
            if d < max(44, r * S0 * self.zoom * 2.1) and (best is None or d < best[0]):
                best = (d, limb)
        if best:
            return "orb", best[1]
        q = self.to_sprite(p)
        cx, cy, rx, ry = sprites.HEAD_ELLIPSE
        if ((q.x - cx) / rx) ** 2 + ((q.y - cy) / ry) ** 2 <= 1:
            return "head", None
        x, y, w, h = sprites.BODY_RECT
        if x <= q.x <= x + w and y <= q.y <= y + h:
            return "body", None
        return None

    # ---- behaviour -------------------------------------------------------------------------
    def pick_target(self):
        tx = self.pos.x
        for _ in range(10):
            tx = random.uniform(*FLOOR_X)
            if abs(tx - self.pos.x) > 170:
                break
        self.target = V2(tx, random.uniform(*FLOOR_Y))
        self.dash = 1.6 if (self.wave >= 4 and not self.passive and random.random() < 0.15) else 1.0

    @property
    def speed(self):
        legs = sum(1 for l in self.disabled if "leg" in l)
        return self.speed_base * (0.62 ** legs) * self.dash

    def trigger(self, kind):
        if self.state in ("dying", "dead"):
            return
        if kind == "orb":
            self.react = [("hit", 0.13), ("stagger", 0.22), ("recover", 0.24)]
        elif kind == "head":
            self.react = [("stagger", 0.30)]
        elif kind == "body" and not self.react:
            self.react = [("hit", 0.09)]
        self.react_t = self.react[0][1] if self.react else 0
        self.flash = 1.0

    def die(self):
        self.state = "dying"
        self.die_t = 0.0
        self.react = [("hit", 0.10), ("stagger", 0.16), ("collapse", 99)]
        self.react_t = 0.10
        self.flash = 1.0

    def spit_interval(self):
        arms = sum(1 for l in self.disabled if "arm" in l)
        base = max(2.8, 5.4 - 0.25 * (self.wave - 1))
        return base * (1 + 0.55 * arms) * random.uniform(0.85, 1.2)

    def update(self, dt):
        self.t += dt
        self.flash = max(0.0, self.flash - dt * 5)
        if self.react:
            self.react_t -= dt
            if self.react_t <= 0 and self.react[0][0] != "collapse":
                self.react.pop(0)
                self.react_t = self.react[0][1] if self.react else 0
        reacting = bool(self.react)

        if self.state == "spawn":
            self.spawn_t += dt
            if self.spawn_t >= 1.0:
                self.state = "alive"
        if self.state == "dying":
            self.die_t += dt
            self.knock *= (1 - min(1, 3 * dt))
            self.pos += self.knock * dt
            self.moving = False
            if self.die_t >= 2.7:
                self.state = "dead"
        elif self.state in ("alive", "spawn"):
            moving = False
            if self.pause > 0:
                self.pause -= dt
            else:
                d = self.target - self.pos
                if d.length() < 8:
                    self.pause = random.uniform(0.6, 1.6)
                    self.pick_target()
                else:
                    v = d.normalize() * self.speed * (0.25 if reacting else 1.0) * (0.3 if self.state == "spawn" else 1)
                    self.pos += v * dt
                    self.lean = lerp(self.lean, clamp(v.x / 120, -1, 1), min(1, dt * 6))
                    moving = True
            if not moving:
                self.lean = lerp(self.lean, 0, min(1, dt * 5))
            self.pos += self.knock * dt
            self.knock *= (1 - min(1, 6 * dt))
            self.pos.x = clamp(self.pos.x, *FLOOR_X)
            self.pos.y = clamp(self.pos.y, *FLOOR_Y)
            self.phase += dt * ((7.5 + self.speed / 28) if moving else 2.2)
            self.moving = moving

            if self.state == "alive" and not self.passive and not reacting and self.g.state == "play":      # spit spores at the player
                self.spore_t -= dt
                if self.spore_t <= 0:
                    self.spore_t = self.spit_interval()
                    self.g.spawn_spore(self)
            self.smoke_t -= dt                                                    # damaged orbs smoulder
            if self.disabled and self.smoke_t <= 0 and self.state == "alive":
                self.smoke_t = random.uniform(0.25, 0.5)
                limb = random.choice(list(self.disabled))
                self.g.particles.smoke(self.to_screen(sprites.ORBS[limb][:2]), 1, (90, 95, 90), (6, 12), (0.5, 0.9))

        # procedural walk cycle: bob, sway and lean (the art has no walk frames)
        legs = [l for l in self.disabled if "leg" in l]
        if self.moving:
            bob = abs(math.sin(self.phase)) * 9 if not legs else math.sin(self.phase) * 6 + 3
            sway = math.sin(self.phase) * (2.4 if not legs else 4.0)
        else:
            bob = math.sin(self.t * 2.0) * 2.0
            sway = math.sin(self.t * 1.3) * 0.7
        self.angle = self.lean * 3.5 + sway
        z = lerp(0.50, 0.66, self.depth) / S0
        a = 255
        if self.state == "spawn":
            k = ease_out(clamp(self.spawn_t / 1.0, 0, 1))
            z *= lerp(0.55, 1.0, k)
            a = int(255 * k)
            if random.random() < dt * 30:
                self.g.particles.smoke((self.pos.x + random.uniform(-90, 90), self.pos.y + 6), 1,
                                       (60, 120, 70), (10, 22), (0.5, 1.0))
        if self.state == "dying" and self.die_t > 1.5:
            a = int(255 * clamp(1 - (self.die_t - 1.5) / 1.1, 0, 1))
        self.zoom = z
        self.alpha = a
        self.P = V2(self.pos.x, self.pos.y - bob * z)

    # ---- drawing ---------------------------------------------------------------------------
    def current_frame(self):
        if self.react:
            return self.g.poses[self.react[0][0]]
        return self.g.idle[frozenset(self.disabled)]

    def draw(self, surf):
        if self.state == "dead":
            return
        w = int(380 * self.zoom * 0.85)
        sh = pygame.transform.smoothscale(self.g.shadow_img, (w, int(w * 0.2)))
        sh.set_alpha(int(self.alpha * 0.8))
        surf.blit(sh, sh.get_rect(center=(self.pos.x, self.pos.y + 4)))

        frame = self.current_frame()
        img = pygame.transform.rotozoom(frame.surf, self.angle, self.zoom)
        if self.flash > 0.02:
            v = int(150 * self.flash)
            img.fill((v, v, v, 0), special_flags=pygame.BLEND_RGB_ADD)
        if self.alpha < 255:
            img.set_alpha(self.alpha)
        c = self.P - self._anchor_center(frame).rotate(-self.angle) * self.zoom
        surf.blit(img, img.get_rect(center=(round(c.x), round(c.y))))

        if not self.react and self.state in ("alive", "spawn"):                  # pulsing orb glow
            for i, (limb, (ox, oy, r)) in enumerate(sprites.ORBS.items()):
                if limb in self.disabled:
                    continue
                pulse = 1 + 0.16 * math.sin(self.t * 5.5 + i * 1.7)
                size = max(8, int(r * 2 * S0 * self.zoom * 3.0 * pulse))
                glow = pygame.transform.smoothscale(self.g.orb_glow, (size, size))
                if self.alpha < 255:
                    glow.fill((self.alpha,) * 3, special_flags=pygame.BLEND_RGB_MULT)
                surf.blit(glow, glow.get_rect(center=self.to_screen((ox, oy))), special_flags=pygame.BLEND_RGB_ADD)


class Spore:
    """A glowing seed spat by the mutant. It flies toward you while growing: shoot it before it lands."""

    def __init__(self, start, target, dur, kind="seed"):
        self.kind = kind
        self.start, self.target = V2(start), V2(target)
        self.dur, self.t = dur, 0.0
        self.seed = random.uniform(0, 6)
        self.pos = V2(start)
        self.radius = 10
        self.dead = False

    @property
    def p(self):
        return clamp(self.t / self.dur, 0, 1)

    def update(self, dt):
        self.t += dt
        p = self.p
        d = self.target - self.start
        perp = V2(-d.y, d.x).normalize() if d.length() else V2(0, 1)
        self.pos = self.start.lerp(self.target, p ** 1.15) + perp * math.sin(self.t * 8 + self.seed) * 22 * (1 - p)
        self.radius = lerp(11, 74, p ** 1.7)

    def draw(self, surf, g):
        r = int(self.radius)
        flesh = self.kind == "flesh"
        glow = pygame.transform.smoothscale(g.flesh_glow if flesh else g.spore_glow, (r * 5, r * 5))
        surf.blit(glow, glow.get_rect(center=self.pos), special_flags=pygame.BLEND_RGB_ADD)
        pygame.draw.circle(surf, (40, 10, 16) if flesh else (15, 40, 22), self.pos, r + 3)
        pygame.draw.circle(surf, (170, 56, 64) if flesh else (70, 160, 60), self.pos, r)
        pygame.draw.circle(surf, (236, 130, 120) if flesh else (170, 220, 80), self.pos + V2(-r * 0.15, -r * 0.15), int(r * 0.75))
        for i in range(8):
            a = self.t * 3 + i * math.tau / 8
            u = V2(math.cos(a), math.sin(a))
            pygame.draw.line(surf, (70, 16, 26) if flesh else (20, 55, 28), self.pos + u * r, self.pos + u * (r + 6 + r * 0.22), 3)
        pulse = 0.65 + 0.35 * math.sin(self.t * 9)
        pygame.draw.circle(surf, (255, int(190 + 50 * pulse), 80), self.pos, max(3, int(r * 0.42 * pulse)))
        if self.p > 0.55:                                                    # incoming warning ring
            draw_arc(surf, (255, 90, 60), self.pos, r + 12, -math.pi / 2, -math.pi / 2 + math.tau * self.p, 3)


# ============================================================================================
# the game
# ============================================================================================
class Game:
    def __init__(self, screen, sfx):
        self.screen = screen
        self.sfx = sfx
        self.world = pygame.Surface((W, H)).convert()
        self.t = 0.0
        self.load_assets()

        self.leaves = fx.LeafSystem((W, H), back=34, front=7)
        self.fireflies = fx.Fireflies((W, H), 30)
        self.rain = fx.Rain((W, H), 300, 80)
        self.fog = fx.Fog((W, H))
        self.lightning = fx.Lightning((W, H))
        self.particles = fx.Particles(self.leaves.bank)
        self.texts = fx.FloatingText()
        self.decals = []
        self.spores = []

        self.cross = V2(W / 2, H / 2)
        self.kick = self.shake = self.muzzle = self.hurt = 0.0
        self.paused = False
        self.banner = None                  # (text, sub, time_left)
        self.pip = None
        self.pip_id = -1
        self.inp = None
        self.best = 0
        self.state = "title"
        self.reset_stats()
        self.font_fn = font
        self.enemies = [Mob(self, 1, passive=True)]

    def load_assets(self):
        bg = pygame.image.load(os.path.join(ASSETS, "greenhouse_background.jpg")).convert()
        k = max(W / bg.get_width(), H / bg.get_height())
        bg = pygame.transform.smoothscale(bg, (round(bg.get_width() * k), round(bg.get_height() * k)))
        self.bg = bg.subsurface(pygame.Rect(0, 40, W, H)).copy()          # keep the floor, trim the dome
        self.idle, self.poses = sprites.load_mob_frames(ASSETS, S0)
        self.vig = fx.vignette((W, H))
        self.vig_red = fx.vignette((W, H), (200, 0, 10), 0.35, 1.3, 230)
        self.plant_glow = fx.radial_alpha(520, (150, 255, 110), 2.4, 120)
        self.orb_glow = fx.radial_add(96, (255, 170, 60), 2.0, 1.0)
        self.spore_glow = fx.radial_add(128, (110, 255, 90), 2.2, 0.9)
        self.shadow_img = fx.ellipse_alpha(380, 76, (0, 0, 0), 1.2, 170)
        self.flesh_glow = fx.radial_add(128, (255, 70, 60), 2.2, 0.9)
        self.enemy_art = enemies.build_art()

    @property
    def mob(self):
        for e in self.enemies:
            if isinstance(e, Mob):
                return e
        return None

    def reset_stats(self):
        self.score = 0
        self.hearts = MAX_HEARTS
        self.ammo = MAG
        self.reload_t = 0.0
        self.auto_reload_t = None
        self.combo = 0
        self.shots = 0
        self.hits = 0
        self.wave = 1
        self.next_wave_t = None
        self.over_t = 0.0

    def start_game(self):
        self.reset_stats()
        self.state = "play"
        self.spores.clear()
        self.spawn_wave(1)

    def spawn_wave(self, wave):
        plan = WAVE_PLAN[(wave - 1) % len(WAVE_PLAN)]
        self.enemies = []
        n = len(plan)
        for i, k in enumerate(plan):
            x = 330 + (i + 0.5) * (740 / n) + random.uniform(-50, 50)
            if k == "thorn":
                e = Mob(self, min(wave, 8))
                e.pos.x = x
            else:
                e = enemies.KINDS[k](self, min(wave, 10), x)
            self.enemies.append(e)
            e.update(0.0)                       # place the sprite before the first draw
        tip = next((t for k, t in WAVE_TIPS if k in plan), "shoot them down")
        self.banner = (f"WAVE {wave}", tip, 2.4)
        self.sfx.play("charge", 0.7)

    def game_over(self):
        self.state = "over"
        self.over_t = 0.0
        self.best = max(self.best, self.score)
        self.spores.clear()

    # ---- gameplay actions --------------------------------------------------------------------
    def spawn_spore(self, mob):
        self.spawn_spore_at(mob.to_screen(sprites.HEAD_POINT), "seed", max(2.3, 3.8 - 0.08 * (mob.wave - 1)))

    def spawn_spore_at(self, start, kind, dur):
        target = V2(W / 2 + random.uniform(-170, 170), H * 0.80)
        self.spores.append(Spore(start, target, dur, kind))
        self.sfx.play("charge", 0.45)
        cols = ((255, 120, 100), (255, 200, 120)) if kind == "flesh" else ((150, 255, 110), (255, 230, 120))
        self.particles.sparks(start, 8, cols, (60, 200), (0.2, 0.4), 0)

    def damage_player(self, pos, label="INFECTED!"):
        if self.state != "play":
            return
        self.hearts -= 1
        self.combo = 0
        self.hurt = 1.0
        self.shake = max(self.shake, 16)
        self.sfx.play("hurt")
        self.particles.sparks(pos, 30, ((255, 120, 80), (255, 200, 100)), (150, 520), (0.3, 0.8), 300)
        self.texts.add(label, V2(W / 2, H * 0.62), (255, 90, 80), 44, 1.1)
        if self.hearts <= 0:
            self.game_over()

    def mult(self):
        return min(5, 1 + self.combo // 3)

    def add_score(self, base, pos, label=None, color=(255, 240, 160)):
        pts = base * self.mult()
        self.score += pts
        self.texts.add(f"+{pts}" + (f"  {label}" if label else ""), V2(pos) + V2(0, -26), color, 34 if label else 30)

    def pop_spore(self, s):
        s.dead = True
        self.combo += 1
        self.hits += 1
        self.add_score(25, s.pos, "SPORE", (190, 255, 130))
        self.particles.sparks(s.pos, 22, ((150, 255, 110), (230, 255, 150), (255, 220, 100)), (120, 380), (0.3, 0.7), 420)
        self.particles.leaves(s.pos, 5)
        self.particles.ring(s.pos, (150, 255, 120), int(s.radius * 1.5), 0.3)
        self.sfx.play("pop")

    def shoot(self, pos):
        pos = V2(pos)
        if self.state == "title":
            if (pos - V2(W / 2, 470)).length() < 92:
                self.start_game()
            else:
                self.miss(pos, silent=True)
            return
        if self.state == "over":
            if self.over_t > 1.2 and (pos - V2(W / 2, 520)).length() < 92:
                self.start_game()
            return
        if self.paused or self.reload_t > 0:
            return
        if self.ammo <= 0:
            self.start_reload()
            self.sfx.play("empty")
            self.texts.add("RELOAD!", pos + V2(0, -40), (255, 120, 90), 32, 0.7)
            return
        self.ammo -= 1
        self.shots += 1
        self.kick = self.muzzle = 1.0
        self.shake = max(self.shake, 3)
        self.sfx.play("shot")
        if self.ammo == 0:
            self.texts.add("AUTO-RELOAD", pos + V2(0, -40), (255, 220, 120), 26, 0.8)
            self.auto_reload_t = 0.5

        for s in sorted(self.spores, key=lambda s: -s.radius):                   # 1) spores threaten you first
            if not s.dead and (pos - s.pos).length() <= s.radius * 1.3 + 28:
                self.pop_spore(s)
                return
        for e in sorted(self.enemies, key=lambda e: -e.pos.y):                    # 2) enemies, nearest first
            hit = e.hit_test(pos)
            if not hit:
                continue
            self.combo += 1
            self.hits += 1
            if isinstance(e, Mob):
                self.hit_mob(e, hit, pos)
            else:
                self.hit_enemy(e, hit, pos)
            return
        self.miss(pos)

    def hit_enemy(self, e, kind, pos):
        info = e.hit_info(kind)
        e.hp -= info["dmg"]
        self.add_score(info["pts"], pos, info["label"], info["color"])
        self.particles.sparks(pos, 16 if kind != "body" else 9, ((255, 150, 90), (255, 230, 150), (220, 60, 70)),
                              (120, 380), (0.25, 0.55), 500)
        self.particles.ring(pos, (255, 255, 255), 34, 0.18)
        self.sfx.play(info["sfx"])
        self.shake = max(self.shake, 2 if kind == "body" else 6)
        e.on_hit(kind)
        if e.hp <= 0 and e.state == "alive":
            self.kill_enemy(e)

    def hit_mob(self, mob, hit, pos):
        kind, limb = hit
        if kind == "orb":
            mob.disabled.add(limb)
            mob.hp -= 18
            self.add_score(100, pos, sprites.LIMB_LABEL[limb] + " DOWN!", (255, 190, 80))
            c = mob.to_screen(sprites.ORBS[limb][:2])
            self.particles.sparks(c, 34, ((255, 230, 130), (255, 160, 40), (255, 255, 220)), (160, 480), (0.3, 0.8), 500)
            self.particles.leaves(c, 9)
            self.particles.ring(c, (255, 200, 90), 90, 0.35)
            self.sfx.play("orb")
            self.shake = max(self.shake, 7)
            mob.knock += V2(random.choice((-1, 1)) * 150, 0)
            mob.trigger("orb")
        elif kind == "head":
            mob.hp -= 16
            self.add_score(50, pos, "HEADSHOT", (255, 120, 100))
            self.particles.sparks(pos, 18, ((255, 150, 90), (255, 230, 150)), (140, 420), (0.25, 0.6), 500)
            self.particles.leaves(pos, 6)
            self.sfx.play("head")
            self.shake = max(self.shake, 5)
            mob.knock += V2(random.choice((-1, 1)) * 90, 0)
            mob.trigger("head")
        else:
            mob.hp -= 6
            self.add_score(10, pos)
            self.particles.sparks(pos, 10, ((200, 255, 140), (255, 220, 120)), (100, 300), (0.2, 0.5), 500)
            self.particles.leaves(pos, 2)
            self.sfx.play("body")
            mob.trigger("body")
        self.particles.ring(pos, (255, 255, 255), 34, 0.18)
        if mob.state == "alive" and (mob.hp <= 0 or len(mob.disabled) == 4):
            self.kill_enemy(mob)

    def miss(self, pos, silent=False):
        if not silent:
            self.combo = 0
        self.decals.append([V2(pos), 5.0])
        self.particles.sparks(pos, 8, ((255, 240, 190), (190, 190, 170)), (60, 240), (0.15, 0.35), 700)
        self.particles.smoke(pos, 2, (140, 150, 130), (6, 12), (0.3, 0.6))
        if len(self.decals) > 40:
            self.decals.pop(0)

    def kill_enemy(self, e):
        e.die()
        if isinstance(e, Mob):
            bonus, name, c = 500 * e.wave, "MUTANT THORN", e.to_screen((425, 560))
        else:
            bonus, name, c = e.BONUS, e.NAME, V2(e.rect.center)
        self.score += bonus
        big = bonus >= 500
        self.texts.add(f"{name} DOWN  +{bonus}", V2(e.pos.x, max(150, e.pos.y - 330)), (255, 235, 120), 40 if big else 30, 1.6, -30)
        self.sfx.play("collapse" if big else "pop")
        self.shake = max(self.shake, 12 if big else 5)
        self.particles.smoke(c, 22 if big else 8, (150, 120, 80), (22, 46), (0.9, 1.7))
        if isinstance(e, Mob):
            self.particles.leaves(c, 26, (120, 520), (1.0, 1.9))
        self.particles.sparks(c, 40 if big else 18, ((255, 220, 120), (255, 160, 40), (220, 60, 70)), (200, 560), (0.4, 1.0), 600)
        e.knock = V2(random.choice((-1, 1)) * 140, 0)

    def start_reload(self):
        if self.state != "play" or self.reload_t > 0 or self.ammo >= MAG or self.paused:
            return
        self.reload_t = 1.0
        self.sfx.play("reload")

    # ---- per-frame update ------------------------------------------------------------------
    def update(self, dt, inp):
        self.inp = inp
        if self.paused:
            return
        self.t += dt
        tgt = V2(inp["aim"])
        self.cross += (tgt - self.cross) * min(1.0, dt * (26 if inp["mode"] == "hand" else 60))
        self.kick = max(0.0, self.kick - dt * 7)
        self.muzzle = max(0.0, self.muzzle - dt * 9)
        self.shake = max(0.0, self.shake - dt * 22)
        self.hurt = max(0.0, self.hurt - dt * 1.6)

        for pos in inp["fires"]:
            self.shoot(pos)
        if inp["reload"]:
            self.start_reload()

        self.leaves.update(dt)
        self.fireflies.update(dt)
        self.rain.update(dt)
        self.fog.update(dt)
        self.lightning.update(dt, lambda: self.sfx.play("thunder", 0.8))
        self.particles.update(dt)
        self.texts.update(dt)
        for d in self.decals:
            d[1] -= dt
        self.decals = [d for d in self.decals if d[1] > 0]
        if self.banner:
            self.banner = (self.banner[0], self.banner[1], self.banner[2] - dt)
            if self.banner[2] <= 0:
                self.banner = None
        if self.state == "over":
            self.over_t += dt
        for e in self.enemies:
            e.update(dt)

        if self.state == "play":
            if self.auto_reload_t is not None:
                self.auto_reload_t -= dt
                if self.auto_reload_t <= 0:
                    self.auto_reload_t = None
                    self.start_reload()
            if self.reload_t > 0:
                self.reload_t -= dt
                if self.reload_t <= 0:
                    self.ammo = MAG
                    self.texts.add("READY", self.cross + V2(0, -50), (150, 255, 160), 30, 0.6)
            for s in self.spores:
                s.update(dt)
                if not s.dead and s.p >= 1.0:
                    s.dead = True
                    self.damage_player(s.pos)
                    if self.state != "play":
                        break
            self.spores = [s for s in self.spores if not s.dead]

            if self.state == "play" and self.enemies and all(e.state == "dead" for e in self.enemies):
                if self.next_wave_t is None:
                    self.next_wave_t = 2.2
                    self.texts.add("WAVE CLEARED", V2(W / 2, 250), (255, 235, 120), 56, 2.0, -30)
                    self.sfx.play("win", 0.8)
                    for sp in self.spores:
                        if not sp.dead:
                            self.pop_spore(sp)
                self.next_wave_t -= dt
                if self.next_wave_t <= 0:
                    self.next_wave_t = None
                    self.wave += 1
                    self.hearts = min(MAX_HEARTS, self.hearts + 1)
                    self.ammo = MAG
                    self.reload_t = 0
                    self.spawn_wave(self.wave)

    # ---- drawing ---------------------------------------------------------------------------
    def draw_world(self):
        w = self.world
        w.blit(self.bg, (0, 0))
        self.plant_glow.set_alpha(int(70 + 30 * math.sin(self.t * 1.6)))
        w.blit(self.plant_glow, self.plant_glow.get_rect(center=(701, 335)))       # breathing specimen-tank glow
        self.rain.draw(w)
        self.fireflies.draw(w, self.t)
        self.fog.draw(w)
        self.leaves.draw(w, front=False)
        for pos, life in self.decals:
            a = clamp(life / 1.5, 0, 1)
            s = pygame.Surface((22, 22), pygame.SRCALPHA)
            pygame.draw.circle(s, (10, 12, 10, int(200 * a)), (11, 11), 5)
            pygame.draw.circle(s, (160, 165, 140, int(120 * a)), (11, 11), 8, 2)
            w.blit(s, (pos.x - 11, pos.y - 11))
        for e in sorted(self.enemies, key=lambda e: e.pos.y):
            e.draw(w)
        for s in self.spores:
            s.draw(w, self)
        self.particles.draw(w)
        self.leaves.draw(w, front=True)
        self.lightning.draw(w)
        if self.muzzle > 0.02:
            v = int(46 * self.muzzle)
            w.fill((v, int(v * 0.85), int(v * 0.5)), special_flags=pygame.BLEND_RGB_ADD)
        w.blit(self.vig, (0, 0))
        low = self.state == "play" and self.hearts == 1
        if self.hurt > 0.02 or low:
            a = self.hurt if self.hurt > 0.02 else 0.35 + 0.2 * math.sin(self.t * 5)
            self.vig_red.set_alpha(int(255 * clamp(a, 0, 1)))
            w.blit(self.vig_red, (0, 0))

    def draw(self):
        scr = self.screen
        self.draw_world()
        if self.shake > 0.2:
            off = (random.uniform(-1, 1) * self.shake, random.uniform(-1, 1) * self.shake)
            scr.fill((0, 0, 0))
        else:
            off = (0, 0)
        scr.blit(self.world, off)
        self.texts.draw(scr, font)
        if self.state == "title":
            self.draw_title(scr)
        elif self.state == "over":
            self.draw_over(scr)
        else:
            self.draw_hud(scr)
        self.draw_banner(scr)
        self.draw_pip(scr)
        if self.paused:
            dim = pygame.Surface((W, H), pygame.SRCALPHA)
            dim.fill((0, 0, 0, 140))
            scr.blit(dim, (0, 0))
            text(scr, "PAUSED", 90, (W / 2, H / 2 - 20), (230, 255, 230), "center", outline=(10, 30, 15))
            text(scr, "press P to continue", 28, (W / 2, H / 2 + 50), (200, 220, 200), "center")
        self.draw_crosshair(scr)

    def target_button(self, scr, center, label, sub=None):
        t = self.t
        cx, cy = center
        r = 78
        for rr, w_, col in ((r + 16 + 4 * math.sin(t * 3), 3, (120, 255, 140)), (r, 6, (255, 190, 70)),
                            (r * 0.62, 6, (255, 100, 70))):
            pygame.draw.circle(scr, (10, 25, 14), center, int(rr) + 2, w_ + 3)
            pygame.draw.circle(scr, col, center, int(rr), w_)
        pygame.draw.circle(scr, (255, 80, 60), center, 10)
        draw_arc(scr, (255, 255, 255), center, r + 30, t * 2, t * 2 + 1.1, 3)
        draw_arc(scr, (255, 255, 255), center, r + 30, t * 2 + math.pi, t * 2 + math.pi + 1.1, 3)
        text(scr, label, 38, (cx, cy + r + 52), (255, 245, 200), "center", outline=(10, 30, 15))
        if sub:
            text(scr, sub, 22, (cx, cy + r + 90), (200, 225, 200), "center")

    def draw_title(self, scr):
        dim = pygame.Surface((W, H), pygame.SRCALPHA)
        dim.fill((0, 8, 4, 110))
        scr.blit(dim, (0, 0))
        text(scr, "R E S I D E N T   E V I L", 34, (W / 2, 62), (210, 235, 200), "center", outline=(8, 24, 12))
        pulse = 0.5 + 0.5 * math.sin(self.t * 2.4)
        text(scr, "GREENHOUSE", 128, (W / 2, 140), (int(150 + 60 * pulse), 255, int(120 + 40 * pulse)),
             "center", outline=(10, 40, 18))
        text(scr, "a hand-gesture shooter", 28, (W / 2, 220), (230, 200, 120), "center")
        self.target_button(scr, (W // 2, 440), "SHOOT THE TARGET TO START", "or press SPACE / click")
        cards = [("AIM", "point your index finger", "aim"), ("FIRE", "drop thumb  or  pinch", "fire"),
                 ("RELOAD", "show an open palm", "reload")]
        for i, (title, sub, icon) in enumerate(cards):
            r = pygame.Rect(30, 290 + i * 102, 300, 90)
            card = pygame.Surface(r.size, pygame.SRCALPHA)
            pygame.draw.rect(card, (6, 20, 12, 175), card.get_rect(), border_radius=14)
            pygame.draw.rect(card, (110, 220, 130, 200), card.get_rect(), 2, border_radius=14)
            scr.blit(card, r)
            self.draw_icon(scr, icon, (r.x + 46, r.centery))
            text(scr, title, 32, (r.x + 94, r.y + 14), (255, 220, 120))
            text(scr, sub, 20, (r.x + 94, r.y + 54), (205, 230, 205))

    def draw_icon(self, scr, kind, c):
        cx, cy = c
        col = (150, 255, 160)
        if kind == "aim":
            pygame.draw.circle(scr, col, c, 24, 3)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                pygame.draw.line(scr, col, (cx + dx * 10, cy + dy * 10), (cx + dx * 34, cy + dy * 34), 3)
        elif kind == "fire":
            pygame.draw.rect(scr, col, (cx - 22, cy - 2, 40, 18), border_radius=6)
            pygame.draw.rect(scr, col, (cx + 6, cy - 22, 30, 8), border_radius=4)
            k = (self.t * 2.0) % 1.0
            ty = cy - 26 - 10 * (1 - k) if k < 0.6 else cy - 8
            pygame.draw.rect(scr, (255, 210, 100), (cx - 12, ty - 4, 8, 22), border_radius=4)
            if k > 0.6:
                pygame.draw.circle(scr, (255, 120, 60), (cx + 46, cy - 18), int(8 * (k - 0.6) * 2.5) + 2)
        else:
            for dx in (-16, -8, 0, 8, 16):
                h_ = 30 - abs(dx) * 0.6
                pygame.draw.rect(scr, col, (cx + dx - 3, cy - h_ + 8, 6, h_), border_radius=3)
            pygame.draw.rect(scr, col, (cx - 19, cy + 6, 38, 18), border_radius=8)
            draw_arc(scr, (255, 210, 100), c, 36, self.t * 3, self.t * 3 + 4.2, 3)

    def draw_over(self, scr):
        dim = pygame.Surface((W, H), pygame.SRCALPHA)
        dim.fill((20, 0, 0, int(min(1, self.over_t) * 170)))
        scr.blit(dim, (0, 0))
        k = ease_out(clamp(self.over_t / 0.8, 0, 1))
        text(scr, "INFECTED", int(60 + 70 * k), (W / 2, 120), (255, 80, 70), "center", outline=(40, 0, 0))
        acc = (100 * self.hits / self.shots) if self.shots else 0
        lines = [f"SCORE   {self.score}", f"BEST   {self.best}", f"WAVES CLEARED   {self.wave - 1}",
                 f"ACCURACY   {acc:.0f}%"]
        for i, l in enumerate(lines):
            text(scr, l, 34 if i else 52, (W / 2, 225 + i * 46 + (12 if i else 0)), (240, 235, 210), "center")
        if self.over_t > 1.2:
            self.target_button(scr, (W // 2, 520), "SHOOT TO TRY AGAIN")

    def draw_banner(self, scr):
        if not self.banner:
            return
        s, sub, left = self.banner
        a = int(255 * clamp(min(left * 2.5, (2.2 - left) * 6), 0, 1))
        text(scr, s, 120, (W / 2, 250), (255, 235, 140), "center", alpha=a, outline=(30, 40, 10))
        text(scr, sub, 30, (W / 2, 330), (230, 255, 220), "center", alpha=a)

    def draw_hud(self, scr):
        text(scr, f"{self.score:06d}", 54, (28, 18), (255, 245, 205), bold=True)
        if self.combo >= 3:
            m = self.mult()
            text(scr, f"COMBO x{m}", 30, (30, 82), (255, 190, 80) if m < 5 else (255, 110, 80))
        self.draw_enemy_bar(scr)
        for i in range(MAX_HEARTS):
            alive = i < self.hearts
            bounce = 3 * math.sin(self.t * 6 + i) if (self.hearts == 1 and alive) else 0
            draw_heart(scr, 52 + i * 52, H - 48 + bounce, 38, (235, 60, 80) if alive else (60, 55, 55))
        for i in range(MAG):
            have = i < self.ammo and self.reload_t <= 0
            x = W - 50 - (MAG - 1 - i) * 30
            pygame.draw.rect(scr, (12, 14, 10), (x - 9, H - 84, 18, 52), border_radius=4)
            pygame.draw.rect(scr, (235, 190, 90) if have else (70, 66, 56), (x - 7, H - 76, 14, 42), border_radius=3)
            pygame.draw.polygon(scr, (200, 120, 60) if have else (60, 56, 48),
                                [(x - 7, H - 76), (x + 7, H - 76), (x, H - 90)])
        mid = W - 50 - (MAG - 1) * 15
        if self.reload_t > 0:
            text(scr, "RELOADING", 28, (mid, H - 124), (255, 220, 120), "midtop")
            bar = pygame.Rect(mid - (MAG - 1) * 15 - 10, H - 28, (MAG - 1) * 30 + 22, 8)
            pygame.draw.rect(scr, (12, 14, 10), bar, border_radius=4)
            pygame.draw.rect(scr, (255, 210, 100), (bar.x, bar.y, int(bar.width * (1 - self.reload_t)), bar.height),
                             border_radius=4)
        elif self.ammo == 0 and int(self.t * 3) % 2 == 0:
            text(scr, "OPEN PALM TO RELOAD", 28, (mid, H - 124), (255, 110, 90), "midtop")
        text(scr, "P pause   R reload   M mouse/hand   F11 fullscreen", 16, (W // 2, H - 10), (170, 195, 170),
             "midbottom", alpha=140)

    def draw_enemy_bar(self, scr):
        alive = [e for e in self.enemies if e.state != "dead"]
        boss = next((e for e in alive if not isinstance(e, enemies.Licker)), None)
        lickers = sum(1 for e in alive if isinstance(e, enemies.Licker) and e.state != "dying")
        cx = W // 2
        y_next = 16
        if boss:
            is_mob = isinstance(boss, Mob)
            name = "MUTANT THORN" if is_mob else boss.NAME
            text(scr, f"{name}  -  WAVE {self.wave}", 24, (cx, 16), (220, 240, 210), "midtop")
            bar = pygame.Rect(cx - 190, 48, 380, 18)
            ratio = clamp(boss.hp / boss.max_hp, 0, 1)
            pygame.draw.rect(scr, (8, 18, 10), bar.inflate(6, 6), border_radius=8)
            pygame.draw.rect(scr, (60, 40, 30), bar, border_radius=7)
            if ratio > 0:
                pygame.draw.rect(scr, (140, 230, 90) if ratio > 0.35 else (255, 130, 70),
                                 (bar.x, bar.y, int(bar.width * ratio), bar.height), border_radius=7)
            pygame.draw.rect(scr, (210, 230, 200), bar, 2, border_radius=7)
            y_next = 78
            if is_mob:
                for i, limb in enumerate(sprites.LIMBS):
                    x = cx - 66 + i * 44
                    on = limb not in boss.disabled
                    pygame.draw.circle(scr, (10, 20, 12), (x, 94), 15)
                    pygame.draw.circle(scr, (255, 175, 60) if on else (110, 112, 110), (x, 94), 12)
                    if on:
                        pygame.draw.circle(scr, (255, 245, 190), (x - 3, 91), 4)
                    text(scr, ("LA", "RA", "LL", "RL")[i], 14, (x, 112), (200, 215, 200), "midtop")
                y_next = 136
        if lickers:
            text(scr, f"LICKERS x{lickers}" if boss else f"LICKERS x{lickers}  -  WAVE {self.wave}", 24,
                 (cx, y_next), (255, 130, 140), "midtop")

    def draw_pip(self, scr):
        inp = self.inp
        if not inp:
            return
        r = pygame.Rect(W - 252, 12, 240, 180) if self.state != "play" else pygame.Rect(W - 172, 12, 160, 120)
        if inp["mode"] == "hand" and inp["preview"] is not None:
            if inp["preview_id"] != self.pip_id:
                arr = inp["preview"]
                self.pip = pygame.image.frombuffer(arr.tobytes(), (arr.shape[1], arr.shape[0]), "RGB").copy()
                self.pip_id = inp["preview_id"]
            img = pygame.transform.smoothscale(self.pip, r.size) if r.size != self.pip.get_size() else self.pip
            scr.blit(img, r)
            pygame.draw.rect(scr, (12, 20, 14), r.inflate(6, 6), 3)
            pygame.draw.rect(scr, (130, 235, 150) if inp["tracking"] else (200, 90, 80), r, 2)
            g = inp["gesture"]
            col = {"COCKED": (255, 215, 90), "AIM": (150, 255, 160), "RELOAD": (120, 200, 255)}.get(g, (230, 200, 190))
            text(scr, g, 24, (r.x + 6, r.bottom + 4), col)
            text(scr, f"thumb {inp['thumb']:.2f}  pinch {inp['pinch']:.2f}", 15, (r.right - 4, r.bottom + 8), (190, 210, 190), "topright", alpha=170)
        else:
            lab = "LOADING TRACKER..." if inp["mode"] == "loading" else "MOUSE MODE"
            card = pygame.Surface((r.w, 44), pygame.SRCALPHA)
            pygame.draw.rect(card, (6, 20, 12, 175), card.get_rect(), border_radius=10)
            scr.blit(card, (r.x, r.y))
            text(scr, lab, 20, (r.centerx, r.y + 22), (230, 220, 160), "center")
        if self.state == "title":
            text(scr, inp["status"], 18, (W - 12, r.bottom + 34), (200, 220, 200), "topright", alpha=210)

    def draw_crosshair(self, scr):
        inp = self.inp
        if not inp:
            return
        pos = self.cross
        over_mob = self.state != "over" and any(e.hit_test(pos) for e in self.enemies)
        over_spore = any((pos - s.pos).length() <= s.radius * 1.3 + 28 for s in self.spores)
        col = (255, 210, 90) if over_spore else ((130, 255, 150) if over_mob else (240, 255, 240))
        tracking = inp["tracking"] or inp["mode"] != "hand"
        size = 130
        surf = pygame.Surface((size, size), pygame.SRCALPHA)
        c = size // 2
        r = 22 + self.kick * 14
        a = 255 if tracking else 90
        pygame.draw.circle(surf, (0, 0, 0, a), (c, c), r + 2, 5)
        pygame.draw.circle(surf, (*col, a), (c, c), r, 3)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            pygame.draw.line(surf, (0, 0, 0, a), (c + dx * (r - 12), c + dy * (r - 12)),
                             (c + dx * (r + 14), c + dy * (r + 14)), 5)
            pygame.draw.line(surf, (*col, a), (c + dx * (r - 10), c + dy * (r - 10)),
                             (c + dx * (r + 12), c + dy * (r + 12)), 3)
        pygame.draw.circle(surf, (255, 70, 60, a), (c, c), 3)
        if inp["cocked"]:
            draw_arc(surf, (255, 215, 80, 255), (c, c), r + 9, -2.4, -0.74, 4)
        if inp["reload_progress"] > 0 and self.ammo < MAG:
            draw_arc(surf, (120, 200, 255, 255), (c, c), r + 17, -math.pi / 2,
                     -math.pi / 2 + math.tau * inp["reload_progress"], 4)
        if self.reload_t > 0:
            draw_arc(surf, (255, 215, 100, 255), (c, c), r + 17, -math.pi / 2,
                     -math.pi / 2 + math.tau * (1 - self.reload_t), 4)
        scr.blit(surf, (pos.x - c, pos.y - c))
        if not tracking:
            text(scr, "show your hand", 20, (pos.x, pos.y + 54), (255, 200, 170), "center", alpha=200)


# ============================================================================================
# main loop
# ============================================================================================
def build_input(snap, game, user_mouse, click_fires, kb_fires, reload_kb):
    use_mouse = snap["mode"] != "hand" or user_mouse
    if use_mouse:
        aim, fires, tracking, cocked = pygame.mouse.get_pos(), click_fires + kb_fires, True, False
    else:
        aim = (snap["aim"][0] * W, snap["aim"][1] * H)
        fires = [(x * W, y * H) for x, y in snap["fires"]] + kb_fires + [tuple(game.cross) for _ in click_fires]
        tracking, cocked = snap["tracking"], snap["cocked"]
    status = snap["status"]
    if snap["mode"] == "hand" and user_mouse:
        status = "Mouse mode (press M for hand mode)"
    return {
        "mode": "loading" if snap["mode"] == "loading" else ("mouse" if use_mouse else "hand"),
        "aim": aim, "fires": fires, "tracking": tracking, "cocked": cocked,
        "reload": reload_kb or (bool(snap["reloads"]) and not use_mouse),
        "reload_progress": 0.0 if use_mouse else snap["reload_progress"],
        "gesture": snap["gesture"], "thumb": snap["thumb"], "pinch": snap["pinch"],
        "preview": snap["preview"], "preview_id": snap["preview_id"], "status": status,
    }


def main():
    ap = argparse.ArgumentParser(description="Resident Evil - Greenhouse (hand gesture shooter)")
    ap.add_argument("--mouse", action="store_true", help="skip the webcam, play with the mouse")
    ap.add_argument("--camera", type=int, default=0, help="webcam index (default 0)")
    ap.add_argument("--no-sound", action="store_true")
    args = ap.parse_args()

    pygame.mixer.pre_init(44100, -16, 2, 512)
    pygame.init()
    pygame.display.set_caption("Resident Evil")
    try:
        screen = pygame.display.set_mode((W, H), pygame.SCALED | pygame.RESIZABLE, vsync=1)
    except Exception:                                                     # noqa: BLE001
        screen = pygame.display.set_mode((W, H), pygame.SCALED | pygame.RESIZABLE)
    clock = pygame.time.Clock()
    screen.fill((6, 14, 8))
    text(screen, "LOADING...", 48, (W / 2, H / 2), (200, 240, 200), "center")
    pygame.display.flip()

    tracker = HandTracker(args.camera, force_mouse=args.mouse)
    tracker.start()                       # camera + model load in the background, the game starts right away
    sfx = fx.Sfx(enabled=not args.no_sound)
    game = Game(screen, sfx)
    sfx.loop_rain()
    user_mouse = args.mouse

    running = True
    while running:
        dt = min(clock.tick(FPS) / 1000.0, 0.05)
        kb_fires, click_fires, reload_kb = [], [], False
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    running = False
                elif e.key in (pygame.K_SPACE, pygame.K_RETURN):
                    kb_fires.append(tuple(game.cross))
                elif e.key == pygame.K_r:
                    reload_kb = True
                elif e.key == pygame.K_p and game.state == "play":
                    game.paused = not game.paused
                elif e.key == pygame.K_m:
                    user_mouse = not user_mouse
                elif e.key == pygame.K_F11:
                    pygame.display.toggle_fullscreen()
            elif e.type == pygame.MOUSEBUTTONDOWN:
                if e.button == 1:
                    click_fires.append(e.pos)
                elif e.button == 3:
                    reload_kb = True
        inp = build_input(tracker.snapshot(), game, user_mouse, click_fires, kb_fires, reload_kb)
        game.update(dt, inp)
        game.draw()
        pygame.display.flip()

    tracker.stop()
    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
