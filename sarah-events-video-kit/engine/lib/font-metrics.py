"""Sidecar de métriques pour le layout ASS exact de gen-subs.mjs.

    .venv/bin/python3 engine/lib/font-metrics.py fonts/Baloo2-800.ttf

Écrit fonts/Baloo2-800.metrics.json : unitsPerEm, ascender/descender (hhea) et
l'avance de chaque caractère mappé (latin + ponctuation + €). gen-subs s'en sert
pour poser chaque mot à sa position définitive au pixel près (le rendu fantôme
pré-affiche toute la carte : une largeur estimée à l'œil décale tout le layout).
"""
import json
import sys
from pathlib import Path

from fontTools.ttLib import TTFont

if len(sys.argv) != 2:
    sys.exit("usage: font-metrics.py <font.ttf>")
src = Path(sys.argv[1])
font = TTFont(src)
upm = font["head"].unitsPerEm
cmap = font.getBestCmap()
hmtx = font["hmtx"]

from fontTools.pens.boundsPen import BoundsPen

glyph_set = font.getGlyphSet()
advances = {}
bounds = {}
for code, gname in cmap.items():
    if code > 0x2500 and code != 0x20AC:  # latin étendu + € suffisent
        continue
    ch = chr(code)
    advances[ch] = hmtx[gname][0]
    pen = BoundsPen(glyph_set)
    glyph_set[gname].draw(pen)
    if pen.bounds is not None:
        # xMin / xMax de l'encre : permet à gen-subs d'espacer les mots par leurs bords
        # d'encre réels (gap visuel constant) au lieu des chasses typographiques.
        bounds[ch] = [round(pen.bounds[0]), round(pen.bounds[2])]

out = {
    "unitsPerEm": upm,
    "ascender": font["hhea"].ascender,
    "descender": font["hhea"].descender,
    # libass (comme VSFilter) mappe \fs sur la hauteur de cellule usWinAscent+usWinDescent,
    # pas sur l'em : gen-subs s'en sert pour convertir une taille em voulue en \fs réel.
    "winAscent": font["OS/2"].usWinAscent,
    "winDescent": font["OS/2"].usWinDescent,
    "advances": advances,
    "bounds": bounds,
}
dst = src.with_suffix(".metrics.json")
dst.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
print(f"{dst.name}: {len(advances)} caractères, upm={upm}")
