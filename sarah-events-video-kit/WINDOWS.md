# Installation sur PC Windows

Claude fait ces étapes à ta place, en te demandant ton accord avant chaque logiciel.
Les commandes tournent dans Git Bash (installé avec Claude Code), depuis la racine du kit.

1. **Node 18+** : `node --version`. Sinon : `winget install OpenJS.NodeJS.LTS`
2. **ffmpeg complet (avec libass)** : `winget install Gyan.FFmpeg`
3. **Python 3** : `winget install Python.Python.3.12`
4. Fermer et rouvrir l'appli Claude (sinon ffmpeg et python restent introuvables).
5. **Environnement Python** :
   ```bash
   python -m venv .venv
   .venv/Scripts/python.exe -m pip install numpy scipy faster-whisper
   ```
6. **Vérifier** : `source env.sh && node doctor.mjs` → zéro ligne STOP.
   Le premier dérush télécharge une fois le modèle Whisper (~1,6 Go), ensuite tout reste sur le PC.
7. **Police Playfair Display** (avec accord) : depuis Google Fonts, en `.ttf`, dans `fonts/`.

Problèmes fréquents : « ffmpeg introuvable » ou « python introuvable » → rouvrir l'appli Claude.
Si `python` ouvre le Microsoft Store : Paramètres > Applications > Alias d'exécution, désactiver « python.exe ».
