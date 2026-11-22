#!/usr/bin/env python3
"""Waveform-driven VAD + energy analysis for autonomous cut verification.

Reads 16k mono wav, computes a short-time RMS-dB envelope, auto-calibrates the
noise floor from the amplitude histogram (bimodal: room-tone vs speech), and
emits speech intervals. Also exposes a `simulate` mode to score a proposed set
of keep-segments WITHOUT rendering video (fast iteration).

Usage:
  python vad.py analyze audio16k.wav                          -> noise floor, speech level, VAD intervals
  python vad.py envelope audio16k.wav env.json                -> dump per-hop dB envelope
"""
import sys, json, numpy as np
from scipy.io import wavfile

HOP = 0.010     # 10 ms
WIN = 0.025     # 25 ms

def load_env(path):
    sr, x = wavfile.read(path)
    if x.ndim > 1:
        x = x.mean(axis=1)
    x = x.astype(np.float64)
    peak = np.abs(x).max() or 1.0
    x = x / peak
    hop = int(sr * HOP)
    win = int(sr * WIN)
    n = 1 + (len(x) - win) // hop if len(x) >= win else 1
    env = np.empty(n)
    for i in range(n):
        seg = x[i*hop:i*hop+win]
        rms = np.sqrt(np.mean(seg*seg)) if len(seg) else 1e-9
        env[i] = 20*np.log10(rms + 1e-9)
    return sr, env, hop

def load_env_band(path, lo=80.0, hi=1000.0):
    """Enveloppe dB (mêmes hops que load_env, même normalisation par le pic du fichier) sur la
    bande voisée lo-hi Hz. Une queue de fricative (/s/, /f/) n'a presque rien dans cette bande :
    coupée en fin de /s/ elle n'est pas un mot tronqué, une voyelle coupée l'est (08/09/2026)."""
    from scipy.signal import butter, sosfiltfilt
    sr, x = wavfile.read(path)
    if x.ndim > 1:
        x = x.mean(axis=1)
    x = x.astype(np.float64)
    peak = np.abs(x).max() or 1.0
    x = x / peak
    sos = butter(4, [lo, min(hi, sr / 2 - 1)], btype="band", fs=sr, output="sos")
    y = sosfiltfilt(sos, x)
    hop = int(sr * HOP)
    win = int(sr * WIN)
    n = 1 + (len(y) - win) // hop if len(y) >= win else 1
    env = np.empty(n)
    for i in range(n):
        seg = y[i*hop:i*hop+win]
        rms = np.sqrt(np.mean(seg*seg)) if len(seg) else 1e-9
        env[i] = 20*np.log10(rms + 1e-9)
    return sr, env, hop

def calibrate(env):
    # bimodal histogram -> valley between room-tone peak (low) and speech peak (high)
    # Digital-silence hops (encoder-gated zeros, ~-180 dB) would hijack the "room tone" mode
    # and push the valley absurdly low (-165 dB seen on split-pipeline sources) — drop them
    # before calibrating so the histogram is room-tone vs speech, not zeros vs everything.
    e = env[env > -120.0]
    if e.size >= 100:
        env = e
    lo, hi = np.percentile(env, 1), np.percentile(env, 99)
    hist, edges = np.histogram(env, bins=60, range=(lo, hi))
    centers = (edges[:-1]+edges[1:])/2
    # smooth
    k = np.ones(3)/3
    hs = np.convolve(hist, k, mode='same')
    # noise floor = mode of lowest third; speech = mode of highest third
    third = len(centers)//3
    nf = centers[np.argmax(hs[:third])]
    sp = centers[2*third + np.argmax(hs[2*third:])]
    # threshold = valley: lowest bin between nf and sp
    band = (centers > nf) & (centers < sp)
    if band.any():
        idxs = np.where(band)[0]
        thr = centers[idxs[np.argmin(hs[idxs])]]
    else:
        thr = (nf+sp)/2
    return nf, sp, thr

def vad(env, hop, sr, thr, min_speech=0.10, min_sil=0.12, hang=0.05):
    voiced = env > thr
    # close short silences (hangover), then drop short blips
    times = np.arange(len(env)) * (hop/sr)
    ivals = []
    i = 0
    N = len(voiced)
    while i < N:
        if voiced[i]:
            j = i
            while j < N and voiced[j]:
                j += 1
            ivals.append([i, j])
            i = j
        else:
            i += 1
    # merge gaps < min_sil
    merged = []
    for a, b in ivals:
        if merged and (a - merged[-1][1]) * (hop/sr) < min_sil:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    # drop speech shorter than min_speech
    out = [[a, b] for a, b in merged if (b - a) * (hop/sr) >= min_speech]
    # to seconds with hangover pad
    segs = []
    for a, b in out:
        s = max(0.0, a*(hop/sr) - hang)
        e = min(len(env)*(hop/sr), b*(hop/sr) + hang)
        segs.append([round(s, 3), round(e, 3)])
    return segs

if __name__ == "__main__":
    mode, wav = sys.argv[1], sys.argv[2]
    sr, env, hop = load_env(wav)
    if mode == "envelope":
        json.dump({"sr": sr, "hop": hop, "hop_s": HOP, "env": [round(float(v),2) for v in env]},
                  open(sys.argv[3], "w"))
        print("envelope dumped:", len(env), "hops")
    elif mode == "analyze":
        nf, sp, thr = calibrate(env)
        segs = vad(env, hop, sr, thr)
        dur = len(env)*HOP
        speech = sum(b-a for a,b in segs)
        print(f"noise_floor={nf:.1f}dB  speech_level={sp:.1f}dB  VAD_threshold={thr:.1f}dB")
        print(f"total={dur:.1f}s  speech={speech:.1f}s ({speech/dur*100:.0f}%)  segments={len(segs)}")
        json.dump({"nf":nf,"sp":sp,"thr":thr,"segs":segs}, open("vad.json","w"))
        print("wrote vad.json")
