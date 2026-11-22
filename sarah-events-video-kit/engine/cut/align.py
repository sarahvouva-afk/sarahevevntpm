#!/usr/bin/env python3
"""
ALIGNEMENT FORCÉ des mots de Whisper sur le son (06/10/2026, l'auteur : « pas d'ElevenLabs »).

Whisper écrit le bon texte, mais ses horaires de mots sont flous (0,1 à 0,3 s d'écart, petits mots à durée nulle) : un dérush
au mot près coupe alors à côté (« justement », « du coup » restaient dans le son). Ici on garde le TEXTE de Whisper et on
recalcule début et fin de chaque mot avec le modèle d'alignement MMS de Meta (torchaudio, MMS_FA), par fenêtres d'environ 30 s.
Résultat : des horaires de la précision de Scribe, sans clé ni service extérieur.

  .venv-align/bin/python engine/cut/align.py <audio> <mots.json> [sortie.json]     (sortie par défaut : réécrit mots.json)

Environnement séparé `.venv-align` (torch 2.2.2 + torchaudio 2.2.2 + numpy<2 : derniers paquets pour Mac Intel).
Le modèle (~1,2 Go) est téléchargé une fois dans ~/.cache/torch. Un mot sans lettre (« 18h » → « h », « 100 ») garde
au besoin les horaires de Whisper, bornés par ses voisins.
"""
import sys, json, re, unicodedata, subprocess
import numpy as np
import torch, torchaudio

audio, src = sys.argv[1], sys.argv[2]
dst = sys.argv[3] if len(sys.argv) > 3 else src
SR = 16000
data = json.load(open(src))
words = data["words"]

x = np.frombuffer(subprocess.check_output(["ffmpeg", "-v", "error", "-i", audio, "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"]), np.int16)
wav = torch.from_numpy(x.astype(np.float32) / 32768).unsqueeze(0)
DUR = wav.shape[1] / SR

B = torchaudio.pipelines.MMS_FA
model = B.get_model(with_star=False).eval()
DIC = B.get_dict(star=None)
tokenizer, aligner = B.get_tokenizer(), B.get_aligner()
CHIF = {"0": "zero", "1": "un", "2": "deux", "3": "trois", "4": "quatre", "5": "cinq", "6": "six", "7": "sept", "8": "huit", "9": "neuf"}

def norm(t):
    t = unicodedata.normalize("NFD", t.lower()).encode("ascii", "ignore").decode()
    t = re.sub(r"\d", lambda m: CHIF[m[0]], t)
    t = t.replace("’", "'")
    return "".join(c for c in t if c in DIC and c != "-")

# fenêtres : on coupe la suite de mots aux plus grands blancs de Whisper, ~30 s au plus
groups, cur = [], []
for i, w in enumerate(words):
    if cur and (w["start"] - words[cur[0]]["start"] > 30 or (w["start"] - words[cur[-1]]["end"] > 1.2 and w["start"] - words[cur[0]]["start"] > 12)):
        groups.append(cur); cur = []
    cur.append(i)
if cur: groups.append(cur)

new = [None] * len(words)
for g in groups:
    a = max(0.0, words[g[0]]["start"] - 0.6)
    b = min(DUR, words[g[-1]]["end"] + 0.6)
    ok = [i for i in g if norm(words[i]["text"])]
    if not ok: continue
    seg = wav[:, int(a * SR):int(b * SR)]
    with torch.inference_mode():
        em, _ = model(seg)
    ratio = seg.shape[1] / SR / em.shape[1]
    try:
        spans = aligner(em[0], tokenizer([norm(words[i]["text"]) for i in ok]))
    except Exception as e:
        print(f"[align] fenêtre {a:.1f}-{b:.1f} s non alignée ({e}) : horaires Whisper gardés", file=sys.stderr); continue
    for i, sp in zip(ok, spans):
        new[i] = (round(a + sp[0].start * ratio, 3), round(a + sp[-1].end * ratio, 3))

moved = []
for i, w in enumerate(words):
    if new[i]:
        moved.append(abs(new[i][0] - w["start"])); w["start"], w["end"] = new[i]
for i, w in enumerate(words):            # mots sans lettre : bornés par les voisins alignés
    if not new[i]:
        lo = words[i - 1]["end"] if i else 0.0
        hi = words[i + 1]["start"] if i + 1 < len(words) else DUR
        w["start"] = round(min(max(w["start"], lo), hi), 3); w["end"] = round(min(max(w["end"], w["start"] + 0.02), hi), 3)
data["words"] = words
data["aligned"] = "mms_fa"
json.dump(data, open(dst, "w"), ensure_ascii=False, indent=1)
print(f"[align] {sum(1 for n in new if n)}/{len(words)} mots alignés, écart médian avec Whisper {np.median(moved) if moved else 0:.3f} s -> {dst}")
