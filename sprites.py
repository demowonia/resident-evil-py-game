"""
Sprite loading for the greenhouse mutant.

Your idle_*.png files are RGB images on a white background, so they are cut out
here at load time (white background -> transparent, soft orange glow -> translucent halo).
The pose_*.png files already have transparency.

Orb (weak point) positions are measured in the 850x728 idle sprite space.
"""
import itertools
import os

import cv2
import numpy as np
import pygame

LIMBS = ["left_arm", "right_arm", "left_leg", "right_leg"]
LIMB_LABEL = {
    "left_arm": "LEFT ARM", "right_arm": "RIGHT ARM",
    "left_leg": "LEFT LEG", "right_leg": "RIGHT LEG",
}

# (x, y, radius) of every glowing orb in the 850x728 idle sprite
ORBS = {
    "left_arm": (278, 350, 27),
    "right_arm": (490, 345, 27),
    "left_leg": (314, 558, 25),
    "right_leg": (446, 558, 25),
}
IDLE_SIZE = (850, 728)
IDLE_ANCHOR = (425, 650)            # where the feet touch the floor
HEAD_ELLIPSE = (360, 225, 135, 125)  # cx, cy, rx, ry (sprite space)
BODY_RECT = (250, 335, 275, 300)     # x, y, w, h (sprite space)
HEAD_POINT = (355, 285)              # where spores are spat from
POSE_SCALE = 1.32                    # pose_*.png are drawn smaller than idle_*.png

POSES = {
    "hit": "pose_1_shocked_hit.png",
    "stagger": "pose_2_backward_stagger.png",
    "recover": "pose_3_recovery.png",
    "collapse": "pose_4_dazed_collapse.png",
}


def _read(path):
    """cv2.imread that also survives non-ASCII Windows paths. Returns RGB(A)."""
    data = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(path)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    elif img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
    else:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    return img


def key_white(rgb, thr=245, min_area=120, zone=61, floor=110):
    """White background -> alpha, with proper un-mixing of the soft glow around the orbs."""
    rgb = rgb.astype(np.float32)
    mn = rgb.min(2)
    cand = (mn >= thr).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(cand, connectivity=4)
    big = np.zeros(n, bool)
    big[1:] = st[1:, 4] >= min_area
    bg = big[lab]

    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (zone, zone))
    zone_mask = cv2.dilate(bg.astype(np.uint8), k) > 0
    bg = bg | ((cand > 0) & ~bg & zone_mask)          # glow remnants count as background
    inzone = zone_mask & ~bg

    a = np.ones(mn.shape, np.float32)
    a_est = np.clip((255 - mn) / (255 - floor), 0, 1)
    warm = (rgb[..., 0] - rgb[..., 2]) > 12            # glow is warm; grey orbs/outlines are not
    glow = inzone & (warm | (mn >= 235))
    a[glow] = a_est[glow]
    a[bg] = 0

    edge = (cv2.dilate(bg.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0) & ~bg
    a[edge & (mn > 150) & ~warm] = 0                    # light anti-aliasing pixels hugging the outline

    out = rgb.copy()
    m = glow & (a > 0.02) & (a < 1)
    am = a[m][:, None]
    out[m] = np.clip((rgb[m] - (1 - am) * 255) / am, 0, 255)   # recover the glow colour
    return np.dstack([out, a * 255]).astype(np.uint8)


def _to_surface(rgba, scale):
    rgba = rgba.copy()
    rgba[rgba[..., 3] == 0, :3] = 0            # no white fringe when scaling
    h, w = rgba.shape[:2]
    surf = pygame.image.frombuffer(rgba.tobytes(), (w, h), "RGBA").copy()
    if scale != 1.0:
        surf = pygame.transform.smoothscale(surf, (max(1, int(w * scale)), max(1, int(h * scale))))
    return surf.convert_alpha()


class Frame:
    """A pre-scaled sprite and the point (inside it) where the feet touch the floor."""

    def __init__(self, surf, anchor):
        self.surf = surf
        self.anchor = anchor
        self.center = (surf.get_width() / 2, surf.get_height() / 2)


def _grey_name(grey):
    return "idle_grey_" + "_".join(l for l in LIMBS if l in grey) + ".png"


def load_mob_frames(assets_dir, scale):
    """Returns (idle, poses): idle[frozenset(grey_limbs)] -> Frame, poses[name] -> Frame."""
    idle_rgb = {}
    for r in range(1, 5):
        for combo in itertools.combinations(LIMBS, r):
            idle_rgb[frozenset(combo)] = _read(os.path.join(assets_dir, _grey_name(combo)))[..., :3]

    # No file has "nothing disabled": rebuild it by pasting the glowing left-arm orb into another frame.
    a = idle_rgb[frozenset(["left_arm"])].copy()
    b = idle_rgb[frozenset(["right_arm"])]
    x, y, r = ORBS["left_arm"]
    pad = r + 10
    a[y - pad:y + pad, x - pad:x + pad] = b[y - pad:y + pad, x - pad:x + pad]
    idle_rgb[frozenset()] = a

    idle = {}
    for key, rgb in idle_rgb.items():
        idle[key] = Frame(_to_surface(key_white(rgb), scale),
                          (IDLE_ANCHOR[0] * scale, IDLE_ANCHOR[1] * scale))

    poses = {}
    for name, fname in POSES.items():
        img = _read(os.path.join(assets_dir, fname))
        alpha = img[..., 3]
        ys, xs = np.nonzero(alpha > 128)
        bottom = ys.max()
        cx = xs[ys > bottom - 30].mean()
        s = scale * POSE_SCALE
        poses[name] = Frame(_to_surface(img, s), (cx * s, bottom * s))
    return idle, poses
