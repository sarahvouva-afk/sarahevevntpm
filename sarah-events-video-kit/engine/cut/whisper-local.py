#!/usr/bin/env python3
"""
Whisper local (faster-whisper) — transcription mot à mot SANS clé API, même format de sortie
que scribe.mjs : {language, text, words:[{text,start,end}]}.

  python whisper-local.py <audio.wav> <out.json> [lang]

Ajouté le 02/10/2026 pour l'auteur : repli quand il n'y a pas de clé ElevenLabs, ou si
TRANSCRIBER=whisper. Limite connue (cf. scribe.mjs) : Whisper lisse une partie des
disfluences, donc quelques reprises peuvent survivre au dérush — Scribe reste préférable.

REPRENABLE : la VM Cowork coupe chaque commande à 180 s et tue les processus de fond. Le
script avance par fenêtres, sauvegarde son état dans <out.json>.partial après chacune, et
s'arrête proprement avant le budget (WHISPER_BUDGET_S, défaut 130 s). Code de sortie 3 =
« pas fini, relance la même commande » ; 0 = terminé, <out.json> écrit.
"""
import json, os, subprocess, sys, time

T0 = time.time()
BUDGET = float(os.environ.get("WHISPER_BUDGET_S", "130"))
WIN = float(os.environ.get("WHISPER_WINDOW_S", "60"))
MARGIN = 4.0  # on ne garde pas les mots des dernières secondes d'une fenêtre (mot coupé)
HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.environ.get("WHISPER_MODEL_DIR") or os.path.join(HERE, "..", "..", ".linux", "models", "large-v3-turbo")
if not os.path.isdir(MODEL):
    MODEL = "large-v3-turbo"  # téléchargé une fois par faster-whisper (~1,6 Go), puis en cache
ISO2 = {"fra": "fr", "eng": "en", "spa": "es", "deu": "de", "ita": "it", "por": "pt", "nld": "nl"}
PROMPT = {"fr": "Euh, donc, euh... je, je veux dire, hum, voilà. On, on reprend. Alors, euh,"}

if len(sys.argv) < 3:
    sys.exit("usage: whisper-local.py <audio> <out.json> [lang]")
audio, out = sys.argv[1], sys.argv[2]
lang = sys.argv[3] if len(sys.argv) > 3 else "fra"
lang = ISO2.get(lang, lang[:2])
part = out + ".partial"

dur = float(subprocess.check_output(
    ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", audio]).decode().strip())
state = {"audio": os.path.abspath(audio), "dur": dur, "t": 0.0, "words": []}
if os.path.exists(part):
    try:
        s = json.load(open(part))
        if s.get("audio") == state["audio"] and abs(s.get("dur", 0) - dur) < 0.05:
            state = s
    except Exception:
        pass

from faster_whisper import WhisperModel
model = WhisperModel(MODEL, device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 4)
load_s = time.time() - T0

last_win = 0.0
while state["t"] < dur - 0.05:
    if time.time() - T0 + max(last_win, 20.0) * 1.15 > BUDGET and last_win > 0:
        break
    w0 = time.time()
    a, b = state["t"], min(state["t"] + WIN, dur)
    final = b >= dur - 0.05
    segs, _ = model.transcribe(
        audio, language=lang, word_timestamps=True, condition_on_previous_text=False,
        beam_size=int(os.environ.get("WHISPER_BEAM", "3")), temperature=0.0,
        initial_prompt=PROMPT.get(lang), clip_timestamps=[a, b], vad_filter=False,
        suppress_blank=True)
    got = []
    for s in segs:
        for w in (s.words or []):
            t = w.word.strip()
            if not t:
                continue
            # Whisper rend « j'aurais » en « j » + « 'aurais », « rendez-vous » en « rendez » + « -vous » : un morceau sans
            # espace devant (ou qui commence par ' ou -) se recolle au mot d'avant, comme Scribe (06/10/2026).
            if got and (not w.word.startswith(" ") or t[0] in "'’-") and not got[-1]["text"].endswith((".", "?", "!", ",")):
                got[-1]["text"] += t
                got[-1]["end"] = round(float(w.end), 3)
                continue
            got.append({"text": t, "start": round(float(w.start), 3), "end": round(float(w.end), 3)})
    if final:
        keep, nxt = got, dur
    else:
        keep = [w for w in got if w["end"] <= b - MARGIN]
        # prochaine fenêtre : juste après le dernier mot gardé (ou avance franche si silence)
        nxt = keep[-1]["end"] if keep else b - MARGIN
        if nxt <= a + 1.0:
            nxt = b - MARGIN
    state["words"].extend(keep)
    state["t"] = nxt
    json.dump(state, open(part, "w"), ensure_ascii=False)
    last_win = time.time() - w0
    print(f"[whisper] {a:7.1f}→{b:7.1f}s  {len(keep):3d} mots  {last_win:5.1f}s", flush=True)

if state["t"] < dur - 0.05:
    print(f"[whisper] PAS FINI : {state['t']:.0f}/{dur:.0f}s transcrits (modèle chargé en {load_s:.0f}s). Relance la même commande.")
    sys.exit(3)

words = state["words"]
json.dump({"language": lang, "text": " ".join(w["text"] for w in words), "words": words},
          open(out, "w"), ensure_ascii=False, indent=1)
try:
    os.replace(part, part + ".done")
except Exception:
    pass
print(f"{len(words)} words -> {out}")
print("TEXT:", " ".join(w["text"] for w in words)[:400])
