/**
 * Fallback transcriber — OpenAI word-level timestamps instead of ElevenLabs Scribe.
 * Emits the same JSON shape the rest of the engine expects: { language, text, words[] }.
 *
 *   node transcribe-openai.mjs <video> [--language fr] [--out words.json]
 *
 * Trade-off: OpenAI smooths over part of the disfluencies, so a few retakes survive the cut.
 * Scribe stays the default for that reason.
 */
import { execSync } from "node:child_process";
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const argv = process.argv.slice(2);
const video = argv.find((a) => !a.startsWith("--"));
const flag = (n, d) => {
  const i = argv.indexOf(`--${n}`);
  return i === -1 ? d : argv[i + 1];
};
if (!video) {
  console.error("usage: node transcribe-openai.mjs <video> [--language fr] [--out words.json]");
  process.exit(1);
}
const language = flag("language", "fr");
const out = flag("out", video.replace(/\.[^.]+$/, "") + ".words.json");

// Key from the environment, falling back to a .env sitting next to the kit.
// Never parse a .env by hand beyond this: an inline comment or a quoted value breaks naive parsers.
function readKey() {
  if (process.env.OPENAI_API_KEY) return process.env.OPENAI_API_KEY.trim();
  const candidates = [
    join(process.cwd(), ".env"),
    fileURLToPath(new URL("../../.env", import.meta.url)),
  ];
  for (const f of candidates) {
    try {
      const m = readFileSync(f, "utf8").match(/^\s*OPENAI_API_KEY\s*=\s*(.*)$/m);
      if (m) {
        const v = m[1].split("#")[0].trim().replace(/^["']|["']$/g, "");
        if (v) return v;
      }
    } catch { /* next candidate */ }
  }
  return null;
}
const key = readKey();
if (!key) {
  console.error("OPENAI_API_KEY introuvable. Exporte-la dans ton environnement, ou mets-la dans un fichier .env à la racine du kit. Lance `node doctor.mjs` pour vérifier.");
  process.exit(1);
}

const td = mkdtempSync(join(tmpdir(), "tx-"));
const wav = join(td, "a.wav");
execSync(`ffmpeg -y -loglevel error -i "${video}" -vn -ac 1 -ar 16000 -c:a pcm_s16le "${wav}"`);

const fd = new FormData();
fd.append("file", new Blob([readFileSync(wav)], { type: "audio/wav" }), "a.wav");
fd.append("model", "whisper-1");
fd.append("language", language);
fd.append("response_format", "verbose_json");
fd.append("timestamp_granularities[]", "word");

const res = await fetch("https://api.openai.com/v1/audio/transcriptions", {
  method: "POST",
  headers: { Authorization: `Bearer ${key}` },
  body: fd,
});
rmSync(td, { recursive: true, force: true });
if (!res.ok) { console.error(`OpenAI error ${res.status}: ${(await res.text()).slice(0, 400)}`); process.exit(1); }

const j = await res.json();
const words = (j.words || [])
  .map((w) => ({ text: w.word, start: w.start, end: w.end }))
  .filter((w) => w.text && w.text.trim());

writeFileSync(out, JSON.stringify({ language: j.language, text: j.text || "", words }, null, 1), "utf8");
console.log(`${words.length} words -> ${out}`);
