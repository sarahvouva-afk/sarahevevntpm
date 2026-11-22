#!/usr/bin/env python3
"""take-check — pour chaque passage dit PLUSIEURS fois dans le rush, quelle prise le final utilise-t-il ?

Pourquoi (06/09/2026, ADS7 « comme par exemple le syndrome de l'imposteur » à 28 s) : quand le
speaker refait une phrase, c'est que la précédente était ratée ; une QA par transcription ne
l'entend pas (tous les mots y sont). Le seul signal machine : le final a gardé une prise qui
N'EST PAS la dernière. Ce script le dit, avec le timecode dans le final, pour l'oreille.

  python take-check.py <rush.words.json> <final.words.json|final.whisper.json> [--ngram 8]
Sortie : PRISE NON FINALE @<t final>s « … » (prise 1/3 utilisée, dernière à <t rush>s)
Exit 2 si au moins un cas, 0 sinon.
"""
import sys, re, json, difflib

def norm(w): return re.sub(r"[^a-zàâäéèêëîïôöùûüç0-9]", "", w.lower())
def toks(s): return [norm(x) for x in re.split(r"[\s'’\-]+", s) if norm(x)]

def load(path):
    d = json.load(open(path, encoding="utf-8"))
    if "segments" in d:  # whisper
        ws = [{"text": x["word"], "start": x["start"]} for s in d["segments"] for x in s.get("words", [])]
    else:                # scribe
        ws = d["words"]
    out = []
    for w in ws:
        for t in toks(w["text"]): out.append((t, w["start"]))
    return out

args = [a for a in sys.argv[1:] if not a.startswith("--")]
opt = {sys.argv[i].lstrip("-"): sys.argv[i + 1] for i in range(1, len(sys.argv) - 1) if sys.argv[i].startswith("--")}
if len(args) < 2: print(__doc__); sys.exit(1)
NG = int(opt.get("ngram", 8))
R = load(args[0]); F = load(args[1])
Rt = [t for t, _ in R]; Ft = [t for t, _ in F]

# passages repris dans le rush : n-gram présent ≥ 2 fois à > 3 s d'écart, un par zone
occ = {}
for k in range(len(Rt) - NG + 1): occ.setdefault(" ".join(Rt[k:k + NG]), []).append(k)
groups = sorted((R[ks[0]][1], g, ks) for g, ks in occ.items() if len(ks) >= 2 and R[ks[-1]][1] - R[ks[0]][1] > 3.0)
zones, last = [], -99
for t0, g, ks in groups:
    if t0 - last < 2.5: continue
    last = t0; zones.append((g, ks))

# appariement final -> rush par blocs fiables (≥ 3 mots)
sm = difflib.SequenceMatcher(None, Ft, Rt, autojunk=False)
f2r = {}
for a, b, n in sm.get_matching_blocks():
    if n >= 3:
        for i in range(n): f2r[a + i] = b + i

bad = 0
for g, ks in zones:
    # où le n-gram apparaît dans le final ?
    gt = g.split()
    pos = [i for i in range(len(Ft) - NG + 1) if Ft[i:i + NG] == gt]
    if not pos:
        continue  # passage absent du final (jeté ou reformulé : c'est le job de qa.mjs)
    i = pos[0]
    # quelle occurrence ? deux prises ont souvent le même début : on départage sur les 20 mots
    # qui SUIVENT (la suite d'une prise ratée diverge : « …ce sont tous. » vs « …ce sont elles »).
    # Égalité parfaite → on suppose la dernière (rien ne permet de dire le contraire).
    ctxF = Ft[i + NG:i + NG + 20]
    def score(k):
        return difflib.SequenceMatcher(None, ctxF, Rt[k + NG:k + NG + 20], autojunk=False).ratio()
    scores = [score(k) for k in ks]
    best = max(scores)
    which = max(q for q in range(len(ks)) if scores[q] >= best - 0.02)
    if which != len(ks) - 1:
        bad += 1
        print(f"PRISE NON FINALE @{F[i][1]:.1f}s « {' '.join(gt)}… » : prise {which + 1}/{len(ks)} utilisée "
              f"(rush {R[ks[which]][1]:.1f}s), la dernière est à {R[ks[-1]][1]:.1f}s → à écouter")
if not bad: print("OK — chaque passage repris utilise sa dernière prise")
sys.exit(2 if bad else 0)
