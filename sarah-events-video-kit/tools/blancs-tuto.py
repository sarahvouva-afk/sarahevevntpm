#!/opt/homebrew/bin/python3.11
"""Blancs > MIN s dans une vidéo tuto (voix basse, piste compressée).
Pipeline : RMS par trame (0,18 s) → candidats quiet ≥ MIN-1 s (seuil strict + tolérance clics)
→ Whisper word timestamps sur chaque candidat (fenêtre + marge) → trous réels ≥ MIN s
→ mouvement image (YDIF) sur chaque trou. Bridé nice 19 / 2 threads."""
import sys, os, re, json, subprocess, shutil

F = sys.argv[1]; MIN = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
T_DB = -45.0; PAD = 1.5
S = os.path.dirname(os.path.abspath(__file__)); W = os.path.join(os.environ.get("TMPDIR", "/tmp"), "blancs-tuto"); os.makedirs(W, exist_ok=True)
FF = ["nice", "-n", "19", "ffmpeg", "-hide_banner", "-nostats", "-threads", "2"]
env = dict(os.environ, LC_ALL="C")

def sh(cmd, **kw): return subprocess.run(cmd, capture_output=True, text=True, env=env, **kw)
def ts(t): return f"{int(t//60)}:{t%60:04.1f}"

dur = float(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", F]).stdout.strip())
sr = int(sh(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=sample_rate", "-of", "csv=p=0", F]).stdout.strip())
print(f"fichier : {F}\ndurée   : {ts(dur)}  ·  audio {sr} Hz  ·  seuil {MIN:.0f} s")

# 1. RMS par trame
rms_file = os.path.join(W, "rms.txt")
if os.path.exists(rms_file): os.remove(rms_file)
sh(FF + ["-i", F, "-vn", "-ac", "1", "-af",
         f"asetnsamples=n=8000:p=0,astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file={rms_file}",
         "-f", "null", "-"])
vals = [float(v) if v != "-inf" else -99.0 for v in re.findall(r"RMS_level=(-?[\d.]+|-inf)", open(rms_file).read())]
d = 8000 / sr
print(f"trames  : {len(vals)} × {d:.3f} s")

# 2. candidats : runs quiet (strict) + runs avec tolérance de 2 trames bruyantes (clics)
def runs(tol):
    out = []; run = 0; loud = 0; start = 0
    for i, v in enumerate(vals):
        t = i * d
        if v < T_DB:
            if run == 0: start = t
            run += 1; loud = 0
        elif run > 0 and loud < tol:
            loud += 1; run += 1
        else:
            if run > 0 and (run - loud) * d >= MIN - 1: out.append((start, t - loud * d))
            run = 0; loud = 0
    if run > 0 and (run - loud) * d >= MIN - 1: out.append((start, len(vals) * d))
    return out
cands = sorted(set(runs(0) + runs(2)))
# fusion des candidats qui se chevauchent
merged = []
for a, b in cands:
    if merged and a <= merged[-1][1] + PAD: merged[-1] = (merged[-1][0], max(merged[-1][1], b))
    else: merged.append((a, b))
print(f"candidats audio (≥ {MIN-1:.0f} s sous {T_DB:.0f} dB RMS) : {len(merged)}")

# 3. Whisper mots sur chaque candidat élargi
found = []
for i, (a, b) in enumerate(merged):
    a0, b0 = max(0, a - PAD), min(dur, b + PAD)
    wav = os.path.join(W, f"c{i:02d}.wav")
    sh(FF + ["-loglevel", "error", "-y", "-ss", f"{a0:.2f}", "-t", f"{b0-a0:.2f}", "-i", F, "-vn", "-ac", "1", "-ar", "16000", wav])
    sh(["nice", "-n", "19", "whisper", "--model", "large-v3-turbo", "--language", "fr", "--threads", "2", "--fp16", "False",
        "--word_timestamps", "True", "--output_format", "json", "--output_dir", W, wav])
    j = json.load(open(wav[:-4] + ".json"))
    words = [w for s in j["segments"] for w in s.get("words", [])]
    # bornes : début/fin de fenêtre comptent comme "parole" inconnue → on ne compte que les trous internes,
    # sauf si aucun mot : tout le candidat est un blanc
    if not words:
        gaps = [(a0, b0)]
    else:
        pts = [(a0, a0)] + [(w["start"] + a0, w["end"] + a0) for w in words] + [(b0, b0)]
        gaps = [(pts[k][1], pts[k+1][0]) for k in range(len(pts) - 1)]
    for g0, g1 in gaps:
        if g1 - g0 >= MIN: found.append((g0, g1, words))
    txt = " ".join(w["word"].strip() for w in words)
    print(f"  {ts(a)} → {ts(b)} : {'aucun mot' if not words else 'parole : ' + txt[:70]}")

# 4. mouvement image sur chaque blanc confirmé
print(f"\n=== BLANCS RÉELS ≥ {MIN:.0f} s : {len(found)} ===")
for g0, g1, words in found:
    r = sh(FF + ["-ss", f"{g0:.2f}", "-t", f"{g1-g0:.2f}", "-i", F, "-vf",
                 "fps=2,scale=320:-1,signalstats,metadata=print:key=lavfi.signalstats.YDIF", "-an", "-f", "null", "-"])
    yd = [float(x) for x in re.findall(r"YDIF=([\d.]+)", r.stdout + r.stderr)]
    avg = sum(yd) / len(yd) if yd else 0; mx = max(yd) if yd else 0; act = sum(1 for x in yd if x > 1)
    tag = "ÉCRAN ACTIF (ne pas couper)" if avg > 1.0 or act >= len(yd) * 0.3 else ("quelques mouvements (à regarder)" if mx > 3 else "IMAGE FIGÉE (coupable)")
    before = " ".join(w["word"].strip() for w in words if w["end"] + 0 <= 1e9)[-60:]
    print(f"{ts(g0)} → {ts(g1)}  ({g1-g0:4.1f} s)  motion moy {avg:.2f} / max {mx:.2f} / actives {act}/{len(yd)}  → {tag}")
