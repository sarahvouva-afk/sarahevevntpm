# Environnement du kit (Mac ou PC Windows avec Git Bash) : ffmpeg avec libass, venv python, transcription Whisper locale.
# Usage : source env.sh   (depuis la racine du kit)
KIT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# .venv/bin sur Mac, .venv/Scripts sur Windows
export PATH="$KIT/bin:$KIT/.venv/bin:$KIT/.venv/Scripts:$HOME/.local/node/bin:$PATH"
if [ -x "$KIT/.venv/Scripts/python.exe" ]; then export PYTHON="$KIT/.venv/Scripts/python.exe"; fi
[ -f "$KIT/.env" ] && set -a && . "$KIT/.env" && set +a
# Transcription 100 % locale : pas d'ElevenLabs. Whisper large-v3-turbo via faster-whisper.
export TRANSCRIBER=whisper
export WHISPER_BUDGET_S=86400
