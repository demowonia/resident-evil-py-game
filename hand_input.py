"""
Hand-gesture input: webcam -> MediaPipe Hand Landmarker -> game controls.

GESTURES  (a "finger gun")
    AIM      point with your index finger, the crosshair follows your fingertip
    FIRE     drop your raised thumb onto your hand  OR  pinch thumb + index together  ->  bang
    RELOAD   show an open palm (all 5 fingers) and hold it for ~0.5 s

Everything runs in a background thread so the game keeps its 60 FPS.
If anything fails (no camera, no mediapipe, no internet for the model download)
the tracker switches to mode "mouse" and the game falls back to mouse + keyboard.
"""
import math
import os
import threading
import time
import urllib.request
from collections import deque

import numpy as np

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
             "hand_landmarker/float16/1/hand_landmarker.task")
MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "assets", "models", "hand_landmarker.task")

# ---- tuning knobs ---------------------------------------------------------------------------
THUMB_OPEN = 0.55      # thumb-tip <-> middle-knuckle distance / palm length  : above = thumb raised (cocked)
THUMB_CLOSE = 0.43     # below = thumb dropped (FIRE)
THUMB_DROP = 0.14      # ALSO fire when the thumb ratio falls by this much within THUMB_DROP_WINDOW (works at any hand angle)
THUMB_DROP_WINDOW = 0.35   # seconds
THUMB_REARM = 0.10     # after a drop-shot the thumb must rise this much above its lowest point before it can fire again
PINCH_OPEN = 0.50      # thumb-tip <-> index-tip distance / palm: above = fingers apart
PINCH_CLOSE = 0.24     # below = pinched together (FIRE)
FIRE_COOLDOWN = 0.20   # seconds between two shots
RELOAD_HOLD = 0.45     # seconds of open palm needed to reload
LOST_AFTER = 0.30      # seconds without a hand before tracking is considered lost
# part of the camera image that maps to the whole screen (so you can reach the corners comfortably)
MARGIN_X = (0.14, 0.86)
MARGIN_Y = (0.10, 0.78)
# ---------------------------------------------------------------------------------------------

CONNECTIONS = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10),
               (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (17, 18),
               (18, 19), (19, 20), (0, 17)]


class OneEuro:
    """1-euro filter: smooth when the hand is slow (no jitter), responsive when it moves fast."""

    def __init__(self, min_cutoff=1.5, beta=6.0, d_cutoff=1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.reset()

    def reset(self):
        self.x_prev = None
        self.dx_prev = 0.0
        self.t_prev = None

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x, t):
        if self.x_prev is None:
            self.x_prev, self.t_prev = x, t
            return x
        dt = max(t - self.t_prev, 1e-3)
        dx = (x - self.x_prev) / dt
        a_d = self._alpha(self.d_cutoff, dt)
        dx_hat = a_d * dx + (1 - a_d) * self.dx_prev
        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        a = self._alpha(cutoff, dt)
        x_hat = a * x + (1 - a) * self.x_prev
        self.x_prev, self.dx_prev, self.t_prev = x_hat, dx_hat, t
        return x_hat


def analyze_hand(pts):
    """pts: (21, 3) array in pixel-ish units. Returns a dict describing the hand pose."""
    def d(i, j):
        return float(np.linalg.norm(pts[i] - pts[j]))

    # NOTE: pts should be MediaPipe *world* landmarks (metric 3D, rotation-invariant), so these ratios
    # stay the same whether the hand points sideways, up or straight at the camera.
    palm = d(0, 9) + 1e-6
    reach = {n: d(0, t) / palm for n, t in (("index", 8), ("middle", 12), ("ring", 16), ("pinky", 20))}
    idx = reach["index"] > 1.35
    mid, ring, pinky = reach["middle"] > 1.55, reach["ring"] > 1.5, reach["pinky"] > 1.4
    thumb_ratio = d(4, 9) / palm            # thumb tip <-> middle knuckle
    pinch_ratio = d(4, 8) / palm            # thumb tip <-> index tip
    return {
        "index": idx, "middle": mid, "ring": ring, "pinky": pinky,
        "thumb_ratio": thumb_ratio, "pinch_ratio": pinch_ratio,
        "pointing": idx and not (mid and ring),
        "open_palm": idx and mid and ring and pinky and thumb_ratio > 0.70 and pinch_ratio > 0.5,
    }


