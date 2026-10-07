"""
Procedural pixel-art sprites for the extra enemies (Mr. X, Lickers, Birkin).

You can replace any of them with your own artwork: each make_* function just returns a pygame Surface.
Sprites are drawn on a tiny canvas with flat colours, then a finishing pass adds grain, rim-light and a dark
outline, and everything is scaled up with nearest-neighbour so it looks like real pixel art.
"""
import math

import numpy as np
import pygame

OUT = (14, 10, 18)
PIXEL = 3          # on-screen size of one art pixel


def _canvas(w, h):
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    return s


def poly(s, pts, fill, edge=OUT):
    pygame.draw.polygon(s, fill, pts)
    if edge:
        pygame.draw.polygon(s, edge, pts, 1)


def rect(s, r, fill, edge=OUT, radius=0):
    pygame.draw.rect(s, fill, r, border_radius=radius)
    if edge:
        pygame.draw.rect(s, edge, r, 1, border_radius=radius)


def circ(s, c, r, fill, edge=OUT):
    pygame.draw.circle(s, fill, c, r)
    if edge:
        pygame.draw.circle(s, edge, c, r, 1)


def finish(s, grain=7, seed=1, rim=26, scale=PIXEL):
    """grain + rim light + outline, then nearest-neighbour upscale."""
    rng = np.random.default_rng(seed)
    rgb = pygame.surfarray.array3d(s).astype(np.int16)
    a = pygame.surfarray.array_alpha(s) > 0
    w, h = a.shape
    noise = (rng.integers(-2, 3, (w, h)) * (grain // 2))
    rgb += noise[..., None]
    # rim light on top/left edges, shade on bottom/right edges
    up = a & ~np.pad(a, ((0, 0), (1, 0)))[:, :-1]
    left = a & ~np.pad(a, ((1, 0), (0, 0)))[:-1, :]
    dn = a & ~np.pad(a, ((0, 0), (0, 1)))[:, 1:]
    rt = a & ~np.pad(a, ((0, 1), (0, 0)))[1:, :]
    lit = up | left
    shade = (dn | rt) & ~lit
    rgb[lit] += rim
    rgb[shade] -= rim
    # vertical light falloff: top brighter, bottom darker
    grad = np.linspace(10, -22, h)[None, :, None]
    rgb = rgb + grad.astype(np.int16)
    rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    # outline
    m = a
    ring = (np.pad(m, ((1, 1), (0, 0)))[2:, :] | np.pad(m, ((1, 1), (0, 0)))[:-2, :] |
            np.pad(m, ((0, 0), (1, 1)))[:, 2:] | np.pad(m, ((0, 0), (1, 1)))[:, :-2]) & ~m
    out = np.zeros((w, h, 4), np.uint8)
    out[..., :3] = rgb
    out[..., 3] = np.where(m, 255, 0)
    out[ring, :3] = OUT
    out[ring, 3] = 255
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.surfarray.pixels3d(surf)[:] = out[..., :3]
    pygame.surfarray.pixels_alpha(surf)[:] = out[..., 3]
    return pygame.transform.scale(surf, (w * scale, h * scale)).convert_alpha()


# ============================================================================================
# MR. X  - towering, silent, trench coat + fedora            canvas 84 x 112
# ============================================================================================
def make_mrx(phase=0):
    s = _canvas(86, 114)
    COAT, COAT_L, COAT_D = (40, 40, 48), (66, 66, 80), (22, 22, 28)
    SKIN, SKIN_D = (158, 162, 156), (108, 112, 108)
    HAT, BAND = (34, 34, 42), (84, 66, 66)
    GLOVE, BOOT, PANTS = (30, 30, 36), (20, 20, 24), (44, 44, 52)
    a, b = (0, 3) if phase == 0 else (3, 0)          # leg lift
    # legs + boots
    rect(s, (30, 90 - a, 13, 16), PANTS)
    rect(s, (44, 90 - b, 13, 16), PANTS)
    rect(s, (27, 104 - a, 17, 8), BOOT, radius=2)
    rect(s, (43, 104 - b, 17, 8), BOOT, radius=2)
    # arms (swing with phase)
    sw = 2 if phase == 0 else -2
    poly(s, [(5, 40), (17, 36), (19, 84 + sw), (7, 88 + sw)], COAT)
    poly(s, [(67, 36), (80, 40), (78, 88 - sw), (66, 84 - sw)], COAT)
    circ(s, (13, 92 + sw), 7, GLOVE)
    circ(s, (72, 92 - sw), 7, GLOVE)
    # coat body + long flared skirt
    poly(s, [(16, 36), (70, 36), (74, 52), (74, 90), (80, 96), (6, 96), (12, 90), (12, 52)], COAT)
    poly(s, [(12, 76), (74, 76), (80, 96), (6, 96)], COAT_D, None)
    pygame.draw.line(s, COAT_D, (43, 44), (43, 96), 2)
    for y in (54, 66, 78):
        circ(s, (47, y), 2, (90, 90, 100), None)
    # lapels + shirt
    poly(s, [(28, 36), (43, 36), (43, 62), (30, 52)], COAT_L)
    poly(s, [(58, 36), (43, 36), (43, 62), (56, 52)], COAT_L)
    poly(s, [(36, 36), (50, 36), (43, 52)], (176, 176, 184), None)
    # head
    rect(s, (36, 28, 14, 9), SKIN_D, None)
    poly(s, [(32, 14), (54, 14), (56, 26), (50, 33), (36, 33), (30, 26)], SKIN)
    rect(s, (31, 16, 24, 3), SKIN_D, None)                       # brim shadow
    rect(s, (36, 21, 5, 3), (10, 10, 14), None)                   # eyes
    rect(s, (46, 21, 5, 3), (10, 10, 14), None)
    pygame.draw.line(s, (140, 56, 56), (49, 16), (52, 29), 1)      # scar
    pygame.draw.line(s, (60, 40, 40), (38, 29), (48, 29), 1)       # mouth
    # fedora
    poly(s, [(20, 14), (66, 14), (70, 18), (16, 18)], HAT)
    poly(s, [(31, 2), (55, 2), (57, 15), (29, 15)], HAT)
    rect(s, (29, 11, 28, 3), BAND, None)
    pygame.draw.line(s, (20, 20, 26), (36, 3), (50, 3), 1)
    return finish(s, seed=11 + phase)


# ============================================================================================
# LICKER - skinless crawler with exposed brain, faces left      canvas 82 x 50
# ============================================================================================
def make_licker(phase=0):
    s = _canvas(82, 50)
    RED, RED_D, RED_L = (184, 54, 68), (126, 32, 48), (214, 92, 96)
    BRAIN, BRAIN_D = (238, 150, 160), (190, 100, 120)
    BONE = (232, 222, 196)
    f = 0 if phase == 0 else 1
    # far-side legs (darker)
    poly(s, [(30, 26), (24, 36 + f), (16 + 3 * f, 46)], RED_D, None)
    pygame.draw.line(s, RED_D, (30, 26), (24, 36 + f), 4)
    pygame.draw.line(s, RED_D, (24, 36 + f), (16 + 3 * f, 46), 3)
    pygame.draw.line(s, RED_D, (62, 26), (70 - 3 * f, 36), 4)
    pygame.draw.line(s, RED_D, (70 - 3 * f, 36), (62 - 4 * f, 46), 3)
    # tail
    pygame.draw.line(s, RED_D, (70, 18), (80, 8 + f * 2), 3)
    # body
    poly(s, [(26, 17), (40, 10), (58, 11), (72, 18), (68, 28), (48, 31), (30, 29)], RED)
    for x in (36, 44, 52, 60):
        circ(s, (x, 11 + (x % 8) // 4), 2, RED_L, None)           # spine knobs
    pygame.draw.line(s, RED_D, (34, 24), (66, 24), 1)
    # head
    poly(s, [(5, 20), (12, 12), (28, 13), (32, 22), (26, 30), (10, 30)], RED_D)
    poly(s, [(8, 19), (14, 15), (26, 16), (28, 22), (22, 27), (10, 27)], RED)
    # exposed brain
    pygame.draw.ellipse(s, BRAIN, (12, 5, 20, 13))
    pygame.draw.ellipse(s, OUT, (12, 5, 20, 13), 1)
    for x in (16, 21, 26):
        pygame.draw.line(s, BRAIN_D, (x, 7), (x + 1, 15), 1)
    pygame.draw.line(s, BRAIN_D, (14, 11), (30, 11), 1)
    # mouth + teeth
    rect(s, (4, 22, 10, 6), (60, 10, 24), None)
    for x in (5, 8, 11):
        pygame.draw.line(s, BONE, (x, 22), (x, 24), 1)
    # (no eyes, they are skinless)
    # near-side legs
    pygame.draw.line(s, RED, (32, 27), (26, 38 - f), 5)
    pygame.draw.line(s, RED, (26, 38 - f), (18 - 3 * f, 47), 4)
    pygame.draw.line(s, RED, (64, 27), (72 + 3 * f, 38), 5)
    pygame.draw.line(s, RED, (72 + 3 * f, 38), (64 + 4 * f, 47), 4)
    for cx, cy in ((18 - 3 * f, 47), (64 + 4 * f, 47)):
        for d in (-3, 0, 3):
            pygame.draw.line(s, BONE, (cx, cy), (cx + d, cy + 2), 1)
    return finish(s, grain=8, seed=21 + phase, rim=30)


# ============================================================================================
# BIRKIN - hulking mutated flesh, giant eye on the shoulder      canvas 136 x 124
# ============================================================================================
def make_birkin(phase=0, eye_open=True):
    s = _canvas(136, 124)
    FLESH, FLESH_L, FLESH_D = (200, 132, 98), (226, 164, 126), (146, 76, 66)
    MUSCLE, MUSCLE_D = (160, 46, 52), (104, 28, 38)
    BONE = (232, 220, 190)
    sw = 0 if phase == 0 else 3
    # legs
    poly(s, [(40, 86), (64, 86), (66, 118), (32, 118)], FLESH_D)
    poly(s, [(72, 86), (96, 86), (104, 118), (70, 118)], FLESH_D)
    for x in (30, 38, 46):
        pygame.draw.line(s, BONE, (x, 118), (x + 1, 122), 2)
    for x in (72, 80, 90, 98):
        pygame.draw.line(s, BONE, (x, 118), (x + 1, 122), 2)
    # left (viewer) arm
    poly(s, [(8, 50), (28, 42), (30, 92), (12, 98)], FLESH)
    poly(s, [(12, 62), (26, 60), (27, 82), (14, 86)], MUSCLE, None)
    circ(s, (20, 100), 8, FLESH_D)
    # torso
    poly(s, [(24, 40), (110, 40), (120, 66), (102, 94), (34, 94), (16, 66)], FLESH)
    poly(s, [(40, 52), (96, 52), (100, 72), (88, 90), (48, 90), (36, 72)], MUSCLE)
    for y in (60, 70, 80):                                           # rib lines
        pygame.draw.line(s, MUSCLE_D, (44, y), (92, y), 2)
    pygame.draw.line(s, MUSCLE_D, (68, 52), (68, 90), 2)
    poly(s, [(30, 46), (46, 44), (40, 60), (28, 60)], FLESH_L, None)
    # head (small, sunk between the shoulders)
    poly(s, [(52, 20), (84, 20), (88, 38), (48, 38)], (150, 120, 118))
    poly(s, [(52, 14), (84, 14), (86, 22), (50, 22)], (40, 30, 40))      # hair
    circ(s, (60, 28), 3, (20, 10, 14), None)
    circ(s, (76, 28), 3, (20, 10, 14), None)
    pygame.draw.line(s, (60, 20, 30), (58, 34), (78, 34), 2)
    # big right arm with claws
    poly(s, [(98, 38), (122, 40), (134, 62), (134, 104 - sw), (116, 112 - sw), (100, 92)], FLESH)
    poly(s, [(106, 50), (128, 62), (126, 98 - sw), (112, 100 - sw)], MUSCLE, None)
    for x, dx in ((114, -2), (122, 0), (130, 2)):
        poly(s, [(x - 3, 108 - sw), (x + 3, 108 - sw), (x + dx, 122)], BONE)
    for (ex, ey) in ((124, 70), (118, 88 - sw)):                          # tiny extra eyes (decoration)
        circ(s, (ex, ey), 4, (250, 224, 120))
        circ(s, (ex, ey), 1, (20, 10, 10), None)
    pygame.draw.line(s, MUSCLE_D, (108, 100), (104, 118), 2)
    # the weak point: giant eye on the left shoulder
    ex, ey = 30, 50
    if eye_open:
        circ(s, (ex, ey), 14, (244, 210, 84))
        circ(s, (ex, ey), 9, (236, 110, 30), None)
        pygame.draw.ellipse(s, (20, 6, 8), (ex - 2, ey - 8, 4, 16))
        for ang in range(0, 360, 50):
            r = math.radians(ang)
            pygame.draw.line(s, (176, 40, 52), (ex + 10 * math.cos(r), ey + 10 * math.sin(r)),
                             (ex + 14 * math.cos(r), ey + 14 * math.sin(r)), 1)
    else:
        circ(s, (ex, ey), 14, MUSCLE_D)
        pygame.draw.arc(s, OUT, (ex - 11, ey - 7, 22, 14), 3.4, 6.0, 2)
        pygame.draw.line(s, (200, 70, 70), (ex - 10, ey), (ex + 10, ey), 2)
    return finish(s, grain=8, seed=31 + phase, rim=28)


if __name__ == "__main__":
    import os
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    pygame.init()
    pygame.display.set_mode((10, 10))
    imgs = [make_mrx(0), make_mrx(1), make_licker(0), make_licker(1), make_birkin(0), make_birkin(1, False)]
    W = sum(i.get_width() for i in imgs) + 20 * len(imgs)
    H = max(i.get_height() for i in imgs) + 20
    sheet = pygame.Surface((W, H))
    sheet.fill((30, 44, 36))
    x = 10
    for i in imgs:
        sheet.blit(i, (x, H - i.get_height() - 10))
        x += i.get_width() + 20
    pygame.image.save(sheet, "/home/claude/enemy_sheet.png")
    print(sheet.get_size())
