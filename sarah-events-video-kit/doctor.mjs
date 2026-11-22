#!/usr/bin/env node
/**
 * doctor — checks everything the kit needs, and tells you exactly what to do when it's missing.
 *
 *   node doctor.mjs
 *
 * Exit code 0 = you can run the engine. 1 = at least one blocking item is missing.
 */
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { readFontNames } from "./engine/lib/font-name.mjs";

const ROOT = dirname(fileURLToPath(import.meta.url));
const isWin = process.platform === "win32";

const results = [];
const add = (ok, label, detail, blocking = true) =>
  results.push({ ok, label, detail, blocking });

function tryRun(bin, argv) {
  try {
    return execFileSync(bin, argv, { stdio: ["ignore", "pipe", "pipe"] }).toString();
  } catch {
    return null;
  }
}

// ── Node ────────────────────────────────────────────────────────────────────────
const nodeMajor = Number(process.versions.node.split(".")[0]);
add(nodeMajor >= 18, "Node 18 ou plus",
  nodeMajor >= 18
    ? `Node ${process.versions.node}`
    : `Node ${process.versions.node} est trop ancien. Installe la version LTS depuis nodejs.org.`);

// ── ffmpeg / ffprobe ────────────────────────────────────────────────────────────
for (const bin of ["ffmpeg", "ffprobe"]) {
  const v = tryRun(bin, ["-version"]);
  add(!!v, bin,
    v
      ? v.split("\n")[0].slice(0, 60)
      : isWin
        ? `${bin} introuvable. Installe-le avec : winget install Gyan.FFmpeg  puis rouvre ton terminal.`
        : `${bin} introuvable. macOS : brew install ffmpeg. Linux : sudo apt install ffmpeg.`);
}

// libass is what burns the subtitles. An ffmpeg build without it fails only at the last step,
// which is the most frustrating moment to discover it.
const cfg = tryRun("ffmpeg", ["-version"]) || "";
add(/--enable-libass/.test(cfg) || /libass/.test(cfg), "ffmpeg compilé avec libass",
  /libass/.test(cfg)
    ? "présent, les sous-titres pourront être incrustés"
    : "ton ffmpeg n'a pas libass, l'incrustation des sous-titres échouera. Prends un build complet (gyan.dev sur Windows, brew sur macOS).",
  false);

// ── Python + numpy/scipy ────────────────────────────────────────────────────────
let py = null;
for (const cand of ["python", "python3", "py"]) {
  if (tryRun(cand, ["--version"])) { py = cand; break; }
}
add(!!py, "Python 3",
  py ? `${py} → ${(tryRun(py, ["--version"]) || "").trim()}`
     : "Python introuvable. Installe-le depuis python.org en cochant « Add to PATH ».");

if (py) {
  for (const mod of ["numpy", "scipy"]) {
    const ok = tryRun(py, ["-c", `import ${mod}`]) !== null;
    add(ok, `Python : ${mod}`,
      ok ? "installé" : `manquant. Lance : ${py} -m pip install ${mod}`);
  }
}

// ── Transcription key ───────────────────────────────────────────────────────────
let brand = {};
try { brand = JSON.parse(readFileSync(join(ROOT, "brand.json"), "utf8")); } catch { /* defaults below */ }
const provider = brand?.transcription?.provider || "scribe";
const keyName = provider === "openai" ? "OPENAI_API_KEY" : "ELEVENLABS_API_KEY";
const key = process.env[keyName];
if (process.env.TRANSCRIBER === "whisper") {
  const ok = py && tryRun(py, ["-c", "import faster_whisper"]) !== null;
  add(!!ok, "Transcription locale (faster-whisper)",
    ok ? "installée, aucune clé payante nécessaire" : `manquante. Lance : ${py || "python"} -m pip install faster-whisper`);
} else add(!!key, `Clé ${keyName}`,
  key
    ? `présente (${key.length} caractères)`
    : provider === "openai"
      ? "absente. Crée une clé sur platform.openai.com puis exporte OPENAI_API_KEY dans ton environnement."
      : "absente. Crée une clé sur elevenlabs.io (le modèle Scribe), puis exporte ELEVENLABS_API_KEY. "
        + "Tu peux aussi passer sur OpenAI en mettant \"provider\": \"openai\" dans brand.json.");

// ── Brand + fonts ───────────────────────────────────────────────────────────────
add(existsSync(join(ROOT, "brand.json")), "brand.json",
  existsSync(join(ROOT, "brand.json")) ? "trouvé" : "absent — le moteur tournera avec la charte par défaut.", false);

const subFile = brand?.subtitles?.file || brand?.fonts?.heading?.file || "fonts/heading.ttf";
const subPath = join(ROOT, subFile);
add(existsSync(subPath), `Police de sous-titres (${subFile})`,
  existsSync(subPath)
    ? "trouvée"
    : `absente. Dépose un fichier .ttf dans fonts/ et renseigne son chemin dans brand.json. `
      + `libass a besoin d'un .ttf, pas d'un .woff2. Voir fonts/README.md.`,
  false);

// The `family` in brand.json must match the name written INSIDE the font file. When it does not,
// libass silently picks another font: the video renders and the subtitles are simply not yours.
// Nothing else in the chain reports it, so the doctor does.
if (existsSync(subPath)) {
  const declared = brand?.subtitles?.family || brand?.fonts?.heading?.family || null;
  try {
    const n = readFontNames(subPath);
    const accepted = [n.family, n.typographic, n.full].filter(Boolean);
    const match = declared && accepted.some((a) => a.toLowerCase() === declared.toLowerCase());
    add(!!match, "Nom interne de la police",
      match
        ? `« ${declared} » correspond au nom écrit dans le fichier`
        : `brand.json déclare « ${declared || "(rien)"} » mais la police s'appelle « ${n.family} ». `
          + `Mets exactement « ${n.family} » dans subtitles.family, sinon libass prendra une autre police sans prévenir.`,
      false);
  } catch (e) {
    add(false, "Nom interne de la police", e.message, false);
  }
}

// ── Report ──────────────────────────────────────────────────────────────────────
const pad = (s, n) => s.padEnd(n);
console.log("\n  Claude Video Kit — diagnostic\n");
for (const r of results) {
  const mark = r.ok ? "  OK  " : r.blocking ? " STOP " : " NOTE ";
  console.log(`${mark} ${pad(r.label, 34)} ${r.detail}`);
}

const blockers = results.filter((r) => !r.ok && r.blocking);
const notes = results.filter((r) => !r.ok && !r.blocking);
console.log("");
if (blockers.length === 0) {
  console.log(notes.length
    ? `  Tu peux lancer le dérush. ${notes.length} point(s) à régler avant le montage complet.\n`
    : "  Tout est en place. Tu peux lancer le dérush et le montage.\n");
} else {
  console.log(`  ${blockers.length} point(s) bloquant(s) à régler avant de lancer quoi que ce soit.\n`);
}
process.exit(blockers.length ? 1 : 0);
