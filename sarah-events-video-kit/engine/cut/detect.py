#!/usr/bin/env python3
"""Reel-cut disfluency detection + boundary-safe keep-EDL (frozen standard).

Aligns a VERBATIM word-level transcript to the intended SCRIPT (Needleman-Wunsch);
words aligned to a gap = disfluency (false start / retake / filler) -> cut. Substitutions
(ASR mishears) are kept. Then cuts by classifying whole silence-bounded VAD chunks, and
trims each kept chunk to its real speech extent + tiny margin (incisive, seams in silence).

  python detect.py <words.json> <script.txt> <audio16k.wav> [out_edl.json] [remove.json]

Frozen params (validated on IMG_0819 -> cut-v10, 2026-07-24):
  LEAD=0.045  TRAIL=0.020  thr_off=+7dB  min_sil=0.10  (override via env LEAD/TRAIL)
"""
import sys, os, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from vad import load_env, calibrate

WORDS, SCRIPT, AUDIO = sys.argv[1], sys.argv[2], sys.argv[3]
OUT_EDL = sys.argv[4] if len(sys.argv) > 4 else "keep.edl.json"
OUT_REM = sys.argv[5] if len(sys.argv) > 5 else "remove.json"
FILLERS = {"euh", "bah", "ben", "hein", "donc", "voilà", "voila", "quoi", "ok", "ça", "ca", "genre", "enfin", "alors"}
LEAD  = float(os.environ.get("LEAD", 0.045))
TRAIL = float(os.environ.get("TRAIL", 0.020))
THR_OFF = float(os.environ.get("THR_OFF", 7.0))
MIN_SIL = float(os.environ.get("MIN_SIL", 0.10))
HOP = 0.010

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

raw = json.load(open(WORDS, encoding="utf-8"))["words"]
words = merge_elisions(raw)
T = [norm(w["text"]) for w in words]
idxmap = [i for i, t in enumerate(T) if t]
Tw = [T[i] for i in idxmap]
S = [w for w in (norm(x) for x in open(SCRIPT, encoding="utf-8").read().split()) if w]

# --- Needleman-Wunsch AFFINE (Gotoh). Bug corrigé 28/08/2026 : avec un gap linéaire,
# « matcher l'instance d'origine d'un n-gram répété » et « sauter l'origine pour matcher
# une instance lointaine » ont EXACTEMENT le même score (la répétition compense mot pour
# mot) — le tie-break "garde la dernière prise" choisissait alors l'instance lointaine et
# fragmentait la phrase d'origine (vécu 3x : « c'est ça », « moins de six ans », « compte »,
# phrases dites 2-3x avec faux départs). En affine, la fragmentation coûte une OUVERTURE
# de gap supplémentaire et perd ; sur un vrai retake adjacent les deux choix restent à
# égalité et le tie-break M>X (match d'abord, en remontant depuis la fin) garde bien la
# DERNIÈRE prise, comme avant.
m, n = len(Tw), len(S)
MATCH, MIS = 2.0, -2.0
GO, GE = -2.5, -0.5   # gap open / extend
NEG = -1e9
EPS = 1e-6
M = np.full((m + 1, n + 1), NEG); X = np.full((m + 1, n + 1), NEG); Y = np.full((m + 1, n + 1), NEG)
M[0][0] = 0.0
for i in range(1, m + 1): X[i][0] = GO + GE * (i - 1)
for j in range(1, n + 1): Y[0][j] = GO + GE * (j - 1)
for i in range(1, m + 1):
    ti = Tw[i - 1]
    Mi, Mp, Xi, Xp, Yi, Yp = M[i], M[i - 1], X[i], X[i - 1], Y[i], Y[i - 1]
    for j in range(1, n + 1):
        sc = MATCH if ti == S[j - 1] else MIS
        Mi[j] = sc + max(Mp[j - 1], Xp[j - 1], Yp[j - 1])
        Xi[j] = max(Mp[j] + GO, Xp[j] + GE, Yp[j] + GO)
        Yi[j] = max(Mi[j - 1] + GO, Yi[j - 1] + GE, Xi[j - 1] + GO)
ins = [False] * m
i, j = m, n
def _best(cands):
    # tie-break par ordre de liste (M avant X avant Y)
    top = max(c[1] for c in cands)
    return next(c[0] for c in cands if c[1] >= top - EPS)
state = _best([("M", M[i][j]), ("X", X[i][j]), ("Y", Y[i][j])])
while i > 0 and j > 0:
    if state == "M":
        state = _best([("M", M[i-1][j-1]), ("X", X[i-1][j-1]), ("Y", Y[i-1][j-1])])
        i -= 1; j -= 1
    elif state == "X":
        ins[i-1] = True
        state = _best([("M", M[i-1][j] + GO), ("X", X[i-1][j] + GE), ("Y", Y[i-1][j] + GO)])
        i -= 1
    else:
        state = _best([("M", M[i][j-1] + GO), ("Y", Y[i][j-1] + GE), ("X", X[i][j-1] + GO)])
        j -= 1
while i > 0:
    ins[i-1] = True; i -= 1

spans = []; run = []
for p in range(m):
    if ins[p]: run.append(p)
    elif run: spans.append(run); run = []
if run: spans.append(run)

