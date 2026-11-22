/**
 * concat — colle des composants (hook + body, body en 2 parties…) en UNE variante, par
 * FILTRE avec ré-encodage, jamais par concat demuxer `-c copy`.
 *   node engine/montage/concat.mjs --out variant.mp4 --brand brand.json part1.mp4 part2.mp4 [...]
 * Pourquoi (08/09/2026, audit client A) : le demuxer `-c copy` perd l'edit list AAC du 2e
 * fichier → +40 à 80 ms d'audio (priming) par raccord, la piste audio dépasse la vidéo et
 * l'image finit figée sur le dernier mot (ADS3-H2 : vidéo 78.300 s / audio 78.378 s).
 * Le filtre concat re-timestampe les deux flux en continu. Contrôle en sortie : durées
 * vidéo et audio égales à 1 image près, sinon exit 3.
 */
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { loadBrand } from "../lib/brand.mjs";
import { vtArgs } from "../lib/encoder.mjs";

const args = process.argv.slice(2);
const flag = (n) => { const i = args.indexOf(`--${n}`); return i !== -1 ? args[i + 1] : undefined; };
const parts = args.filter((a, i) => !a.startsWith("--") && args[i - 1] !== "--out" && args[i - 1] !== "--brand");
const out = flag("out");
if (!out || parts.length < 2) { console.error("usage: concat.mjs --out variant.mp4 [--brand b.json] part1.mp4 part2.mp4 [...]"); process.exit(1); }
const brand = flag("brand") ? loadBrand(flag("brand")) : { render: {} };
const run = (cmd, a) => execFileSync(cmd, a, { stdio: ["ignore", "pipe", "pipe"] }).toString();
const probe = (f, sel, key) => run("ffprobe", ["-v", "error", "-select_streams", sel, "-show_entries", `stream=${key}`, "-of", "csv=p=0", f]).trim();
const fr = probe(parts[0], "v:0", "r_frame_rate");
const [fn, fd] = fr.split("/").map(Number); const fps = fd ? fn / fd : 30;
for (const p of parts) {
  const f = probe(p, "v:0", "r_frame_rate");
  if (f !== fr) { console.error(`[concat] cadence différente : ${p} ${f} vs ${fr}`); process.exit(2); }
}
const inputs = parts.flatMap((p) => ["-i", resolve(p)]);
// Audio de chaque partie calé sur SA durée vidéo (08/09/2026 soir, ADS1-H1) : l'AAC décodé d'un
// composant est 5 à 30 ms plus court (ou long) que sa vidéo (flush encodeur) ; concaténé tel
// quel, l'audio du body démarrait 29 ms trop tôt par rapport à l'image (raccords du body
// jugés « queue de mot coupée » par le banc). apad/atrim à nb_frames/fps, exact.
const vdur = parts.map((p) => { const n = Number(probe(p, "v:0", "nb_frames")); return n > 0 ? n / fps : Number(probe(p, "v:0", "duration")); });
const graph = parts.map((_, i) => `[${i}:a]apad=whole_dur=${vdur[i].toFixed(6)},atrim=end=${vdur[i].toFixed(6)},asetpts=N/SR/TB[a${i}];`).join("")
  + parts.map((_, i) => `[${i}:v][a${i}]`).join("") + `concat=n=${parts.length}:v=1:a=1[v][a]`;
console.log(`[concat] parties (vidéo) : ${vdur.map((d) => d.toFixed(3) + "s").join(" + ")}`);
run("ffmpeg", ["-y", "-loglevel", "error", ...inputs, "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
  "-fps_mode", "cfr", "-r", fr, ...(vtArgs(brand.render) || ["-c:v", "libx264", "-preset", "medium", "-crf", "18"]),
  "-c:a", "aac", "-b:a", "192k", "-ar", "48000", resolve(out)]);
const vd = Number(probe(out, "v:0", "duration")), ad = Number(probe(out, "a:0", "duration"));
const sum = parts.reduce((s, p) => s + Number(probe(p, "v:0", "duration")), 0);
const msg = `vidéo ${vd.toFixed(3)}s / audio ${ad.toFixed(3)}s / somme des parties ${sum.toFixed(3)}s`;
if (Math.abs(vd - ad) > 1.5 / fps || Math.abs(vd - sum) > 1.5 / fps) { console.error(`[concat] A/V FAIL : ${msg}`); process.exit(3); }
console.log(`[concat] ${parts.length} parties → ${out} : A/V OK, ${msg}`);
