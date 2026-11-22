#!/usr/bin/env python3
"""Face-aware reframe: find the speaker and compute the crop that puts their eye line on
the upper-third line (rule of thirds), whatever the source framing.

  python framing.py <video> <aspectW:aspectH> [--faceline 0.33] [--samples 9]

Prints JSON: {"crop": "w:h:x:y", "eye_y": ..., "face": [cx, cy, w, h], "detected": n}
Exit 3 when no face is found — caller falls back to a centred crop.

Samples frames across the whole clip (edges skipped), takes the MEDIAN face box (robust to
a detection outlier or the speaker leaning), and solves the largest crop window of the
target aspect whose eye line sits at `faceline` of its height, clamped inside the frame.
"""
import sys, json, subprocess, tempfile, os
import numpy as np
import cv2

VIDEO = sys.argv[1]
AW, AH = (int(x) for x in sys.argv[2].split(":"))
FACELINE = float(sys.argv[sys.argv.index("--faceline") + 1]) if "--faceline" in sys.argv else 0.33
SAMPLES = int(sys.argv[sys.argv.index("--samples") + 1]) if "--samples" in sys.argv else 9

probe = subprocess.run(
    ["ffprobe", "-v", "error", "-select_streams", "v:0",
     "-show_entries", "stream=width,height:format=duration", "-of", "json", VIDEO],
    capture_output=True, text=True)
info = json.loads(probe.stdout)
IW, IH = info["streams"][0]["width"], info["streams"][0]["height"]
DUR = float(info["format"]["duration"])

# YuNet (FaceDetectorYN): DNN detector bundled with OpenCV >= 4.5.4 (haar cascades were
# dropped in OpenCV 5). Gives eye landmarks directly — no eye-line approximation needed.
MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "yunet.onnx")
det = cv2.FaceDetectorYN_create(MODEL, "", (IW, IH), 0.6)
faces = []
with tempfile.TemporaryDirectory() as td:
    for i in range(SAMPLES):
        t = DUR * (0.08 + 0.84 * i / max(1, SAMPLES - 1))
        f = os.path.join(td, f"f{i}.jpg")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}",
                        "-i", VIDEO, "-frames:v", "1", "-q:v", "4", f], check=True)
        img = cv2.imread(f)
        if img is None:
            continue
        det.setInputSize((img.shape[1], img.shape[0]))
        _, found = det.detect(img)
        if found is not None and len(found):
            x, y, w, h, rex, rey, lex, ley = max(found, key=lambda d: d[2] * d[3])[:8]
            faces.append((x + w / 2, y + h / 2, w, h, (rey + ley) / 2))

if not faces:
    print(json.dumps({"error": "no face detected"}))
    sys.exit(3)

cx, cy, fw, fh, eye_y = (float(np.median([f[i] for f in faces])) for i in range(5))

# Largest crop of aspect AW:AH with the eye line at FACELINE of its height.
ch = min(IH, (IH - eye_y) / (1 - FACELINE), eye_y / FACELINE)
cw = ch * AW / AH
if cw > IW:
    cw = IW
    ch = cw * AH / AW
cw, ch = int(cw // 2 * 2), int(ch // 2 * 2)
cyy = int(max(0, min(IH - ch, eye_y - FACELINE * ch)))
cxx = int(max(0, min(IW - cw, cx - cw / 2)))

print(json.dumps({"crop": f"{cw}:{ch}:{cxx}:{cyy}", "eye_y": round(eye_y, 1),
                  "face": [round(cx, 1), round(cy, 1), round(fw, 1), round(fh, 1)],
                  "detected": len(faces)}))