class HandTracker(threading.Thread):
    def __init__(self, camera_index=0, force_mouse=False):
        super().__init__(daemon=True)
        self.camera_index = camera_index
        self.force_mouse = force_mouse
        self._halt = threading.Event()
        self._lock = threading.Lock()
        # shared state ------------------------------------------------------
        self.mode = "mouse" if force_mouse else "loading"      # loading | hand | mouse
        self.status = "Mouse mode (forced)" if force_mouse else "Starting..."
        self._aim = (0.5, 0.5)
        self._tracking = False
        self._cocked = False
        self._gesture = "NO HAND"
        self._thumb = 0.0
        self._pinch = 1.0
        self._reload_progress = 0.0
        self._fires = []
        self._reloads = 0
        self._preview = None
        self._preview_id = 0
        self._fps = 0.0

    # ---------------------------------------------------------------- public API (main thread)
    def snapshot(self):
        """Latest state; consumes the pending fire / reload events."""
        with self._lock:
            snap = {
                "mode": self.mode, "status": self.status, "aim": self._aim,
                "tracking": self._tracking, "cocked": self._cocked, "gesture": self._gesture,
                "thumb": self._thumb, "pinch": self._pinch, "reload_progress": self._reload_progress,
                "fires": self._fires, "reloads": self._reloads,
                "preview": self._preview, "preview_id": self._preview_id, "fps": self._fps,
            }
            self._fires = []
            self._reloads = 0
        return snap

    def stop(self):
        self._halt.set()
        if self.is_alive():
            self.join(timeout=2.0)

    # ---------------------------------------------------------------- internals
    def _set(self, **kw):
        with self._lock:
            for k, v in kw.items():
                setattr(self, k, v)

    def _fallback(self, msg):
        self._set(mode="mouse", status=msg, _tracking=False)

    def _ensure_model(self):
        if os.path.exists(MODEL_PATH) and os.path.getsize(MODEL_PATH) > 1_000_000:
            return MODEL_PATH
        os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
        self._set(status="Downloading hand model (one time, ~8 MB)...")
        tmp = MODEL_PATH + ".part"
        urllib.request.urlretrieve(MODEL_URL, tmp)
        os.replace(tmp, MODEL_PATH)
        return MODEL_PATH

    def _open_camera(self, cv2):
        backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY] if os.name == "nt" else [cv2.CAP_ANY]
        for be in backends:
            cap = cv2.VideoCapture(self.camera_index, be)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                cap.set(cv2.CAP_PROP_FPS, 30)
                return cap
            cap.release()
        return None

    def run(self):
        if self.force_mouse:
            return
        try:
            self._set(status="Loading hand tracker...")
            import cv2
            import mediapipe as mp
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision
        except Exception as e:                                  # noqa: BLE001
            self._fallback("mediapipe/opencv missing -> mouse mode  (pip install -r requirements.txt)")
            print("[hand_input] import failed:", e)
            return

        try:
            model_path = self._ensure_model()
        except Exception as e:                                  # noqa: BLE001
            self._fallback("Could not download hand model -> mouse mode (see README)")
            print("[hand_input] model download failed:", e)
            return

        try:
            options = vision.HandLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=model_path),
                running_mode=vision.RunningMode.VIDEO,
                num_hands=1,
                min_hand_detection_confidence=0.5,
                min_hand_presence_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            landmarker = vision.HandLandmarker.create_from_options(options)
        except Exception as e:                                  # noqa: BLE001
            self._fallback("Hand model failed to load -> mouse mode")
            print("[hand_input] landmarker failed:", e)
            return

        self._set(status="Opening camera...")
        cap = self._open_camera(cv2)
        if cap is None:
            self._fallback("No webcam found -> mouse mode (try --camera 1)")
            landmarker.close()
            return

        self._set(mode="hand", status="Hand tracking ready - show your hand")
        try:
            self._loop(cv2, mp, landmarker, cap)
        except Exception as e:                                  # noqa: BLE001
            print("[hand_input] tracking loop crashed:", e)
            self._fallback("Tracking stopped -> mouse mode")
        finally:
            cap.release()
            landmarker.close()

    def _loop(self, cv2, mp, landmarker, cap):
        fx, fy = OneEuro(), OneEuro()
        history = deque(maxlen=12)            # (t, x, y) of the smoothed aim point
        thumb_open = False
        pinch_armed = True
        thumb_hist = deque(maxlen=30)         # (t, thumb_ratio)
        drop_armed = True
        drop_floor = None
        last_fire = 0.0
        palm_since = None
        palm_armed = True
        last_seen = 0.0
        last_ts = 0
        fails = 0
        fps_t, fps_n = time.monotonic(), 0

        while not self._halt.is_set():
            ok, frame = cap.read()
            if not ok:
                fails += 1
                if fails > 150:
                    raise RuntimeError("camera stopped delivering frames")
                time.sleep(0.01)
                continue
            fails = 0
            frame = cv2.flip(frame, 1)                       # mirror: moving right moves the cursor right
            h, w = frame.shape[:2]
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            ts = int(time.monotonic() * 1000)
            ts = ts if ts > last_ts else last_ts + 1
            last_ts = ts
            res = landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts)
            now = time.monotonic()

            gesture = None
            fire_pos = None
            reload_now = False
            if res.hand_landmarks:
                lm = res.hand_landmarks[0]
                pts = np.array([[p.x * w, p.y * h, p.z * w] for p in lm], dtype=np.float32)
                wl = getattr(res, "hand_world_landmarks", None)
                if wl:
                    wpts = np.array([[p.x, p.y, p.z] for p in wl[0]], dtype=np.float32)
                else:                                   # older mediapipe: fall back to image coordinates
                    wpts = pts
                info = analyze_hand(wpts)
                last_seen = now

                # --- aim: index fingertip, remapped so the screen corners are reachable
                nx = (lm[8].x - MARGIN_X[0]) / (MARGIN_X[1] - MARGIN_X[0])
                ny = (lm[8].y - MARGIN_Y[0]) / (MARGIN_Y[1] - MARGIN_Y[0])
                ax = fx(min(max(nx, 0.0), 1.0), now)
                ay = fy(min(max(ny, 0.0), 1.0), now)
                history.append((now, ax, ay))

                # --- fire: (A) thumb raised then dropped, or (B) pinch thumb + index together
                tr, pr = info["thumb_ratio"], info["pinch_ratio"]
                thumb_hist.append((now, tr))
                if not info["open_palm"]:
                    if tr > THUMB_OPEN:
                        thumb_open = True
                    if pr > PINCH_OPEN:
                        pinch_armed = True
                    # relative drop: thumb ratio fell quickly from a recent peak (no absolute threshold needed)
                    peak = max((v for t, v in thumb_hist if now - t <= THUMB_DROP_WINDOW), default=tr)
                    if drop_floor is not None:
                        drop_floor = min(drop_floor, tr)
                        if tr > drop_floor + THUMB_REARM:
                            drop_armed, drop_floor = True, None
                    shot = None
                    if thumb_open and tr < THUMB_CLOSE:
                        thumb_open, shot = False, 0.08
                        drop_armed, drop_floor = False, tr
                    elif drop_armed and peak - tr > THUMB_DROP and tr < peak * 0.8:
                        thumb_open, shot = False, 0.08
                        drop_armed, drop_floor = False, tr
                    elif pinch_armed and pr < PINCH_CLOSE:
                        pinch_armed, shot = False, 0.16
                    if shot is not None and now - last_fire > FIRE_COOLDOWN:
                        ref = now - shot          # aim point from just before the flinch of the gesture
                        old = [hp for hp in history if hp[0] <= ref]
                        hp = old[-1] if old else history[0]
                        fire_pos = (hp[1], hp[2])
                        last_fire = now
                    gesture = "COCKED" if thumb_open else "AIM"
                else:
                    thumb_open = False
                    thumb_hist.clear()

                # --- reload: open palm held for a moment
                if info["open_palm"]:
                    gesture = "RELOAD"
                    if palm_since is None:
                        palm_since = now
                    prog = min((now - palm_since) / RELOAD_HOLD, 1.0)
                    if prog >= 1.0 and palm_armed:
                        reload_now = True
                        palm_armed = False
                else:
                    palm_since = None
                    palm_armed = True
                    prog = 0.0
                if gesture is None:
                    gesture = "HAND"

                with self._lock:
                    self._aim = (ax, ay)
                    self._tracking = True
                    self._cocked = thumb_open
                    self._gesture = gesture
                    self._thumb = tr
                    self._pinch = pr
                    self._reload_progress = prog
                    if fire_pos:
                        self._fires.append(fire_pos)
                    if reload_now:
                        self._reloads += 1

                # --- little preview with the skeleton drawn on it
                for a, b in CONNECTIONS:
                    cv2.line(frame, (int(pts[a][0]), int(pts[a][1])), (int(pts[b][0]), int(pts[b][1])),
                             (80, 255, 160), 2)
                for p in pts:
                    cv2.circle(frame, (int(p[0]), int(p[1])), 3, (255, 255, 255), -1)
                col = (0, 80, 255) if fire_pos else (0, 220, 255)
                cv2.circle(frame, (int(pts[8][0]), int(pts[8][1])), 9, col, 2)
            else:
                if now - last_seen > LOST_AFTER:
                    thumb_open = False
                    palm_since = None
                    palm_armed = True
                    fx.reset()
                    fy.reset()
                    with self._lock:
                        self._tracking = False
                        self._cocked = False
                        self._gesture = "NO HAND"
                        self._reload_progress = 0.0

            small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), (240, 180), interpolation=cv2.INTER_AREA)
            fps_n += 1
            if now - fps_t >= 1.0:
                fps = fps_n / (now - fps_t)
                fps_t, fps_n = now, 0
            else:
                fps = self._fps
            with self._lock:
                self._preview = small
                self._preview_id += 1
                self._fps = fps
