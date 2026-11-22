# Mots clés en bleu clair des sous-titres « version 3 » (l'auteur, 13/10/2026). À partir du --dump de gen-subs
# (segments + mots), construit la carte --emphasis {"<segment>": [indices de mots]} pour une liste de mots clés.
# Un mot clé = un mot (ou le début d'un mot) du reel ; au plus un segment sur trois en bleu pour que ça reste rare.
import json, re, sys, unicodedata
norm = lambda s: re.sub(r"[^a-z0-9%€'-]+", "", unicodedata.normalize("NFD", s.lower()).encode("ascii", "ignore").decode())
def carte(dump, mots):
    cles = [norm(m) for m in mots]; out = {}; dernier = -9
    for seg in dump:
        idx = [k for k, w in enumerate(seg["words"]) if norm(w) in cles]
        if idx and seg["i"] - dernier >= 3:
            out[str(seg["i"])] = idx; dernier = seg["i"]
    return out
if __name__ == "__main__":
    dump = json.load(open(sys.argv[1])); json.dump(carte(dump, sys.argv[3].split(",")), open(sys.argv[2], "w"))
