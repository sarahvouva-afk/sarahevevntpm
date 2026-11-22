# Tes polices

Ce dossier est vide exprès. Les polices que j'utilise sont sous licence, je ne peux pas les
redistribuer. Tu mets les tiennes.

## Ce qu'il faut savoir

**libass ne lit que du `.ttf` ou du `.otf`.** Si tu n'as qu'un `.woff2`, convertis-le, sinon les
sous-titres ne s'afficheront pas et ffmpeg ne te dira pas clairement pourquoi.

```bash
pip install fonttools brotli
python -c "from fontTools.ttLib import TTFont; f=TTFont('ma-police.woff2'); f.flavor=None; f.save('ma-police.ttf')"
```

## Comment faire

1. Dépose tes fichiers ici, par exemple `heading.ttf` et `body.ttf`.
2. Renseigne-les dans `brand.json` :

```json
"fonts": {
  "heading": { "family": "Le Nom Exact De La Police", "file": "fonts/heading.ttf" },
  "body":    { "family": "Le Nom Exact De La Police", "file": "fonts/body.ttf" }
}
```

**Le `family` doit être le nom interne de la police, pas le nom du fichier.** C'est ce nom que
libass cherche. Le kit le lit pour toi, sans rien à installer :

```bash
node engine/lib/font-name.mjs fonts/heading.ttf
```

Il t'affiche la ligne exacte à recopier dans `brand.json`. Et si tu te trompes quand même,
`node doctor.mjs` compare ce que tu as écrit avec ce qu'il y a dans le fichier et te le dit.

C'est le piège le plus coûteux du kit : quand le nom ne correspond pas, libass ne plante pas,
il prend une autre police. La vidéo sort, les sous-titres ne ressemblent simplement pas à ta charte.

## Où trouver des polices gratuites

- [Fontshare](https://fontshare.com) — gratuites, y compris en usage commercial
- [Google Fonts](https://fonts.google.com) — le bouton de téléchargement donne des `.ttf`

Pour des sous-titres, prends un caractère épais. Les graisses fines deviennent illisibles sur une
vidéo qu'on regarde au téléphone.
