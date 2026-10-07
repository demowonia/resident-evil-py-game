# Resident Evil - Greenhouse (pygame + hand gestures)
this is a res evil game i programed for the shellmates welcome day event

Shoot the plant mutant with your **bare hand** (webcam). 

## Install
```
pip install -r requirements.txt
python main.py            # hand-gesture mode
python main.py --mouse    # mouse mode (no webcam needed)
python main.py --camera 1 # use another webcam
```
First launch downloads the MediaPipe hand model (~8 MB) to `assets/models/hand_landmarker.task`.
If the download is blocked, get it from
https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task
and put it at that path. If anything fails, the game falls back to mouse mode automatically.

## Gestures (finger gun)
| Gesture | Action |
|---|---|
| Point your **index finger** (middle + ring curled) | Aim - the crosshair follows your fingertip |
| **Raise your thumb**, then **drop it** | Fire (yellow arc on the crosshair = cocked) |
| **Open palm**, hold ~0.5 s | Reload |

Keyboard: SPACE fire - R reload - M hand/mouse - P pause - F11 fullscreen - ESC quit.
Tip: good light, hand ~50 cm from the camera. Tune thresholds at the top of `hand_input.py`
(the small "thumb 0.xx" readout next to the camera preview shows what the game sees).

## How to play
Shoot the 4 glowing orbs (shoulders/knees) to disable limbs, or whittle his HP down (headshots hurt more).
He spits spores that grow toward you - shoot them before they land. 5 hearts, 6 bullets.
Chain hits for a combo multiplier. Each wave is faster.
