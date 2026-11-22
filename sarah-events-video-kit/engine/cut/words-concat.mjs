/**
 * words-concat — words.json d'une variante par DÉCALAGE, zéro re-Scribe (perf, 28/08/2026).
 *
 *   node words-concat.mjs --out variant.words.json <words.json:media.mp4> [<words.json:media.mp4> …]
 *
 * Une variante = concat de composants (hook + body). Chaque composant a déjà son
 * transcript (hook = tranche du transcript rush ou mini-cut ; body = cut.words.json du
 * content gate). Le transcript de la variante s'obtient en décalant chaque partie de la
 * durée cumulée des médias précédents — même audio, mêmes mots, timings exacts.
 * Bonus fiabilité : le body est transcrit UNE fois, donc identique dans toutes les
 * variantes (fini la variance Scribe entre H1/H2/H3 sur le même audio).
 * Le couple se parse par la DROITE (les noms de fichiers peuvent contenir des ':').
 */
import { readFileSync, writeFileSync } from "node:fs";
import { execSync } from "node:child_process";

const args = process.argv.slice(2);
const oi = args.indexOf("--out");
if (oi === -1 || args.length < 3) {
  console.error("usage: node words-concat.mjs --out variant.words.json <words.json:media.mp4> [...]");
  process.exit(1);
}
const out = args[oi + 1];
const parts = args.filter((_, i) => i !== oi && i !== oi + 1);

const dur = (media) => parseFloat(execSync(
  `ffprobe -v error -show_entries format=duration -of csv=p=0 "${media}"`,
  { stdio: ["ignore", "pipe", "pipe"] }).toString().trim());

let offset = 0;
const words = [];
let lang = null, texts = [];
for (const part of parts) {
  const cut = part.lastIndexOf(":");
  if (cut === -1) { console.error(`words-concat: partie invalide "${part}" (attendu words.json:media)`); process.exit(1); }
  const wp = part.slice(0, cut), mp = part.slice(cut + 1);
  const j = JSON.parse(readFileSync(wp, "utf8"));
  lang = lang || j.language;
  texts.push(j.text || "");
  for (const w of j.words)
    words.push({ text: w.text, start: +(w.start + offset).toFixed(3), end: +(w.end + offset).toFixed(3) });
  const d = dur(mp);
  console.log(`[words-concat] ${wp}: ${j.words.length} mots, +${offset.toFixed(2)}s (média ${d.toFixed(2)}s)`);
  offset += d;
}
writeFileSync(out, JSON.stringify({ language: lang, text: texts.join(" "), words }, null, 1));
console.log(`[words-concat] ${words.length} mots -> ${out} (durée totale ${offset.toFixed(2)}s)`);