all_spans = []
for run in spans:
    oi0, oi1 = idxmap[run[0]], idxmap[run[-1]]
    t0, t1 = words[oi0]["start"], words[oi1]["end"]
    # A span can spill over the START of the good take (script paraphrase makes its first
    # words look like insertions: "Sur ces" vs script "Sur les"). When the span contains a
    # truncation-marked word — the real end of the aborted take — stop the cut THERE and
    # keep everything after it. Seen live: "ces dernières anné-— Sur ces" was eating the
    # "Sur ces" of the take that airs.
    marked = [p for p in run if re.search(r"[-—]$", words[idxmap[p]]["text"].strip())]
    if marked and marked[-1] != run[-1]:
        t1 = words[idxmap[marked[-1]]]["end"]
        run = run[:run.index(marked[-1]) + 1]
    dur = t1 - t0
    conf = "HIGH" if (len(run) >= 3 or dur >= 0.6) else ("MED" if (len(run) == 2 and dur >= 0.25) else "LOW")
    # A truncation marker is hard evidence of a stutter/false start, whatever the span size
    # ("dépa- du département") — promote so the span reaches the removal list.
    if conf == "LOW" and re.search(r"[-—]$", words[idxmap[run[-1]]]["text"].strip()):
        conf = "MED"
    # (08/09/2026 soir : une règle « filler isolé → MED » a été essayée puis retirée : retirer un « bah » de
    # 80 ms au milieu d'une phrase continue crée un raccord en pleine parole, ADS4 « que, bah, ce qui
    # m'empêchait » → « ce qui m'empêchait » perdu. Un mot isolé hors script reste gardé (LOW).)
    all_spans.append({"t0": round(t0, 2), "t1": round(t1, 2), "n": len(run),
                      "dur": round(dur, 2), "conf": conf,
                      "quote": " ".join(words[idxmap[p]]["text"] for p in run)})

remove = [s for s in all_spans if s["conf"] in ("HIGH", "MED")]

# Prises multiples d'un passage (06/09/2026, ADS7 « comme par exemple le syndrome de
# l'imposteur… » dit 3 fois, ADS6 « quand on libère un blocage inconscient… » dit 2 fois) :
# le tie-break « garder la DERNIÈRE prise » de l'alignement ne joue que sur du texte
# présent dans le script ; sur une phrase improvisée ou reformulée, la 1re prise (la ratée,
# sinon le speaker ne l'aurait pas refaite) était gardée et les suivantes jetées comme
# insertions. Règle mécanique : un n-gram de ≥ 8 mots qui réapparaît à > 3 s = reprise ;
# tout ce qui va du début de la 1re occurrence au début de la dernière (≤ 30 s) part.
# Deux portées : 8 mots répétés à ≤ 30 s (une phrase entière refaite), 5 mots répétés à ≤ 12 s
# (une reprise courte et rapide : « ces blocages à la source… Ouh là… ces blocages à la
# source », ADS7 06/09). Au-delà de 12 s, 5 mots identiques peuvent être un vrai rappel
# (« le lien sous cette vidéo » dit à deux endroits du CTA d'ADS6) : on ne touche pas.
_retakes = []
# RETAKE_NGRAM=0 (15/09/2026, batch client C) : désactive la règle « n-gram répété = reprise » quand
# les vraies reprises ont été retirées physiquement du média (bodyonly.py) et que le speaker
# répète volontairement ses formules (« on se dit à dans quelques jours en live » ×2, « le
# webinaire trois point zéro » ×2, « cinquante mille euros par mois » ×2 chez un client) : la
# règle avalait 6 à 18 s de contenu légitime par ad. Défaut = 1 (comportement inchangé).
_NGRAM_RULE = os.environ.get("RETAKE_NGRAM", "1") != "0"
for NG, MAXGAP in (((8, 30.0), (5, 12.0)) if _NGRAM_RULE else ()):
    _occ = {}
    for k in range(len(Tw) - NG + 1):
        _occ.setdefault(" ".join(Tw[k:k + NG]), []).append(k)
    for g, ks in _occ.items():
        if len(ks) < 2: continue
        t_first, t_last = words[idxmap[ks[0]]]["start"], words[idxmap[ks[-1]]]["start"]
        if t_last - t_first <= 3.0 or t_last - t_first > MAXGAP: continue
        if any(a - 0.5 <= t_first <= b + 0.5 for a, b, *_ in _retakes): continue
        # Début réel des prises (08/09/2026 soir, ADS2 « C'est exactement ce qu'a vécu Coralie… »
        # dit 3 fois) : le n-gram commun peut tomber au MILIEU du passage (les prises diffèrent
        # d'un mot au début) ; borner sur lui avalait la tête de la dernière prise (160-165 s
        # perdus). On remonte mot à mot tant que les deux prises disent la même chose.
        i, j = ks[0], ks[-1]; _skips = 0
        while i > 0 and j - 1 > i:
            if Tw[i - 1] == Tw[j - 1]: i -= 1; j -= 1; continue
            if _skips >= 2: break                       # tolérance : 2 mots d'écart max entre les prises
            if i > 1 and Tw[i - 2] == Tw[j - 1]: i -= 2; j -= 1; _skips += 1; continue      # mot en plus dans la 1re (« bah », ADS4)
            if j > 1 and j - 2 > i and Tw[i - 1] == Tw[j - 2]: i -= 1; j -= 2; _skips += 1; continue   # mot en plus dans la dernière
            break
        if i < ks[0]:
            t_first, t_last = words[idxmap[i]]["start"], words[idxmap[j]]["start"]
            print(f"  retake ×n : n-gram « {g[:40]} » remonté de {ks[0] - i} mot(s) au début commun des prises")
        _retakes.append((t_first, t_last, i, j, g))
# Bégaiement immédiat : ≥ 3 mots identiques répétés à la SUITE (« et et et », « dans ton dans
# ton »). Strictement adjacents, sinon « mille euros avec Facebook et quatre mille euros avec »
# passe pour une reprise (vu au test).
# RETAKE_ADJ=0 (15/09/2026, ADS19 client C) : « est-ce que ça te parle, est-ce que ça te parle pas » est une
# vraie répétition rhétorique, pas un bégaiement — la règle avalait la première moitié. Défaut = 1.
_ADJ_RULE = os.environ.get("RETAKE_ADJ", "1") != "0"
for n in ((6, 5, 4, 3) if _ADJ_RULE else ()):
    for k in range(len(Tw) - 2 * n + 1):
        j = k + n
        if Tw[k:k + n] == Tw[j:j + n]:
            t0, t1 = words[idxmap[k]]["start"], words[idxmap[j]]["start"]
            if 0 < t1 - t0 <= 4.0 and not any(a - 0.5 <= t0 < b - 0.5 for a, b, *_ in _retakes):   # < b-0.5 : un bégaiement EN TÊTE de la dernière prise (ADS6 « c'est pour ça, c'est pour ça que ») reste à couper
                _retakes.append((t0, t1, k, j, " ".join(Tw[k:k + n])))
