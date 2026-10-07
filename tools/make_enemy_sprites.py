"""
Builds the transparent enemy sprites (Mr. X, Licker, Birkin) from the raw AI-generated art.

    python make_enemy_sprites.py  <mrx_birkin.jpg>  <licker.jpg>  <out_dir>

 - white / checkerboard background is removed (flood-filled from the borders, so white pixels
   INSIDE the art - teeth, eye highlights - are kept)
 - every enemy is cropped, scaled to its in-game size and saved with the feet on the bottom edge
 - animation frames are generated from the single drawing with small warps (sway / stomp / recoil)
"""
import json
import os
import sys

import cv2
import numpy as np

# ---- in-game heights (pixels) ---------------------------------------------------------------
HEIGHT = {"mrx": 420, "licker": 150, "birkin": 400}
PAD = 36                      # transparent margin so leaning / squashed frames never get clipped


def load_rgb(path):
    img = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def cut_background(rgb, min_bright=205, max_sat=14):
    """Return RGBA. Background = bright + neutral pixels connected to the image border."""
    f = rgb.astype(np.int16)
    sat = f.max(2) - f.min(2)
    cand = ((f.min(2) >= min_bright) & (sat <= max_sat)).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(cand, connectivity=4)
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    bg = np.isin(lab, list(border))
    # enclosed gaps (between an arm and the torso...) are background too - only big ones, so small
    # white details such as teeth and eye highlights survive
    big = np.zeros(n, bool)
    big[1:] = st[1:, 4] >= 100
    bg |= big[lab]

    fg = (~bg).astype(np.uint8)
    # drop specks of left-over background / noise, keep only sizeable shapes
    n, lab, st, _ = cv2.connectedComponentsWithStats(fg, connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, 4] >= 400
    fg = keep[lab].astype(np.uint8)
    # fill pin-holes inside the silhouette
    inv = (1 - fg).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(inv, connectivity=4)
    holes = np.zeros(n, bool)
    holes[1:] = st[1:, 4] < 60
    fg = fg | holes[lab].astype(np.uint8)

    # shave the light anti-aliasing fringe: 1px erosion + soft edge
    fg = cv2.erode(fg, np.ones((3, 3), np.uint8))
    a = cv2.GaussianBlur(fg.astype(np.float32), (0, 0), 0.8)
    a = np.clip((a - 0.25) / 0.6, 0, 1)

    out = rgb.copy()
    # de-matte: pull edge colours toward the nearest solid interior colour (kills the white halo)
    solid = (cv2.erode(fg, np.ones((5, 5), np.uint8)) > 0)
    ys, xs = np.nonzero(solid)
    edge = (a > 0) & ~solid
    if edge.any():
        _, idx = cv2.distanceTransformWithLabels((~solid).astype(np.uint8), cv2.DIST_L2, 3,
                                                 labelType=cv2.DIST_LABEL_PIXEL)
        # build map label -> (y,x) of the seed pixel
        seed_lab = idx[ys, xs]
        lut = np.zeros(idx.max() + 1, np.int64)
        lut[seed_lab] = np.arange(len(ys))
        j = lut[idx[edge]]
        out[edge] = rgb[ys[j], xs[j]]
    return np.dstack([out, (a * 255).astype(np.uint8)])


def crop_alpha(rgba, thr=20):
    ys, xs = np.nonzero(rgba[..., 3] > thr)
    return rgba[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def fit(rgba, height):
    h, w = rgba.shape[:2]
    k = height / h
    # premultiply so scaling doesn't bleed black/white into the edges
    f = rgba.astype(np.float32)
    f[..., :3] *= f[..., 3:4] / 255
    f = cv2.resize(f, (max(1, round(w * k)), height), interpolation=cv2.INTER_AREA)
    a = f[..., 3:4]
    f[..., :3] = np.where(a > 0, f[..., :3] * 255 / np.maximum(a, 1e-3), 0)
    return np.clip(f, 0, 255).astype(np.uint8)


def pad_canvas(rgba, pad=PAD):
    h, w = rgba.shape[:2]
    out = np.zeros((h + pad, w + 2 * pad, 4), np.uint8)       # extra room on top only (feet stay on the floor)
    out[pad:, pad:pad + w] = rgba
    return out


def warp(rgba, rot=0.0, sx=1.0, sy=1.0, shear=0.0, dy=0):
    """Transform about the bottom-centre (the feet). rot in degrees (+ = lean right)."""
    h, w = rgba.shape[:2]
    cx, cy = w / 2, h - 1
    r = np.deg2rad(rot)
    R = np.array([[np.cos(r), -np.sin(r)], [np.sin(r), np.cos(r)]])
    S = np.array([[sx, 0], [0, sy]])
    Sh = np.array([[1, shear], [0, 1]])
    M = R @ Sh @ S
    t = np.array([cx, cy + dy]) - M @ np.array([cx, cy])
    A = np.hstack([M, t[:, None]]).astype(np.float32)
    f = rgba.astype(np.float32)
    f[..., :3] *= f[..., 3:4] / 255
    o = cv2.warpAffine(f, A, (w, h), flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0, 0))
    a = o[..., 3:4]
    o[..., :3] = np.where(a > 0, o[..., :3] * 255 / np.maximum(a, 1e-3), 0)
    return np.clip(o, 0, 255).astype(np.uint8)


