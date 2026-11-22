# Installation

> Si tu préfères suivre le parcours en images, ouvre `GUIDE.html` dans ton navigateur.
> Ce fichier-ci est la même chose en texte, avec un peu plus de détail sur les cas particuliers.

Compte quinze à trente minutes la première fois. Ensuite tu n'y reviens plus.

Lance `node doctor.mjs` après chaque étape. Il te dit exactement où tu en es.

---

## 1. Node

Vérifie :

```bash
node --version
```

S'il te faut l'installer, prends la version LTS sur [nodejs.org](https://nodejs.org).
Il faut au moins la 18.

---

## 2. ffmpeg

C'est lui qui découpe, assemble et incruste. **Prends un build complet**, avec libass : sans lui
tout marche jusqu'aux sous-titres, qui échouent au dernier moment.

**Windows**

```powershell
winget install Gyan.FFmpeg
```

Ferme ton terminal et rouvre-le, sinon `ffmpeg` reste introuvable.

**macOS**

```bash
brew install ffmpeg
```

**Linux**

```bash
sudo apt install ffmpeg
```

Vérifie :

```bash
ffmpeg -version
```

---

## 3. Python et deux librairies

La détection du silence et la vérification des raccords tournent en Python.

```bash
python --version
python -m pip install numpy scipy
```

Sur Windows, si `python` n'est pas reconnu, réinstalle Python depuis
[python.org](https://python.org) **en cochant « Add python.exe to PATH »** sur le premier écran.
C'est l'erreur la plus fréquente.

Sur macOS et Linux, remplace `python` par `python3` si besoin.

---

## 4. La clé de transcription

Deux options, ElevenLabs par défaut.

### ElevenLabs (recommandé)

Crée un compte sur [elevenlabs.io](https://elevenlabs.io) et génère une clé API. Le modèle utilisé
est Scribe. Il est payant à l'usage, mais transcrire un rush coûte quelques centimes, et c'est le
seul qui garde les hésitations, ce dont le moteur a besoin pour repérer tes reprises.

**Windows (PowerShell, permanent)**

```powershell
setx ELEVENLABS_API_KEY "ta-cle"
```

Rouvre ton terminal après.

**macOS et Linux**

Ajoute à ton `~/.zshrc` ou `~/.bashrc` :

```bash
export ELEVENLABS_API_KEY="ta-cle"
```

### OpenAI (repli)

Si tu as déjà une clé OpenAI, mets `"provider": "openai"` dans la section `transcription` de
`brand.json` et exporte `OPENAI_API_KEY` de la même façon.

À savoir : la transcription OpenAI nettoie une partie des hésitations, donc quelques reprises
passeront à travers. Le dérush reste bon, il est juste moins exhaustif.

---

## 5. Tes polices

Dépose tes fichiers de police dans `fonts/`. **libass ne lit que des `.ttf` ou `.otf`**, pas des
`.woff2`.

L'entretien de personnalisation (étape 7) lit le nom de tes polices tout seul. Si tu veux le faire
à la main :

```bash
node engine/lib/font-name.mjs fonts/heading.ttf
```

Recopie la ligne qu'il affiche. Ce nom est celui écrit **dans** le fichier de police, il n'a
souvent rien à voir avec le nom du fichier, et c'est le seul que libass sait chercher.

Tu peux sauter cette étape pour commencer : le dérush n'a pas besoin de police, seuls les
sous-titres en ont besoin.

---

## 6. Vérifie tout

```bash
node doctor.mjs
```

Tu veux zéro ligne `STOP`. Les lignes `NOTE` ne bloquent que le montage, pas le dérush.

## 7. Personnalise le kit

Dernière étape avant de monter quoi que ce soit. Ouvre Claude Code dans ce dossier :

> Personnalise le kit.

Il t'interroge et réécrit le kit à ta main. Détail dans `PERSONNALISER.md`.

Ton premier vrai montage sert aussi de test d'installation : si le dérush va au bout et affiche
`DONE — cut verified` en dernière ligne, toute la chaîne fonctionne chez toi. Si quelque chose
casse, laisse Claude Code lire l'erreur, elle nomme la pièce en cause.

---

## Quand ça coince

**« ffmpeg n'est pas reconnu »** — tu n'as pas rouvert ton terminal après l'installation.

**« ModuleNotFoundError: numpy »** — tu as plusieurs Python sur la machine. Installe avec le même
que celui qui répond : `python -m pip install numpy scipy`.

**Les sous-titres ne s'affichent pas dans la vidéo finale** — ton ffmpeg n'a pas libass, ou ta
police est un `.woff2`. Le doctor te le dit.

**Les sous-titres s'affichent mais dans une autre police que la tienne** — le `family` de
`brand.json` ne correspond pas au nom interne du fichier, donc libass en a pris une autre sans
prévenir. Lance `node doctor.mjs`, il compare les deux et te donne le bon nom.

**« GATE1 failed »** — le moteur a coupé au milieu d'un mot et te prévient au lieu de te livrer un
fichier bancal. Le plus souvent, ton `script.txt` est trop éloigné de ce que tu as réellement dit.
Rapproche-le et relance.

**La transcription échoue** — vérifie que ta clé est bien dans l'environnement du terminal où tu
lances la commande (`echo $ELEVENLABS_API_KEY`, ou `echo $env:ELEVENLABS_API_KEY` sur PowerShell).