# Même début → la zone la PLUS LONGUE d'abord (un bégaiement de 4 mots au début d'une prise
# refaite en entier ne doit pas éclipser la reprise complète, vu ADS6 « c'est pour ça que »).
_retakes.sort(key=lambda r: (r[0], -r[1]))
# Un passage repris produit plusieurs n-grams qui se chevauchent ; seul le PREMIER (t0 le plus
# tôt) donne la bonne zone [début 1re prise, début dernière prise]. Les suivants commencent
# à l'intérieur de cette zone et finissent DANS la dernière prise : on les ignore, jamais de
# fusion (vu : « comme par exemple… » entièrement perdu au 1er essai, 06/09/2026).
_accepted = []
for t0, t1, k0, k1, g in _retakes:
    # ignorée seulement si strictement INCLUSE dans la zone précédente (sous-n-gram du même
    # passage) ; une zone adjacente (bégaiement puis reprise complète, ADS6 « c'est pour ça
    # que, c'est pour ça que dans quelques jours… ») est une zone à part entière.
    if _accepted and _accepted[-1][0] <= t0 < _accepted[-1][1] - 0.5: continue
    # Faux départs trop courts pour un 8-gram juste avant la 1re prise (« comme par exemple…
    # [pause] comme par exemple le syndrome… ») : même 3 premiers mots dans les 12 s qui
    # précèdent → la zone commence là (sinon un « comme » orphelin reste devant la bonne prise).
    g3 = Tw[k0:k0 + 3]
    for k in range(max(0, k0 - 60), k0):
        if Tw[k:k + 3] == g3 and t0 - 12.0 <= words[idxmap[k]]["start"] < t0:
            t0 = words[idxmap[k]]["start"]; break
    _accepted.append([t0, t1, g])
# La dernière prise est PROTÉGÉE : de son début jusqu'à sa première vraie pause (≥ 0.6 s
# après au moins 2 s de parole, plafond 12 s). Aucun autre span ne peut y mordre — sinon le
# span d'alignement d'origine (qui voit toute la reprise comme une insertion) la reprend.
_protected = []
for t0, t1, g in _accepted:
    nw = sum(1 for w in words if t0 <= w["start"] < t1)
    remove.append({"t0": round(t0, 2), "t1": round(t1 - 0.01, 2), "n": nw, "dur": round(t1 - t0, 2),
                   "conf": "HIGH", "quote": f"[prise(s) précédente(s) de] {g[:60]}", "retake_ngram": True})
    end = t1 + 12.0
    ws = [w for w in words if w["start"] >= t1 - 0.01]
    for a, b in zip(ws, ws[1:]):
        if a["end"] - t1 >= 2.0 and b["start"] - a["end"] >= 0.6:
            end = a["end"]; break
    _protected.append((t1, min(end, t1 + 12.0)))
    print(f"  retake ×n : [{t0:.2f}-{t1:.2f}]s ({nw}w) « {g[:60]} » dit plusieurs fois → on garde la dernière prise (protégée jusqu'à {_protected[-1][1]:.2f}s)")
