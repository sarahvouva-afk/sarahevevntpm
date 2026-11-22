#!/usr/bin/env python3
"""Reel-cut objective verification gates (all waveform-derived, no ASR).

  python verify.py <cut.wav> <keep.edl.json> <source_audio16k.wav>

GATE 1 (seams): every concat seam must sit in silence within +/-50ms -> no severed word
                (a cut through a word = audible stutter; ASR verification MISSES this).
GATE 2 (silence): max internal silence + count of gaps > 150ms (incisive).
Exit 0 only if GATE 1 passes.
"""
import sys, json, numpy as np, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vad import load_env, load_env_band, calibrate

CUT, EDL, SRC = sys.argv[1], sys.argv[2], sys.argv[3]
HOP = 0.010
segs = json.load(open(EDL))["segments"]
_, env0, _ = load_env(SRC)
NF0, SP0, valley = calibrate(env0); thr = min(valley + 7.0, SP0 - 12.0)   # même garde-fou que detect
DECAY_DB = float(os.environ.get("DECAY_DB", 30.0))
_, env, _ = load_env(CUT)
_, envv, _ = load_env_band(CUT)   # bande voisée 80-1000 Hz

# GATE 1 — seams
seams, acc = [], 0.0
for i, (a, b) in enumerate(segs):
    acc += (b - a)
    if i < len(segs) - 1: seams.append(acc)
# Durci 08/09/2026 : un seul hop sous le plancher à ±50 ms laissait passer des raccords en
# pleine parole (« le lien | de cette », ADS3). Il faut un vrai creux : ≥ 3 hops (30 ms)
# consécutifs sous thr dans ±80 ms autour du seam.
MARG = 0.08
bad = []
for s in seams:
    lo, hi = max(0, int((s - MARG) / HOP)), min(len(env), int((s + MARG) / HOP))
    w = env[lo:hi]
    # silence RELATIF : sous thr, ou ≥ 25 dB sous le pic de parole des 0,5 s précédentes (un studio
    # très silencieux donne un thr si bas que le souffle normal ne passe jamais dessous : client B 006).
    i = int(s / HOP); pk = float(env[max(0, i - 50):max(1, i)].max()) if i > 1 else thr
    sil = max(thr, pk - 25.0)
    run_, best = 0, 0
    for v in w:
        run_ = run_ + 1 if v < sil else 0
        best = max(best, run_)
    if w.size and best < 3:
        bad.append((round(s, 2), round(float(w.min()), 1)))
    # queue de mot : même critère que detect._decayed_out (08/09/2026 soir) : dans les 30 ms
    # avant le seam, le son est retombé à DECAY_DB sous le pic (ou au plancher + 6 dB), 3 dB
    # de tolérance (ré-encodage AAC, normalisation par le pic propre à chaque fichier).
    pre = float(env[max(0, i - 3):max(1, i)].max())
    target = max(NF0 + 6.0, pk - DECAY_DB)
    # …et dans la bande voisée : une fin de fricative (/s/ de « t'intéresse ») reste à -33 dB en
    # bande large sans qu'aucune voyelle ne soit coupée ; on exige que la bande voisée ait
    # décru d'autant (sinon c'est une voyelle tronquée = severed).
    pkv = float(envv[max(0, i - 50):max(1, i)].max()) if i > 1 else thr
    prev_ = float(envv[max(0, i - 3):max(1, i)].max())
    if i > 3 and pre > target + 3.0 and pre > thr and prev_ > pkv - DECAY_DB + 3.0:
        bad.append((round(s, 2), round(pre, 1)))

# GATE 2 — silence
vf = env > thr
runs = []; i = 0; N = len(vf)
while i < N:
    if not vf[i]:
        k = i
        while k < N and not vf[k]: k += 1
        runs.append(((k - i) * HOP, i * HOP, k * HOP)); i = k
    else: i += 1
dur = len(env) * HOP
intern = [r for r in runs if r[1] >= 0.02 and r[2] <= dur - 0.02]
longest = max((r[0] for r in intern), default=0.0)
speech = float(np.sum(vf)) * HOP

print(f"duration={dur:.1f}s speech={speech/dur*100:.0f}% seams={len(seams)}")
print(f"GATE2 silence: max_internal={longest*1000:.0f}ms gaps>250ms={sum(1 for r in intern if r[0]>0.25)} gaps>150ms={sum(1 for r in intern if r[0]>0.15)}")
if bad:
    print(f"GATE1 seams: FAIL — {len(bad)} severed (energy never hits floor):")
    for s, e in bad: print(f"    @ {s}s min={e}dB (>{thr:.1f})")
    sys.exit(1)
print("GATE1 seams: PASS (every seam in silence, no severed word)")
sys.exit(0)
