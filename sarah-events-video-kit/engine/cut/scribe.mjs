/**
 * ElevenLabs Scribe v1 — deterministic verbatim word-level transcription.
 * Keeps disfluences (repeats/false starts) that whisper cleans. Key from env.
 *   ELEVENLABS_API_KEY=... node scribe.mjs <audio> <out.json> [lang]
 */
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// Repli local OPT-IN (02/10/2026, l'auteur) : TRANSCRIBER=whisper → faster-whisper via
// whisper-local.py, même format de sortie. Reprenable (code 3 = relancer la même commande).
// Non utilisable dans la VM Cowork (modèle trop lent à charger) : prévu pour un run natif.
if (process.env.TRANSCRIBER === "whisper") {
  const py = join(dirname(fileURLToPath(import.meta.url)), "whisper-local.py");
  const r = spawnSync(process.env.PYTHON || (process.platform === "win32" ? "python" : "python3"), [py, ...process.argv.slice(2)], { stdio: "inherit" });
  if (r.status !== 0) process.exit(r.status ?? 1);
  // 06/10/2026 : les horaires de mots de Whisper sont flous (0,1 à 0,3 s) ; alignement forcé MMS (engine/cut/align.py,
  // environnement .venv-align) pour retrouver la précision de Scribe. Absent → horaires de Whisper, avec un avertissement.
  const kit = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
  const apy = process.platform === "win32" ? join(kit, ".venv-align", "Scripts", "python.exe") : join(kit, ".venv-align", "bin", "python");
  if (existsSync(apy) && process.env.ALIGN !== "0") {
    const a = spawnSync(apy, [join(kit, "engine", "cut", "align.py"), process.argv[2], process.argv[3] || "scribe.words.json"], { stdio: ["ignore", "inherit", "pipe"] });
    if (a.status !== 0) { console.error("[align] échec : horaires Whisper gardés\n" + String(a.stderr).slice(-600)); }
  } else console.error("[align] .venv-align absent : horaires Whisper bruts (moins précis pour le dérush)");
  process.exit(0);
}

const KEY = process.env.ELEVENLABS_API_KEY;
if (!KEY) { console.error("ELEVENLABS_API_KEY missing in env"); process.exit(1); }
const audio = process.argv[2], out = process.argv[3] || "scribe.words.json";
const lang = process.argv[4] || "fra";

const fd = new FormData();
fd.append("file", new Blob([readFileSync(audio)], { type: "audio/wav" }), "a.wav");
fd.append("model_id", "scribe_v1");
fd.append("timestamps_granularity", "word");
fd.append("language_code", lang);
fd.append("diarize", "false");

const r = await fetch("https://api.elevenlabs.io/v1/speech-to-text", {
  method: "POST", headers: { "xi-api-key": KEY }, body: fd,
});
if (!r.ok) { console.error(`Scribe ${r.status}: ${(await r.text()).slice(0, 300)}`); process.exit(1); }
const j = await r.json();
const words = (j.words || [])
  .filter(w => (w.type || "word") === "word" && w.text && w.text.trim())
  .map(w => ({ text: w.text, start: w.start, end: w.end }));
writeFileSync(out, JSON.stringify({ language: j.language_code, text: j.text || "", words }, null, 1));
console.log(`${words.length} words -> ${out}`);
console.log("TEXT:", (j.text || "").slice(0, 400));
