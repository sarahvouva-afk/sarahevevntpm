# Claude Video Kit

Tu donnes ton rush et ton script à Claude Code. Tu récupères un montage coupé au mot près,
sous-titré, à ta charte.

C'est le moteur qui monte mes reels. Pas une démo, pas une version allégée. Le même.

> **Commence par ouvrir `GUIDE.html`** dans ton navigateur.
> C'est le parcours complet en images, de l'installation à ton premier montage, en trente minutes.
> Le fichier que tu lis là est la référence, pas le point de départ.

---

## Ce que ça fait

**Le dérush.** Il enlève les silences et surtout **toutes tes reprises**. Quand tu refais une
phrase trois fois, il garde la dernière et supprime les deux autres. Il ne coupe jamais au milieu
d'un mot, et il le vérifie tout seul avant de te rendre le fichier.

Sur mon dernier reel : 187 secondes de rush, 67 secondes de vidéo propre. Aucune reprise oubliée.

**Le montage.** Sous-titres mot à mot avec le mot actif dans ta couleur d'accent, moitié haute
animée si tu fais du split-screen, assemblage et normalisation du son.

Ça marche en vertical (9:16) et en horizontal (16:9).

---

## Ce que ça n'est pas

Ce n'est pas une IA qui décide à ta place ce qui est intéressant dans ton rush. Claude ne regarde
jamais l'image. Il travaille sur du texte et de l'audio, il exécute un pipeline, et il vérifie
chaque étape. C'est exactement pour ça que le résultat ne change pas d'une fois sur l'autre.

Tu gardes deux décisions : ce que tu dis, et ce qu'on voit à l'écran.

---

## Prérequis

- **Claude Code** installé
- **Node 18** ou plus
- **ffmpeg** compilé avec libass (pour incruster les sous-titres)
- **Python 3** avec `numpy` et `scipy`
- Une clé de transcription : **ElevenLabs** (recommandé) ou **OpenAI**

Tu n'as rien à vérifier à la main :

```bash
node doctor.mjs
```

Il te dit ce qui manque et la commande exacte pour l'installer. Détails dans `INSTALL.md`.

---

## Les 3 étapes

### 1. Diagnostic

```bash
node doctor.mjs
```

Tant qu'il reste une ligne `STOP`, rien ne tournera. Règle-les, relance.

### 2. Personnalise le kit

Ce que tu viens de télécharger est générique. Il porte mes réglages, mon rythme, mon type de
contenu. Cette étape le rend tien, une fois pour toutes.

Ouvre Claude Code dans ce dossier et dis-lui :

> Personnalise le kit.

Il t'interroge sur ce que tu filmes, où tu publies, ta charte, tes sous-titres, ton rythme et les
mots que la transcription écorche. Puis il réécrit le kit d'après tes réponses : ta charte, tes
réglages de coupe, la composition animée, et jusqu'à la façon dont il choisira quoi afficher à
l'écran dans tes montages.

Compte une quinzaine de minutes. Tu ne le refais jamais. Le détail est dans `PERSONNALISER.md`,
et tes décisions sont consignées dans `PERSONNALISATION.md` à la fin.

Dépose tes polices dans `fonts/` avant de commencer (voir `fonts/README.md`, libass a besoin de
fichiers `.ttf` ou `.otf`).

### 3. Ton montage

Dépose ton rush et le texte que tu comptais dire, puis dans Claude Code :

> Monte ma vidéo : le rush est dans `mon-rush.mp4`, le script dans `mon-script.txt`.

Claude charge la bonne skill et exécute. Ou en direct, sans passer par lui :

```bash
node engine/cut/cut.mjs --rush mon-rush.mp4 --script mon-script.txt --out cut.mp4
node engine/montage/gen-subs.mjs .cut-*/words.json subs.ass
node engine/montage/assemble.mjs --cut cut.mp4 --subs subs.ass --out final.mp4
```

---

## Le script, à quoi il sert

Le fichier `script.txt`, c'est **ce que tu avais prévu de dire**. Pas la transcription de ce que tu
as dit. C'est la différence entre les deux qui permet de repérer tes reprises : ce qui dépasse du
script prévu est une hésitation, donc ça saute.

Tu n'as pas besoin d'avoir suivi ton script au mot près. Il sert de point d'ancrage, pas de contrat.

---

## Comment c'est fait

Quatre décisions qui expliquent pourquoi ça tient.

1. **La transcription garde les hésitations.** La plupart des moteurs les nettoient, ce qui efface
   la preuve de tes reprises. Celui-ci les garde et les marque.
2. **On aligne, on ne juge pas.** Le moteur ne se demande jamais si une phrase était bien dite. Il
   aligne ce que tu as dit sur ce que tu avais prévu, et un mot aligné sur un trou est une reprise.
3. **La coupe tombe toujours dans du silence.** Le seuil de silence est calibré sur ton fichier,
   pas sur une valeur générique qui échoue dès que ton micro souffle un peu.
4. **La vérification est acoustique, jamais textuelle.** Re-transcrire le résultat ne sert à rien :
   la reconnaissance vocale répare mentalement les mots à moitié coupés et déclare que tout va bien.
   Le moteur mesure l'énergie du signal à chaque raccord.

---

## Structure

```
GUIDE.html          le guide d'installation en images, à ouvrir en premier
PERSONNALISER.md    l'entretien qui adapte le kit à toi, à lancer en premier
brand.json          ta charte, écrite par l'entretien, éditable à la main ensuite
doctor.mjs          diagnostic des prérequis
engine/cut/         le dérush
engine/montage/     sous-titres et assemblage
engine/lib/         lecture de la charte, lecture du nom interne d'une police
fonts/              tes polices
.claude/skills/     les trois skills que Claude charge tout seul
```