# Exception (08/09/2026, ADS3 client A) : un faux départ DANS la prise protégée (« …t'intéresse
# car grâce à cette méthode... Non, on va le refaire. Car grâce à la méthode ») reste une
# disfluence à couper : ses mots sont repris juste après. La protection ne vaut que pour
# les spans SANS reprise (paraphrases que l'alignement prend pour des disfluences).
def _restart_after(sp):
    if re.search(r"\.\.\.\s*$|[-—]\s*$", sp["quote"]): return True
    sw = [norm(x) for x in sp["quote"].split() if norm(x)]
    if len(sw) < 2: return False
    after = [norm(w["text"]) for w in words if sp["t1"] <= w["start"] <= sp["t1"] + 15.0][:max(12, len(sw) + 4)]
    head = sw[:4]   # le DÉBUT du span repris = reprise, même si la suite est un commentaire (« Non, on va le refaire »)
    if sum(1 for t in head if t in after) >= min(3, len(head)): return True
    return sum(1 for t in set(sw) if t in after) >= max(2, len(set(sw)) // 2)
if _protected:
    clipped = []
    for s in remove:
        if s.get("retake_ngram"): clipped.append(s); continue
        hit = [(p0, p1) for p0, p1 in _protected if not (s["t1"] <= p0 or s["t0"] >= p1)]
        if not hit: clipped.append(s); continue
        p0, p1 = hit[0]
        # Faux départ jugé sur la PARTIE du span située dans la prise protégée (08/09/2026 soir, ADS6) :
        # un span qui commence avant la prise (queue de la prise 1 + tête de la dernière) voyait sa
        # tête « ces blocages inconscients… » réapparaître après t1 (suite normale de la dernière
        # prise) et passait pour un faux départ : le CTA de la dernière prise partait avec.
        a_, b_ = max(s["t0"], p0), min(s["t1"], p1)
        inner = dict(s, t0=a_, t1=b_, quote=" ".join(w["text"] for w in words if a_ <= w["start"] < b_))
        if inner["quote"].strip() and _restart_after(inner): s["restart"] = True; clipped.append(s); continue   # faux départ repris : on coupe malgré la protection
        if s["t0"] < p0: s["t1"] = round(p0 - 0.01, 2)      # mord par l'avant : on coupe au début de la prise
        elif s["t1"] > p1: s["t0"] = round(p1 + 0.01, 2)    # mord par l'arrière : on repart après
        else: s = None                                       # entièrement dans la prise : abandonné
        if s and s["t1"] > s["t0"]: clipped.append(s)
    remove = clipped
remove.sort(key=lambda s: s["t0"])
json.dump({"remove": remove, "low": [s for s in all_spans if s['conf'] == 'LOW']},
          open(OUT_REM, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for s in remove:
    print(f"  cut [{s['t0']}-{s['t1']}]s ({s['n']}w {s['conf']})  \"{s['quote'][:60]}\"")
print(f"=> {len(remove)} disfluences, removed_speech={sum(s['dur'] for s in remove):.1f}s")

# --- boundary-safe cut: classify whole VAD chunks, trim to speech extent + margin ---
def wmid(w): return 0.5 * (w["start"] + w["end"])
removed_word = [any(s["t0"] - 0.05 <= wmid(w) <= s["t1"] + 0.05 for s in remove) for w in words]

sr, env, _ = load_env(AUDIO)
NF_, SP_, valley = calibrate(env)
# Garde-fou (08/09/2026 soir, ADS5-H3) : fenêtre de hook courte, bruyante, sans vrai silence →
# histogramme non bimodal, vallée à -15,7 dB, seuil -8,7 dB au-dessus de la voix, EDL vide.
# Le seuil de parole ne dépasse jamais le niveau de parole - 12 dB.
SPEECH_MARGIN = float(os.environ.get("SPEECH_MARGIN", 12.0))   # 15/09/2026 : réglable par ad (rush extérieur, mots doux « bah », « Alors voilà » sous le plafond)
thr = min(valley + THR_OFF, SP_ - SPEECH_MARGIN)
if thr < valley + THR_OFF: print(f"WARN calibration : vallée {valley:.1f} dB trop proche de la parole {SP_:.1f} dB → seuil plafonné à {thr:.1f} dB")
vf = env > thr
r = []; i = 0; N = len(vf)
while i < N:
    if vf[i]:
        k = i
        while k < N and vf[k]: k += 1
        r.append([i, k]); i = k
    else: i += 1
mg = []
for a, b in r:
    if mg and (a - mg[-1][1]) * HOP < MIN_SIL: mg[-1][1] = b
    else: mg.append([a, b])
vad = [[a*HOP, b*HOP] for a, b in mg if (b - a) * HOP >= 0.08]

keep = []
for vs, ve in vad:
    ws = [k for k, w in enumerate(words) if vs <= wmid(w) <= ve]
    if not ws: continue
    if sum(1 for k in ws if removed_word[k]) / len(ws) >= 0.5: continue
    a, b = int(vs / HOP), int(ve / HOP)
    voiced = np.where(env[a:b] > thr)[0]
    if voiced.size == 0: continue
    s0 = (a + voiced[0]) * HOP
    e0 = (a + voiced[-1] + 1) * HOP
    # Clamp to the WORDS actually spoken in the chunk: breath, rustle or a sigh keeps the
    # energy above threshold and stretches the voiced extent past the speech — on camera
    # that's a second of the speaker glancing at their notes. Words are the truth.
    s0 = max(s0, words[ws[0]]["start"] - 0.25)
    e0 = min(e0, words[ws[-1]]["end"] + 0.15)
    # …dans les DEUX sens (fix 28/08/2026) : une attaque ou une queue de mot en fondu
    # passe sous le plancher VAD À L'INTÉRIEUR du chunk et l'étendue voisée mord alors
    # dans le mot (queue de « business, » coupée à 17.47 / fin réelle 17.60, attaque
    # d'« enfance. » rognée — vécu client A ADS1). Jamais commencer après le début du
    # premier mot ni finir avant la fin du dernier.
    s0 = min(s0, words[ws[0]]["start"])
    e0 = max(e0, words[ws[-1]]["end"])
    if e0 - s0 < 0.05: continue
    keep.append([max(0.0, s0 - LEAD), e0 + TRAIL])

keep.sort()

# Mots sous le plancher VAD (fix 28/08/2026) : une fin de phrase dite en voix qui tombe
# (« …rendre compte. » client A, le « génération. » final du 006 client B) n'allume jamais le
# VAD → aucun chunk ne la couvre, le mot est avalé (ou tronqué par le clamp e0) sans que
# GATE1 le voie — le seam est dans un vrai creux d'énergie. Les MOTS font foi : on ÉTEND
# le chunk voisin jusqu'au mot (jamais de fusion globale ni de nouveau chunk, ça
# regonflait les micro-silences légitimes). Garde-fous : durée de mot 0.02-2.0 s et
# distance au chunk <= 0.5 s, sinon c'est un artefact d'alignement Scribe (vécu :
# « Maintenant, » étiré sur 3.4 s dans le 006), pas une fin de phrase.
_rescued = 0
_rescued_idx = []
for _k, _w in enumerate(words):
    if removed_word[_k]: continue
    _dur = _w["end"] - _w["start"]
    if _dur < 0.02 or _dur > 2.0: continue
    _mid = wmid(_w)
    if any(s <= _mid <= e for s, e in keep): continue
    _s0, _e0 = max(0.0, _w["start"] - LEAD), _w["end"] + TRAIL
    _best = None
    for _seg in keep:
        _d = (_s0 - _seg[1]) if _s0 >= _seg[1] else ((_seg[0] - _e0) if _seg[0] >= _e0 else 0.0)
        if _best is None or _d < _best[0]: _best = (_d, _seg)
    if _best is None or _best[0] > 0.5: continue
    _seg = _best[1]
    _seg[0] = min(_seg[0], _s0)
    _seg[1] = max(_seg[1], _e0)
    _rescued += 1; _rescued_idx.append(_k)
if _rescued:
    keep.sort()
    print(f"=> word rescue: {_rescued} mot(s) sous le plancher VAD réinjecté(s)")

# HIGH-confidence spans must go even when they sit inside a mostly-clean chunk (the 50%
# rule keeps the chunk whole and the retake survives — seen on mid-sentence retakes with
# no real pause). But ONLY with retake evidence: a trailing truncation marker in the span,
# or the span's words reappearing right after it (the speaker restarted the phrase). HIGH
# spans without that evidence are usually alignment false-positives on a paraphrase of the
# script ("des empreintes biologiques" vs "une empreinte biologique") — cutting those
# destroys legitimate content, and the 50% chunk rule already neutralises them.
# Seams are placed on the lowest-energy hop near each boundary (quietest spot available).
def quietest(t, lo_off, hi_off):
    a = max(0, int((t + lo_off) / HOP)); b = min(len(env), int((t + hi_off) / HOP))
    if b <= a: return t
    return (a + int(np.argmin(env[a:b]))) * HOP

def is_retake(sp):
    if sp.get("retake_ngram"): return True
    if re.search(r"[-—]\s*$|[-—]\s", sp["quote"]): return True
    sw = {norm(x) for x in sp["quote"].split() if norm(x)}
    if not sw: return False
    win = max(4.0, sp["t1"] - sp["t0"] + 1.0)
    # Restart after the span (cut the FIRST take: false start puis reprise)…
    after = [norm(w["text"]) for w in words
             if sp["t1"] <= w["start"] <= sp["t1"] + win][:max(10, len(sw))]
    if sum(1 for t in after if t in sw) >= max(2, min(len(sw), len(after)) // 2):
        return True
    # …ou variante A/B où on coupe la SECONDE prise : l'évidence (la prise gardée)
    # est AVANT le span, pas après. Sans ce miroir, le doublon survit — vu sur le
    # rush ads1 juillet (prises webinaire/challenge enchaînées sans pause).
    before = [norm(w["text"]) for w in words
              if sp["t0"] - win <= w["end"] <= sp["t0"]][-max(10, len(sw)):]
    return sum(1 for t in before if t in sw) >= max(2, min(len(sw), len(before)) // 2)

def subtract(intervals):
    global keep
    for c0, c1 in intervals:
        if c1 <= c0: continue
        nxt = []
        for s, e in keep:
            if e <= c0 or s >= c1:
                nxt.append([s, e]); continue
            if s < c0: nxt.append([s, c0])
            if e > c1: nxt.append([c1, e])
        keep = nxt

# Seam windows bornés par les MOTS, pas par un offset fixe : on cherche le hop le plus
# silencieux dans le vrai trou inter-mots (fin du dernier mot gardé -> début du span, et
# fin du span -> début du mot suivant). Une fenêtre fixe de 150 ms rate la respiration
# quand elle est un peu plus loin, et pose le seam en pleine voix (seam sévéré GATE1).
def seam_lo(t):
    prev_end = max((w["end"] for w in words if w["end"] <= t + 0.02), default=t - 0.12)
    return quietest(0, min(prev_end, t - 0.08) - 0.04, t + 0.03)

ENTRY_AIR = float(os.environ.get("ENTRY_AIR", 0.08))   # air minimal avant le mot entrant (brand.cut.entryAir)
def seam_hi(t):
    nxt_start = min((w["start"] for w in words if w["start"] >= t - 0.02), default=t + 0.12)
    # (09/09/2026, ADS5 client A) : quand un mot commence à t (borne d'une reprise = 1er mot de la
    # dernière prise, « Il pensait… »), le point le plus calme de la fenêtre était le micro-blanc
    # APRÈS ce mot court (souffle avant, 60 ms de creux après) : « Il » partait avec la coupe.
    # Le raccord d'entrée ne dépasse jamais 80 ms avant le début du mot suivant (à 20 ms, ADS4 :
    # l'attaque de « Justement » passait avant la coupe image, −23 ms au banc).
    return min(quietest(0, t - 0.03, max(nxt_start, t + 0.08) + 0.04), nxt_start - ENTRY_AIR)

# Cluster de débris : quand une prise refaite laisse plusieurs spans proches (queue de
# prise A + variante B + bout de fin), le petit span de queue n'a pas son évidence dans
# la fenêtre is_retake (elle est une prise entière en arrière) — mais s'il suit de près
# un span déjà jugé retake, il fait partie du même nettoyage. Vu sur ads1 juillet :
# "ces dix-huit derniers mois." résiduel 0.76s après le span principal.
_cut_spans = []
_last_t1 = None
for _sp in sorted(remove, key=lambda s: s["t0"]):
    # restart (08/09/2026 soir) : un faux départ repris passe _restart_after mais pas is_retake ;
    # sans soustraction précise, son premier mot survivait dans le chunk voisin (« t'intéresse
    # car | Car grâce à la méthode », ADS3 v11 : « car » doublé + coupe en pleine parole).
    if is_retake(_sp) or _sp.get("restart") or (_last_t1 is not None and _sp["t0"] - _last_t1 <= 1.5):
        _cut_spans.append(_sp)
        _last_t1 = _sp["t1"]

_cut_intervals = [(seam_lo(sp["t0"]), seam_hi(sp["t1"])) for sp in _cut_spans]
subtract(_cut_intervals)

# Breath tightening: an audible breath is NOISE, not silence, so the VAD keeps it and the
# chunk rule never sees it. Any gap between two consecutive WORDS longer than MAX_PAUSE
# is squeezed — keep the natural release/attack margins, land the seam on the quietest
# hops inside the breath. MAX_PAUSE=0 disables.
MAX_PAUSE = float(os.environ.get("MAX_PAUSE", 0.40))
if MAX_PAUSE > 0:
    tight = []
    for k in range(len(words) - 1):
        g0, g1 = words[k]["end"], words[k + 1]["start"]
        if g1 - g0 > MAX_PAUSE:
            c0 = quietest(g0 + 0.12, -0.04, 0.20)
            c1 = quietest(g1 - 0.10, -0.20, 0.04)
            if c1 - c0 >= 0.10:
                tight.append((c0, c1))
    subtract(tight)
    print(f"=> breath tightening: {len(tight)} pauses > {MAX_PAUSE}s squeezed")

# Une coupe se PAIE : elle casse la continuité de l'image (le speaker rebouge entre deux
# prises, le zoom du punch-in change) et le spectateur la voit. En dessous de MIN_GAP le
# trou retiré ne rembourse pas ce coût — on garde la micro-pause plutôt que le raccord.
# Vu sur client A ADS2 hook 1 (31/08/2026) : coupe à 2.13 s pour 67 ms retirées, zoom
# quasi identique des deux côtés, lue comme un accroc en pleine phrase.
# Un trou qui recouvre une disfluence retirée n'est JAMAIS recollé : le rendre au montage
# réinjecterait le bafouillage. Seuls les trous de silence/respiration sont candidats.
MIN_GAP = float(os.environ.get("MIN_GAP", 0.25))
def protege(g0, g1):
    return any(c0 < g1 and c1 > g0 for c0, c1 in _cut_intervals)
merged = []
recolles = 0
for s, e in keep:
    if e - s < 0.05: continue
    if merged:
        gap = s - merged[-1][1]
        if gap <= 0.005 or (gap < MIN_GAP and not protege(merged[-1][1], s)):
            if gap > 0.005: recolles += 1
            merged[-1][1] = max(merged[-1][1], e)
            continue
    merged.append([round(s, 3), round(e, 3)])
print(f"=> min-gap: {recolles} coupes < {MIN_GAP}s recollées (trou rendu au montage)")

# Blancs (08/09/2026, audit client A : blancs de 0,4 à 1,2 s livrés sur ADS2/ADS3). Deux
# origines que les règles ci-dessus ne voient pas : (1) Scribe colle la pause au mot
# précédent (« cible. » 36.46-37.40 pour 0,3 s de voix) donc le gap inter-mots est nul et
# MAX_PAUSE ne se déclenche pas ; (2) un seam de retake garde le silence des DEUX côtés
# (fin de prise A + début de prise B = 1,22 s après « arnaque »). Passe finale sur
# l'ENVELOPPE, indépendante de l'ASR : tout silence (< thr) de plus de MAX_SIL à
# l'intérieur d'un chunk ou à cheval sur un seam est ramené à SIL_KEEP_OUT + SIL_KEEP_IN.
# Le trou retiré crée un raccord (jump cut), grammaire normale d'une ad. MAX_SIL=0 désactive.
MAX_SIL = float(os.environ.get("MAX_SIL", 0.30))
SIL_KEEP_OUT = float(os.environ.get("SIL_KEEP_OUT", 0.12))   # gardé après le dernier son
SIL_KEEP_IN = float(os.environ.get("SIL_KEEP_IN", 0.08))     # gardé avant le son suivant
def _silent_runs(a, b):
    """runs [t0,t1] où env < thr, à l'intérieur de [a,b] (temps rush)"""
    i0, i1 = max(0, int(a / HOP)), min(len(env), int(b / HOP))
    runs, i = [], i0
    while i < i1:
        if env[i] < thr:
            j = i
            while j < i1 and env[j] < thr: j += 1
            runs.append([i * HOP, j * HOP]); i = j
        else: i += 1
    return runs
# Les MOTS font foi sur les bords (08/09/2026 soir, ADS3 : client A laisse tomber la voix en
# fin de mot, l'énergie passe sous thr 150 ms avant la fin du mot transcrit et la coupe
# mangeait la queue de « négocient », « formulaire », « direct »). Une sortie ne précède
# jamais la fin du dernier mot + WORD_OUT, une entrée ne suit jamais le début du mot
# suivant - WORD_IN.
WORD_OUT, WORD_IN = 0.06, 0.05
def _cut_out(r0):
    # plafond +0,30 s : les fins de mots Scribe débordent parfois de 0,5 à 0,9 s dans le silence
    # (client B 006 : +4 blancs ≥ 0,4 s sans plafond) ; la queue audible est gérée par _decayed_out.
    we = [w["end"] for w in words if r0 - 0.6 <= w["end"] <= r0 + 0.4]
    return max(r0 + SIL_KEEP_OUT, min((max(we) + WORD_OUT) if we else 0.0, r0 + 0.30))
def _cut_in(r1):
    ws_ = [w["start"] for w in words if r1 - 0.4 <= w["start"] <= r1 + 0.6]
    return min(r1 - SIL_KEEP_IN, (min(ws_) - WORD_IN) if ws_ else 1e9)
if MAX_SIL > 0 and merged:
    squeezed, out = 0, []
    for s, e in merged:
        cur = s
        for r0, r1 in _silent_runs(s, e):
            # (08/09/2026 soir : une règle « mot doux dans le silence » a été essayée ici puis retirée :
            # le « C'est » de Scribe à 160,34 s (ADS2) était un mot MAL DATÉ, sans aucun son avant 161,35 s ;
            # la règle fabriquait un blanc de 0,6 s puis coupait le vrai mot. L'enveloppe fait foi.)
            if r1 - r0 <= MAX_SIL: continue
            co, ci = _cut_out(r0), _cut_in(r1)
            if r0 <= s + 0.02:           # silence en tête de chunk : on rentre dedans
                if ci > cur: cur = max(cur, ci); squeezed += 1
                continue
            if r1 >= e - 0.02:           # silence en queue de chunk : on coupe court
                if co < e: e = co; squeezed += 1
                continue
            if ci - co < 0.10: continue  # rien à gagner une fois les mots respectés
            out.append([round(cur, 3), round(co, 3)])   # pause interne → split
            cur = ci; squeezed += 1
        if e - cur >= 0.05: out.append([round(cur, 3), round(e, 3)])
    # seams : silence résiduel de part et d'autre d'un raccord
    for k in range(1, len(out)):
        tail = _silent_runs(out[k-1][0], out[k-1][1]); head = _silent_runs(out[k][0], out[k][1])
        t_out = (out[k-1][1] - tail[-1][0]) if tail and tail[-1][1] >= out[k-1][1] - 0.02 else 0.0
        t_in = (head[0][1] - out[k][0]) if head and head[0][0] <= out[k][0] + 0.02 else 0.0
        if t_out + t_in > MAX_SIL:
            if t_out > SIL_KEEP_OUT: out[k-1][1] = round(max(_cut_out(tail[-1][0]), out[k-1][1] - (t_out - SIL_KEEP_OUT)), 3)
            if t_in > SIL_KEEP_IN: out[k][0] = round(min(_cut_in(head[0][1]), out[k][0] + (t_in - SIL_KEEP_IN)), 3)
            squeezed += 1
    merged = [[s, e] for s, e in out if e - s >= 0.05]
    print(f"=> blancs: {squeezed} silence(s) > {MAX_SIL}s ramené(s) à {SIL_KEEP_OUT + SIL_KEEP_IN:.2f}s (enveloppe, indépendant de l'ASR)")
# Queues de mots (08/09/2026 soir, ADS3 v7 : coupes à -16/-30 dB juste avant le raccord, encore
# audibles avec la voix compressée). Une sortie de segment n'est valide que quand l'enveloppe
# est retombée à DECAY_DB sous le pic de parole précédent (ou au plancher + 6 dB). Sinon on
# prolonge la sortie jusqu'à ce point (+ 60 ms), sans jamais mordre le mot suivant.
# 30 dB (08/09/2026 soir) : la compression voix (2,5:1 au-dessus de -26 dB) remonte les queues
# par rapport aux pics, le banc mesure ensuite 16 dB sous le pic sur le fichier final ; il faut
# ~26 dB sur le rush pour les tenir. La cible doit être tenue 30 ms de suite (3 hops), pas
# touchée sur un seul hop.
DECAY_DB = float(os.environ.get("DECAY_DB", 30.0))
DECAY_MAX = float(os.environ.get("DECAY_MAX", 0.35))
def _decayed_out(e):
    i = int(e / HOP); lo = max(0, i - 50)
    peak = float(env[lo:i].max()) if i > lo else thr
    target = max(NF_ + 6.0, peak - DECAY_DB)
    # plafond 0,20 s (08/09 soir, client B 006 : à 0,40 s la prolongation créait 6 blancs de 0,4-0,5 s
    # dans un studio silencieux où la voix décroît lentement ; client A n'a besoin que de 50-100 ms)
    # 0,35 s (09/09/2026, ADS6 indoor réverbérant : « grands-parents. », « méritez. » encore à -26 dB pour
    # des pics à -10/-14 au bout de 0,20 s). Le blanc total du raccord reste borné par le re-serrage.
    j, lim = i, min(len(env) - 1, i + int(round(DECAY_MAX / HOP)))
    while j < lim and float(env[max(0, j - 2):j + 1].max()) > target: j += 1
    return j * HOP + 0.06 if j > i else e
if merged:
    moved = 0
    for k, (s, e) in enumerate(merged):
        ne = _decayed_out(e)
        # mot suivant = tout mot dont le MILIEU est après la sortie (08/09/2026 soir) : « car » retiré
        # démarrait pile à la borne (157.46 = e), le filtre start > e+0.02 le sautait et la sortie
        # s'étendait jusqu'à « grâce » -0.05, réavalant le faux départ (ADS3 v11).
        nxt = min([w["start"] for w in words if wmid(w) > e and w["start"] > e - 0.05] or [1e9])
        ne = min(ne, nxt - 0.05)
        if ne > e + 0.005:
            merged[k][1] = round(ne, 3); moved += 1
    if moved: print(f"=> queues de mots : {moved} sortie(s) prolongée(s) jusqu'à -{DECAY_DB:.0f} dB sous le pic")
# Air avant le mot d'entrée (08/09/2026 soir, ADS3 v12) : quand la sortie n'a pas pu décroître
# (mot suivant collé dans le rush : faux départ « t'intéresse car… »), le raccord n'a que le
# silence que seam_hi a laissé avant le mot d'entrée (45 ms). Si le rush est silencieux avant
# ce mot, on recule l'entrée à AIR_IN avant lui : le raccord respire, GATE1 trouve son creux.
AIR_IN = float(os.environ.get("AIR_IN", 0.15))
if AIR_IN > 0 and len(merged) > 1:
    aired = 0
    for k in range(1, len(merged)):
        e, s = merged[k - 1][1], merged[k][0]
        i = int(e / HOP)
        if i < 4: continue
        peak = float(env[max(0, i - 50):i].max()); tail = float(env[i - 3:i].max())
        if tail <= max(NF_ + 6.0, peak - DECAY_DB): continue      # sortie propre
        nxt = min([w["start"] for w in words if wmid(w) > s and w["start"] > s - 0.05] or [1e9])
        if nxt == 1e9: continue
        want = round(nxt - AIR_IN, 3)
        if want >= s - 0.01 or want < e: continue                 # déjà de l'air, ou chevauche le segment précédent
        a_, b_ = int(want / HOP), int(s / HOP)
        if b_ <= a_ or float(env[a_:b_].max()) >= thr: continue    # pas silencieux : on ne réinjecte rien
        merged[k][0] = want; aired += 1
    if aired: print(f"=> air d'entrée : {aired} raccord(s) reculé(s) à {AIR_IN:.2f}s avant le mot suivant (sortie serrée)")
# Re-serrage des raccords (08/09/2026 soir) : après prolongation de sortie et air d'entrée, le
# blanc d'un raccord (silence de fin du segment sortant + silence de tête du segment entrant)
# ne doit pas dépasser MAX_SIL + 0,05. On resserre l'ENTRÉE d'abord (jamais sous 0,05 s avant
# le mot), la sortie prolongée reste (c'est elle qui protège la queue du mot).
if MAX_SIL > 0 and len(merged) > 1:
    tightened = 0
    for k in range(1, len(merged)):
        e, s = merged[k - 1][1], merged[k][0]
        i = int(e / HOP)
        j = i
        while j > 0 and env[j - 1] < thr: j -= 1
        out_sil = max(0.0, e - j * HOP)
        nxt = min([w["start"] for w in words if wmid(w) > s and w["start"] > s - 0.05] or [1e9])
        if nxt == 1e9: continue
        in_sil = max(0.0, nxt - s)
        if out_sil + in_sil <= MAX_SIL + 0.05: continue
        want_in = max(0.05, MAX_SIL + 0.05 - out_sil)
        ns = round(nxt - want_in, 3)
        if ns > s + 0.005 and ns < merged[k][1] - 0.05:
            merged[k][0] = ns; tightened += 1
    if tightened: print(f"=> raccords resserrés : {tightened} entrée(s) rapprochée(s) du mot suivant (blanc > {MAX_SIL + 0.05:.2f}s)")
# Recollage final (09/09/2026, ADS5 client A : trou de 60 ms à 15,37-15,43 s = une coupe visuelle
# pour rien). Les étapes queues de mots / air d'entrée / re-serrage bougent les bornes APRÈS
# le min-gap et les blancs : un trou peut retomber sous FINAL_GLUE = 0,10 s, le gain minimal
# qu'exige l'étape blancs (pas MIN_GAP : les coupes de blancs de 0,10-0,25 s sont voulues, et
# ADS1-3 validées à l'oreille en dépendent). Jamais sur une disfluence retirée.
# Fragment orphelin (09/09/2026, ADS5 client A : « années, | et à | Chaque fois… ») : un bout de
# segment de moins de 0,35 s et d'au plus 2 mots, entre une coupe de pause à gauche et une coupe
# de disfluence/reprise à droite, est le début avorté de la prise reprise. Deux raccords à
# 260 ms d'écart pour deux mots de liaison : on le retire avec la reprise.
FRAG_MAX = float(os.environ.get("FRAG_MAX", 0.35))
if len(merged) > 2 and FRAG_MAX > 0:
    _kept, _dropped = [merged[0]], 0
    for k in range(1, len(merged) - 1):
        s_, e_ = merged[k]
        nw_ = sum(1 for w in words if s_ - 0.02 <= w["start"] < e_)
        left_cut = not protege(merged[k - 1][1], s_)
        right_cut = protege(e_, merged[k + 1][0])
        if e_ - s_ < FRAG_MAX and nw_ <= 2 and left_cut and right_cut:
            _dropped += 1
            print(f"=> fragment orphelin retiré : [{s_:.2f}-{e_:.2f}]s « {' '.join(w['text'] for w in words if s_ - 0.02 <= w['start'] < e_)} » (début avorté avant une reprise)")
            continue
        _kept.append(merged[k])
    _kept.append(merged[-1])
    merged = _kept
FINAL_GLUE = float(os.environ.get("FINAL_GLUE", 0.10))
if len(merged) > 1:
    _re, _out = 0, [merged[0]]
    for s_, e_ in merged[1:]:
        gap = s_ - _out[-1][1]
        if gap < FINAL_GLUE and not protege(_out[-1][1], s_):
            _out[-1][1] = max(_out[-1][1], e_); _re += 1
        else:
            _out.append([s_, e_])
    merged = _out
    if _re: print(f"=> recollage final : {_re} trou(s) < {FINAL_GLUE}s rendu(s) au montage après ajustement des raccords")
# Marge de fin (08/09/2026) : le dernier mot d'une ad finissait 20 à 110 ms avant la fin du
# fichier (coupure sèche). On laisse TAIL_END de rush après le dernier son, si disponible.
TAIL_END = float(os.environ.get("TAIL_END", 0.35))
if merged and TAIL_END > 0:
    lim = len(env) * HOP
    merged[-1][1] = round(min(lim, merged[-1][1] + TAIL_END), 3)
json.dump({"segments": merged, "thr": round(thr, 1), "lead": LEAD, "trail": TRAIL},
          open(OUT_EDL, "w"), indent=1)
print(f"=> {OUT_EDL}: {len(merged)} chunks, {sum(e-s for s,e in merged):.1f}s")

# Reformulation jetée ? (06/09/2026, batch client A 31/08 : hook ADS6-H3 amputé, CTA ADS7
# coupé, punchline ADS7-H2 remplacée). Quand le speaker REFORMULE une phrase entière, elle
# s'aligne comme une grosse insertion, son chunk VAD est ≥ 50 % « disfluence » et la règle
# des chunks le jette en bloc — sans passer par is_retake, qui ne protège que les découpes
# à l'intérieur d'un chunk gardé. Un span ≥ 4 mots retiré SANS preuve de reprise est donc
# suspect : on ne bloque pas (le script batch décide), on le dit fort et on le marque dans
# remove.json ("paraphrase": true). Parade : script batch-local = texte dit (script-check.py).
def _covered(t0, t1):
    return any(s <= t0 + 0.05 and e >= t1 - 0.05 for s, e in merged)
_para = [s for s in remove if s["n"] >= 4 and not is_retake(s) and not _covered(s["t0"], s["t1"])]
for s in _para:
    s["paraphrase"] = True
    print(f"WARN reformulation jetée ? [{s['t0']}-{s['t1']}]s ({s['n']}w) « {s['quote'][:90]} » — aucune reprise détectée : script ≠ dit ? (script-check.py, puis .fix.txt)")
if _para:
    json.dump({"remove": remove, "low": [s for s in all_spans if s['conf'] == 'LOW']},
              open(OUT_REM, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
