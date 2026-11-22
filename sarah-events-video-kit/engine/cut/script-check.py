#!/usr/bin/env python3
"""script-check — écart entre le SCRIPT prévu et ce qui a été DIT dans le rush, AVANT tout dérush.

Pourquoi (06/09/2026, batch client A du 31/08) : detect.py aligne le transcript sur le script et
jette tout mot aligné sur un gap. Quand le speaker reformule une phrase entière, le chunk VAD est
majoritairement « insertion » et part en bloc : hook amputé (ADS6-H3), CTA coupé (ADS7), punchline
remplacée par le 1er mot de la prise suivante (ADS7-H2). Ce script rend l'écart visible avant de
couper : chaque reformulation listée doit devenir un script batch-local (*.fix.txt) = texte dit.

  python script-check.py <rush.words.json> <script.txt> [--min-run 3] [--window 12.8-22.1] [--json out.json]
  --window a-b : ne regarde que les mots du rush entre a et b s (vérifier un hook sur SA fenêtre)

Sortie :
  REFORMULATION [t]  script « … » / dit « … »   -> ≥ min-run mots consécutifs du script absents
  FIN DU SCRIPT ABSENTE DU RUSH                  -> les 3 derniers mots du script n'y sont pas
  PRISE MULTIPLE « … » à t1, t2                  -> même 5-gram répété à > 3 s : fenêtrer / trimmer
Exit 0 = rien à signaler, 2 = au moins une reformulation ou fin absente (écrire le .fix.txt).
"""
import sys, re, json, difflib

def norm(w):
    return re.sub(r"[^a-zàâäéèêëîïôöùûüç0-9]", "", w.lower())

ELIDE = {"j","d","l","c","n","s","t","m","qu","jusqu","lorsqu","puisqu","quoiqu","aujourd"}

def merge_elisions(items):
    out = []
    for it in items:
        if out and norm(out[-1]["text"]) in ELIDE and not out[-1].get("_m"):
            out[-1] = {"text": out[-1]["text"] + "'" + it["text"], "start": out[-1]["start"],
                       "end": it["end"], "_m": True}
        else:
            out.append({**it})
    return out

args = [a for a in sys.argv[1:] if not a.startswith("--")]
opt = {sys.argv[i].lstrip("-"): sys.argv[i + 1] for i in range(1, len(sys.argv) - 1) if sys.argv[i].startswith("--")}
if len(args) < 2:
    print(__doc__); sys.exit(1)
WORDS, SCRIPT = args[0], args[1]
MIN_RUN = int(opt.get("min-run", 3))

raw = json.load(open(WORDS, encoding="utf-8"))["words"]
if "window" in opt:
    a, b = (float(x) for x in opt["window"].split("-"))
    raw = [w for w in raw if a <= w["start"] <= b]
words = [w for w in merge_elisions(raw) if norm(w["text"])]
Tw = [norm(w["text"]) for w in words]
S_raw = [x for x in open(SCRIPT, encoding="utf-8").read().split() if norm(x)]
S = [norm(x) for x in S_raw]

def t_at(i):  # temps du mot transcript i (borné)
    i = max(0, min(i, len(words) - 1))
    return words[i]["start"]

findings = {"reformulations": [], "fin_absente": False, "prises_multiples": []}
sm = difflib.SequenceMatcher(None, Tw, S, autojunk=False)
for tag, i1, i2, j1, j2 in sm.get_opcodes():
    if tag in ("insert", "replace") and (j2 - j1) >= MIN_RUN:
        said = " ".join(w["text"] for w in words[i1:i2]) if tag == "replace" else ""
        ctx_before = " ".join(w["text"] for w in words[max(0, i1 - 4):i1])
        ctx_after = " ".join(w["text"] for w in words[i2:i2 + 4])
        t0 = t_at(i1 - 1) if i1 > 0 else 0.0
        findings["reformulations"].append({
            "t": round(t0, 2), "script": " ".join(S_raw[j1:j2]), "dit": said,
            "contexte": f"{ctx_before} [ … ] {ctx_after}"})

# Fin du script présente ?
tail = S[-3:]
present = any(Tw[k:k + 3] == tail for k in range(len(Tw) - 2))
findings["fin_absente"] = not present

# Prises multiples : 5-gram répété à > 3 s d'écart, regroupées par zone (un n-gram par mot
# sinon : une reprise de 10 mots sortait 6 lignes). Deux hits dont les 1res occurrences sont à
# moins de 2,5 s l'une de l'autre = la même prise.
seen = {}
for k in range(len(Tw) - 4):
    g = " ".join(Tw[k:k + 5])
    seen.setdefault(g, []).append(words[k]["start"])
hits = sorted((ts[0], g, ts) for g, ts in seen.items() if len(ts) >= 2 and ts[-1] - ts[0] > 3.0)
last = None
for t0, g, ts in hits:
    if last is not None and t0 - last < 2.5:
        last = t0; continue
    last = t0
    findings["prises_multiples"].append({"ngram": g, "t": [round(t, 1) for t in ts]})

bad = bool(findings["reformulations"]) or findings["fin_absente"]
for r in findings["reformulations"]:
    print(f"REFORMULATION [{r['t']:.1f}s]  script « {r['script']} »")
    print(f"   dit « {r['dit']} »" if r["dit"] else f"   (absent du rush) contexte : {r['contexte']}")
if findings["fin_absente"]:
    print(f"FIN DU SCRIPT ABSENTE DU RUSH : « {' '.join(S_raw[-3:])} » jamais dit tel quel (CTA reformulé ? fenêtre ?)")
for p in findings["prises_multiples"]:
    print(f"PRISE MULTIPLE « {p['ngram']} » à {', '.join(str(t) + 's' for t in p['t'])}  -> fenêtrer / trimmer le rush")
if not bad and not findings["prises_multiples"]:
    print("OK — script et rush concordent (aucune reformulation ≥ %d mots, fin présente, pas de prise multiple)" % MIN_RUN)
if "json" in opt:
    json.dump(findings, open(opt["json"], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
sys.exit(2 if bad else 0)