def shut_eye(rgba, c, r_eye):
    """Paint a closed, swollen eyelid over the open glowing eye at c=(x,y)."""
    out = rgba.copy()
    x, y = int(c[0]), int(c[1])
    h, w = out.shape[:2]
    # flesh colour = median of a ring just outside the eye
    yy, xx = np.mgrid[:h, :w]
    d = np.hypot(xx - x, yy - y)
    ring = (d > r_eye * 1.15) & (d < r_eye * 1.6) & (out[..., 3] > 200)
    flesh = np.median(out[ring][:, :3], axis=0)
    dark = flesh * 0.45
    lid = (d <= r_eye * 1.08)
    # flesh disc with a soft shaded edge
    t = np.clip(d / (r_eye * 1.08), 0, 1)[..., None]
    col = flesh * (1.0 - 0.18 * t ** 3) + 8
    blend = cv2.GaussianBlur(lid.astype(np.float32), (0, 0), 1.2)[..., None]
    out[..., :3] = (out[..., :3] * (1 - blend) + col * blend).astype(np.uint8)
    # eyelid slit (a slightly curved dark line) + lashes-wrinkles
    layer = np.zeros((h, w), np.uint8)
    pts = np.array([[x + int(r_eye * k), y + int(np.sin(k * 2.6) * -r_eye * 0.18 + r_eye * 0.12)]
                    for k in np.linspace(-0.95, 0.95, 15)], np.int32)
    cv2.polylines(layer, [pts], False, 255, max(2, int(r_eye * 0.12)), cv2.LINE_AA)
    wr = layer.copy() * 0
    for k in (-0.55, 0.0, 0.55):
        p0 = (x + int(r_eye * k), y + int(r_eye * 0.18))
        p1 = (x + int(r_eye * (k * 1.25)), y + int(r_eye * 0.62))
        cv2.line(wr, p0, p1, 120, 1, cv2.LINE_AA)
    m = np.maximum(layer, wr).astype(np.float32)[..., None] / 255
    out[..., :3] = (out[..., :3] * (1 - m) + dark * m).astype(np.uint8)
    return out


def save(path, rgba):
    bgra = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)
    ok, buf = cv2.imencode(".png", bgra)
    buf.tofile(path)


def main(src_a, src_b, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    a = cut_background(load_rgb(src_a))
    # split Mr. X (left) / Birkin (right) by the two biggest blobs
    mask = (a[..., 3] > 20).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    big = sorted(range(1, n), key=lambda i: -st[i, 4])[:2]
    big.sort(key=lambda i: st[i, 0])
    parts = {}
    for name, i in zip(("mrx", "birkin"), big):
        x, y, w, h = st[i, :4]
        sub = a[y:y + h, x:x + w].copy()
        sub[..., 3] = np.where((lab == i)[y:y + h, x:x + w], sub[..., 3], 0)
        parts[name] = (sub, (x, y))
    parts["licker"] = (cut_background(load_rgb(src_b)), (0, 0))

    # glowing eye on Birkin's shoulder, in the original jpg (x, y, radius)
    EYE_SRC = (553, 203, 27)
    meta = {}
    for name, (art, (ox, oy)) in parts.items():
        ys, xs = np.nonzero(art[..., 3] > 20)
        x0, y0 = xs.min(), ys.min()
        art = art[y0:ys.max() + 1, x0:xs.max() + 1]
        raw_h, raw_w = art.shape[:2]
        k = HEIGHT[name] / raw_h
        base = pad_canvas(fit(art, HEIGHT[name]))
        H_, W_ = base.shape[:2]
        meta[name] = {"canvas": [W_, H_], "art": [PAD / W_, PAD / H_, (W_ - 2 * PAD) / W_, (H_ - PAD) / H_]}

        if name == "mrx":
            frames = {"mrx0": warp(base, rot=-1.4),
                      "mrx1": warp(base, rot=1.4, sy=0.985),
                      "mrx_hurt": warp(base, rot=-5.5, shear=-0.04, sy=0.97)}
        elif name == "licker":
            frames = {"licker0": base,
                      "licker1": warp(base, sx=1.06, sy=0.93),
                      "licker_hurt": warp(base, rot=7, sx=1.1, sy=0.84)}
        else:
            ex = (EYE_SRC[0] - ox - x0) * k + PAD
            ey = (EYE_SRC[1] - oy - y0) * k + PAD
            er = EYE_SRC[2] * k
            shut = shut_eye(base, (ex, ey), er)
            meta[name]["eye"] = [ex / W_, ey / H_, er / W_]
            frames = {"birkin0": base,
                      "birkin1": warp(base, rot=1.2, sx=1.01, sy=0.975),
                      "birkin_shut0": shut,
                      "birkin_shut1": warp(shut, rot=1.2, sx=1.01, sy=0.975),
                      "birkin_hurt": warp(shut, rot=-4.5, shear=-0.03, sy=0.97)}
        for fn, im in frames.items():
            save(os.path.join(out_dir, fn + ".png"), im)
    json.dump(meta, open(os.path.join(out_dir, "layout.json"), "w"), indent=1)
    return meta


if __name__ == "__main__":
    print(json.dumps(main(*sys.argv[1:4]), indent=1))
