/**
 * cut — deterministic talking-head dérush.
 *
 *   node engine/cut/cut.mjs --rush <video> --script <script.txt> --out <cut.mp4>
 *       [--workdir <dir>] [--transcriber scribe|openai] [--scale 1080:1920]
 *       [--lead 0.045] [--trail 0.02] [--lang fra] [--brand brand.json] [--no-verify-content]
 *
 * Defaults come from brand.json (format, transcription provider and language, lead/trail);
 * command-line flags win over the brand file.
 *
 * Pipeline: extract audio -> verbatim transcript (Scribe) -> script-anchored disfluency
 * detection (Needleman-Wunsch) -> boundary-safe cut (VAD chunks + speech-extent trim) ->
 * render -> objective gates (acoustic seams + silence) -> optional content re-check.
 *
 * The MP4 is written before the gates run, then verified. Exit code 0 means GATE1 passed and the
 * file is clean; exit code 2 means the file exists but has a severed seam and must not be shipped.
 * Always read the exit code, never the presence of the file.
 */
import { execSync } from "node:child_process";
import { readFileSync, writeFileSync, mkdirSync, existsSync, unlinkSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve } from "node:path";
import { loadBrand } from "../lib/brand.mjs";
import { vtArgs } from "../lib/encoder.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const A = {};
const av = process.argv.slice(2);
for (let i = 0; i < av.length; i++) {
  if (av[i].startsWith("--")) {
    const k = av[i].slice(2);
    if (av[i + 1] && !av[i + 1].startsWith("--")) { A[k] = av[++i]; } else { A[k] = true; }
  }
}
if (!A.rush || !A.script || !A.out) { console.error("required: --rush --script --out"); process.exit(1); }
const brand = loadBrand(typeof A.brand === "string" ? A.brand : undefined);
let rush = resolve(A.rush);
const script = resolve(A.script), out = resolve(A.out);
const scale = A.scale || brand.scale;
const transcriber = A.transcriber || brand.transcription.provider;
const lang = A.lang || brand.transcription.language;
const work = resolve(A.workdir || join(dirname(out), ".cut-" + Date.now()));
const lead = A.lead || String(brand.cut.lead), trail = A.trail || String(brand.cut.trail);
mkdirSync(work, { recursive: true });
const p = (f) => join(work, f).replace(/\\/g, "/");
const sh = (c) => execSync(c, { stdio: ["ignore", "pipe", "pipe"] }).toString();
const q = (s) => `"${s.replace(/\\/g, "/")}"`;

// Scribe wants ISO-639-2 ("fra"), OpenAI wants ISO-639-1 ("fr").
const ISO2 = { fra: "fr", eng: "en", spa: "es", deu: "de", ita: "it", por: "pt", nld: "nl" };
const lang2 = ISO2[lang] || lang.slice(0, 2);

console.log(`[cut] work=${work} lang=${lang} scale=${scale}`);

// 1bis) normalisation à l'ingest (fix 28/08/2026) : les rushs iPhone rotés en métadonnées
// sont décodés ROTÉS par ffmpeg (espace affiché) mais ffprobe/OpenCV (framing.py YuNet,
// punch-ins) raisonnent en espace STOCKÉ → crop invalide ("Error reinitializing filters")
// ou zoom absurde (vécu 2x sur ads 1.mp4 client A). Les sources 4K paient en plus le
// décodage plein format à chaque passe. Rotation ≠ 0 ou côté long > 1920 → normalisation
// UNIQUE cachée dans le workdir (rotation cuite, plafond 1920, timeline intacte donc
// words.json/EDL inchangés).
{
  const probe = (e) => { try { return sh(`ffprobe -v error -select_streams v:0 -show_entries ${e} -of csv=p=0 ${q(rush)}`).trim(); } catch { return ""; } };
  const rot = Number((probe("side_data=rotation") || probe("stream_tags=rotate") || "0").split("\n").filter(Boolean).pop()) || 0;
  const [w0, h0] = (probe("stream=width,height").split("\n").filter(Boolean).pop() || "0,0").split(",").map(Number);
  // Cadence variable (08/09/2026) : les rushs iPhone sont VFR (avg 29,95 pour 30 nominal).
  // Un trim sur une timeline VFR rend un nombre d'images qui ne correspond pas à la durée
  // audio du segment (±1 image par coupe) : la dérive s'accumule, l'image finit 100 à 300 ms
  // à côté du son en fin d'ad (audit client A 07/09). On normalise TOUJOURS en CFR.
  // csv=p=0 ajoute une virgule de queue quand le flux porte des side data (display matrix d'un
  // rush iPhone roté, 15/09/2026) : « 30/1, » → fps=30/1,, → « No such filter: '' ». On ne garde
  // que les chiffres et la barre.
  const fr_clean = (x) => (x || "").replace(/[^0-9/]/g, "");
  const rfr = fr_clean(probe("stream=r_frame_rate").split("\n").filter(Boolean).pop()) || "30/1";
  const afr = fr_clean(probe("stream=avg_frame_rate").split("\n").filter(Boolean).pop()) || rfr;
  const fr_ = (x) => { const [a, b] = x.split("/").map(Number); return b ? a / b : a; };
  const vfr = Math.abs(fr_(rfr) - fr_(afr)) > 0.001;
  const cfrOk = (f) => { try { const [r, a] = ["r_frame_rate", "avg_frame_rate"].map((k) => sh(`ffprobe -v error -select_streams v:0 -show_entries stream=${k} -of csv=p=0 ${q(f)}`).trim()); return Math.abs(fr_(r) - fr_(a)) <= 0.001; } catch { return false; } };
  // start_time ≠ 0 (08/09/2026 soir) : le trim vidéo compte les images depuis la première
  // décodée ; une vidéo qui démarre à 0,067 s (Honor) ou en négatif (-ss -c copy) décale
  // l'index de 2 à 10 images. La normalisation (fps=) recale la première image à 0.
  const st0 = Number(probe("stream=start_time").split("\n").filter(Boolean).pop() || "0") || 0;
  if (Math.abs(rot) % 180 === 90 || Math.max(w0, h0) > 1920 || vfr || Math.abs(st0) > 0.001) {
    // Un run tué en plein encodage (cap 10 min d'un appel Bash, 06/09/2026) laisse un
    // rush-norm.mp4 sans moov atom que le run suivant reprenait « en cache » puis plantait.
    // Un cache se prouve à la probe, sinon on le refait.
    if (existsSync(p("rush-norm.mp4"))) {
      let d = 0;
      try { d = Number(sh(`ffprobe -v error -show_entries format=duration -of csv=p=0 ${q(p("rush-norm.mp4"))}`).trim()); } catch { d = 0; }
      if (!(d > 0)) { console.log("[cut] ingest: rush-norm.mp4 en cache mais illisible (run précédent tué ?) → refait"); unlinkSync(p("rush-norm.mp4")); }
      else if (!cfrOk(p("rush-norm.mp4"))) { console.log("[cut] ingest: rush-norm.mp4 en cache mais en cadence variable (avant le fix CFR du 08/09) → refait"); unlinkSync(p("rush-norm.mp4")); }
    }
    if (!existsSync(p("rush-norm.mp4"))) {
      console.log(`[cut] ingest: ${w0}x${h0} rot=${rot} ${vfr ? `VFR ${afr}` : "CFR"} start=${st0} → normalisation (rotation cuite, plafond 1920, CFR ${rfr}, départ à 0)`);
      sh(`ffmpeg -loglevel error -i ${q(rush)} -vf "scale=1920:1920:force_original_aspect_ratio=decrease:force_divisible_by=2,fps=${rfr},format=yuv420p" -fps_mode cfr -c:v libx264 -preset fast -crf 18 -c:a copy ${q(p("rush-norm.mp4"))} -y`);
    } else {
      console.log(`[cut] ingest: rush-norm.mp4 en cache`);
    }
    rush = p("rush-norm.mp4");
  }
}

// 1) audio — skipped when already extracted (same workdir), reruns stay cheap
// Timeline (08/09/2026 soir, ADS3 v9) : les rushs iPhone ont des TROUS de timestamps audio
// (13 à 23 ms chacun, 70 à 230 ms cumulés sur 3 min). Une extraction WAV brute colle les
// samples bout à bout, alors que atrim et le trim vidéo suivent les timestamps : l'EDL
// (calculée sur le WAV via Scribe et l'enveloppe) tombait 80 à 130 ms trop tôt dans la
// matière après chaque trou, d'où les queues de mots coupées malgré un detect correct.
// aresample=async=1 comble les trous (silence) : le WAV est sur la timeline du conteneur.
// Un WAV en cache sans le marqueur vient de l'ancienne extraction : on le refait, et le
// words.json (transcrit sur l'ancienne timeline) avec.
// min_hard_comp=0.001 : par défaut aresample ne compense qu'à partir de 0,1 s d'écart cumulé
// (mesuré : 100 ms insérés sur 149 ms de trous, run 2 toujours à -83 ms). À 1 ms : 0 ms partout.
const A16 = "aresample=16000:async=1:min_hard_comp=0.001:first_pts=0";
if (existsSync(p("audio16k.wav"))) {
  let d = 0;
  try { d = Number(sh(`ffprobe -v error -show_entries format=duration -of csv=p=0 ${q(p("audio16k.wav"))}`).trim()); } catch { d = 0; }
  if (!(d > 0)) { console.log("[cut] audio16k.wav en cache mais illisible → refait"); unlinkSync(p("audio16k.wav")); }
  else if (!existsSync(p("audio16k.ts")) || readFileSync(p("audio16k.ts"), "utf8").trim() !== A16) {
    console.log("[cut] audio16k.wav en cache sur l'ancienne timeline (samples) → refait sur la timeline timestamps, words.json re-transcrit");
    unlinkSync(p("audio16k.wav"));
    if (existsSync(p("words.json"))) unlinkSync(p("words.json"));
  }
}
if (!existsSync(p("audio16k.wav"))) {
  if (existsSync(p("words.json"))) console.log("[cut] WARN words.json présent sans audio16k.wav : il doit venir d'une extraction calée timestamps (aresample=async=1) de CE média");
  sh(`ffmpeg -loglevel error -i ${q(rush)} -vn -af "${A16}" -ac 1 -c:a pcm_s16le ${q(p("audio16k.wav"))} -y`);
  writeFileSync(p("audio16k.ts"), A16 + "\n");
}

// 2) verbatim transcript — cached: a re-run after a detect/render tweak must not re-pay Scribe
if (existsSync(p("words.json"))) {
  console.log(`[cut] transcribe: words.json already in workdir, skipping`);
} else if (transcriber === "scribe") {
  console.log(`[cut] transcribe (${transcriber})`);
  sh(`node ${q(join(HERE, "scribe.mjs"))} ${q(p("audio16k.wav"))} ${q(p("words.json"))} ${lang}`);
} else {
  console.log(`[cut] transcribe (${transcriber})`);
  sh(`node ${q(join(HERE, "transcribe-openai.mjs"))} ${q(p("audio16k.wav"))} --language ${lang2} --out ${q(p("words.json"))}`);
}

// Warnings à lire AVANT montage (06/09/2026) : ne changent pas le code de sortie (les
// scripts batch en `|| fail` restent valides), mais un cut avec warning ne va pas au montage.
const warnings = [];

// 3) detect + EDL — ou EDL fournie via --edl (édition manuelle après un défaut
// d'alignement, ex. répétition légitime avalée) : detect est sauté, tout le reste
// (snap, punch-ins, render, GATEs) s'applique normalement.
if (typeof A.edl === "string") {
  console.log(`[cut] EDL fournie (${A.edl}) — detect sauté`);
  writeFileSync(p("keep.edl.json"), readFileSync(resolve(A.edl), "utf8"));
} else {
  console.log(`[cut] detect disfluences (LEAD=${lead} TRAIL=${trail})`);
  process.env.LEAD = lead; process.env.TRAIL = trail;
  process.env.MAX_PAUSE = String(brand.cut.maxPause ?? 0.40);
  // Blancs / bords (08/09/2026) : réglables par client dans brand.cut, un env déjà posé par
  // l'appelant gagne (ex. TAIL_END=0.05 pour un hook qui sera collé devant un body).
  // Raccords (09/09/2026) : réglables par client. client A (rushs réverbérants, mots courts avalés) = défauts ;
  // client B (studio silencieux, voix qui décroît lentement) garde decayMax 0,20 / entryAir 0,045 dans son brand,
  // sinon +8 blancs de 0,40-0,48 s sur 3 min (non-régression 006 du 09/09).
  const cutEnv = { MAX_SIL: brand.cut.maxSilence ?? 0.30, SIL_KEEP_OUT: brand.cut.keepOut ?? 0.12, SIL_KEEP_IN: brand.cut.keepIn ?? 0.08, TAIL_END: brand.cut.tailEnd ?? 0.35,
    DECAY_MAX: brand.cut.decayMax ?? 0.35, ENTRY_AIR: brand.cut.entryAir ?? 0.08, FINAL_GLUE: brand.cut.finalGlue ?? 0.10, FRAG_MAX: brand.cut.fragMax ?? 0.35, MIN_GAP: brand.cut.minGap ?? 0.25 };
  for (const [k, v] of Object.entries(cutEnv)) if (process.env[k] === undefined) process.env[k] = String(v);
  console.log(`[cut] blancs: maxSilence=${process.env.MAX_SIL}s keepOut=${process.env.SIL_KEEP_OUT}s keepIn=${process.env.SIL_KEEP_IN}s tailEnd=${process.env.TAIL_END}s`);
  const detOut = sh(`python ${q(join(HERE, "detect.py"))} ${q(p("words.json"))} ${q(script)} ${q(p("audio16k.wav"))} ${q(p("keep.edl.json"))} ${q(p("remove.json"))}`).trim();
  console.log(detOut);
  warnings.push(...detOut.split("\n").filter((l) => l.startsWith("WARN")));
}

// 4) render (interleaved trim+concat, 10ms join fades, scale)
// Snap every boundary to the frame grid: video trim snaps to frames while atrim is
// sample-exact, and the per-segment duration mismatch accumulates into a real A/V seam
// drift (±180ms observed on 39 segments) that breaks GATE1's seam positions.
const fpsRaw = sh(`ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of csv=p=0 ${q(rush)}`).trim();
const [fn, fd] = fpsRaw.split("/").map(Number);
const FPS = fd ? fn / fd : (fn || 30);
const edl = JSON.parse(readFileSync(p("keep.edl.json"), "utf8"));
const snap = (t) => Math.round(t * FPS) / FPS;
edl.segments = edl.segments
  .map(([a, b]) => [snap(a), snap(b)])
  .filter(([a, b]) => b - a >= 1 / FPS);
writeFileSync(p("keep.edl.json"), JSON.stringify(edl, null, 1));
const segments = edl.segments;

// Punch-ins (brand.montage.punchIn) — two kinds of zoom, like the reference ads:
//   long chunks (>= progMin s) get a slow continuous push-in (zoompan, supersampled 4x
//   before panning: zoompan's integer x/y rounding at slow rates reads as turbulence,
//   working 4x over the output grid kills it);
//   short chunks alternate hard static punch-ins (plain crop, no zoompan) and no zoom,
//   so every seam still reads as a deliberate jump cut.
const PI = { enabled: false, base: 1.05, rate: 0.025, max: 1.15, hard: 1.08, progMin: 2.0, punchMin: 1.2, faceY: 0.35, ...(brand.montage.punchIn || {}) };
const dimsRaw = sh(`ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 ${q(rush)}`).trim();
let [SW, SH] = dimsRaw.split(",").map(Number);

// Face-aware reframe (brand.montage.autoFrame): find the speaker (YuNet) and crop to the
// target aspect with their EYES on the upper-third line, instead of a blind centre crop.
// Falls back silently to no reframe when no face is found.
const AF = { enabled: false, faceline: 0.33, ...(brand.montage.autoFrame || {}) };
let frameCrop = "";
if (AF.enabled) {
  try {
    const fr = JSON.parse(sh(
      `python ${q(join(HERE, "framing.py"))} ${q(rush)} ${brand.format.replace(":", ":")} --faceline ${AF.faceline}`
    ).trim().split("\n").pop());
    if (fr.crop) {
      frameCrop = `,crop=${fr.crop}`;
      const [cw, ch] = fr.crop.split(":").map(Number);
      SW = cw; SH = ch;
      console.log(`[cut] autoFrame: crop=${fr.crop} (eyes @${fr.eye_y}px, ${fr.detected} samples)`);
    }
  } catch { console.log("[cut] autoFrame: no face found, keeping full frame"); }
}
const hardChain = (z) => {
  const cw = Math.floor(SW / z / 2) * 2, ch = Math.floor(SH / z / 2) * 2;
  const cx = Math.round((SW - cw) / 2), cy = Math.round((SH - ch) * PI.faceY);
  return `,crop=${cw}:${ch}:${cx}:${cy},scale=${SW}:${SH}:flags=lanczos`;
};
const progChain = (base) =>
  `,scale=${SW * 4}:${SH * 4}:flags=lanczos` +
  `,zoompan=z='min(${base}+${PI.rate}*in/${FPS.toFixed(3)},${PI.max})'` +
  `:x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*${PI.faceY}':d=1:s=${SW}x${SH}:fps=${FPS.toFixed(3)}`;

// Visual rhythm: a speaker who talks non-stop yields few real (audio) cuts, and the edit
// feels static. Chunks longer than punchIn.cutEvery get extra VIDEO-ONLY jump cuts (the
// framing changes, the audio runs through untouched) — video and audio are concatenated
// as separate streams, so the virtual splits never touch a seam the gates verified.
const CUT_EVERY = PI.enabled && PI.cutEvery !== 0 ? (PI.cutEvery || 3.0) : Infinity;
// Aimantation (08/09/2026 soir) : un saut virtuel posé à intervalle fixe tombait en plein mot
// (« clique », ADS3 v11) ; on le déplace sur le trou entre deux mots le plus proche (±0,6 s,
// jamais à moins de 0,5 s des bords du chunk). Les mots sont ceux du rush (même timeline).
let VW = [];
try { const wj = JSON.parse(readFileSync(p("words.json"), "utf8")); VW = Array.isArray(wj) ? wj : (wj.words || []); } catch {}
const GAPS = [];
for (let i = 0; i + 1 < VW.length; i++) { const g0 = Number(VW[i].end), g1 = Number(VW[i + 1].start); if (g1 > g0) GAPS.push([g0, g1]); }
let vsnap = 0, vfree = 0;
const snapGap = (t, a, b) => {
  let best = null;
  for (const [g0, g1] of GAPS) {
    const m = (g0 + g1) / 2;
    if (m <= a + 0.5 || m >= b - 0.5) continue;
    const d = Math.abs(m - t);
    if (d <= 0.6 && (!best || d < best.d)) best = { d, m };
  }
  if (best) { vsnap++; return snap(best.m); }
  vfree++; return snap(t);
};
const vsegs = [];
for (const [a, b] of segments) {
  const n = Math.max(1, Math.round((b - a) / CUT_EVERY));
  let s = a;
  for (let k = 0; k < n; k++) {
    const e = k === n - 1 ? b : snapGap(a + ((b - a) * (k + 1)) / n, a, b);
    if (e - s < 1 / FPS) continue;
    vsegs.push([s, e]); s = e;
  }
  if (vsegs.length && vsegs[vsegs.length - 1][1] < b) vsegs[vsegs.length - 1][1] = b;
}
if (vsnap + vfree) console.log(`[cut] sauts virtuels : ${vsnap} aimanté(s) sur un trou entre mots, ${vfree} sans trou à ±0,6 s`);
// Plan de zoom par vseg : le rythme de base alterne par parité (comme avant), MAIS une
// grosse ellipse source (fix 28/08/2026, seam qui saute > 3 s de rush : faux départ long,
// prise refaite) exige un DELTA de zoom franc au raccord — la posture du speaker change,
// un raccord à cadrage quasi identique se lit comme un accroc (« truc chelou », client A
// ~20 s). Deux plans progressifs voisins peuvent finir/démarrer à 0.01 près : dans ce cas
// le plan qui suit l'ellipse passe en punch sec à l'opposé de l'état de sortie précédent.
const plans = [];
let zoff = 0;   // rephasage de l'alternance après un raccord forcé
for (let i = 0; i < vsegs.length; i++) {
  const [a, b] = vsegs[i];
  const dur = b - a;
  const mk = (eff) => {
    const prog = PI.enabled && dur >= PI.progMin;
    const z0 = !PI.enabled ? 1.0 : prog ? (eff ? PI.base : 1.0) : (eff ? PI.hard : 1.0);
    return { a, b, prog, z0, z1: prog ? Math.min(z0 + PI.rate * dur, PI.max) : z0 };
  };
  let P = mk((i + zoff) % 2);
  const Q = plans[i - 1];
  // Plancher de punch : sous punchMin, un plan n'a pas le temps d'exister. Lui donner son
  // propre état de zoom fait pomper l'image (client A ADS2 31/08 : 9 punchs alternés en 8 s,
  // dont un chunk de 0.20 s). Le plan court hérite de l'état de sortie du précédent, et
  // l'alternance n'est pas consommée : le plan suivant prend la phase qu'il aurait eue.
  if (Q && PI.enabled && dur < PI.punchMin) {
    P = { a, b, prog: false, z0: Q.z1, z1: Q.z1 };
    zoff -= 1;
    plans.push(P);
    continue;
  }
  if (Q && PI.enabled && a - Q.b > 3.0 && Math.abs(P.z0 - Q.z1) < 0.05) {
    // Raccord plat après une grosse ellipse : punch sec à l'opposé de l'état de sortie
    // précédent, puis l'alternance des plans suivants repart de ce nouvel état.
    const wide = Q.z1 >= 1.05;
    const z = wide ? 1.0 : Math.max(PI.hard, 1.10);
    P = { a, b, prog: false, z0: z, z1: z };
    zoff = wide ? i % 2 : (i + 1) % 2;
  }
  plans.push(P);
}
// Raccords de prise : quand l'ellipse source dépasse retakeGap, le speaker a rebougé entre
// les deux prises et la coupe franche se lit comme un accroc, même avec un delta de zoom.
// On fond les deux plans sur retakeFade. Le fondu se paie en PROLONGEANT le plan sortant
// dans le trou (il y a des secondes de rush disponibles là), jamais en rognant le suivant :
// la durée vidéo totale reste identique à la somme des plans, donc l'audio (concat franc,
// intact) ne dérive pas d'une frame. retakeFade=0 rétablit la coupe franche partout.
// ⚠ COÛT MÉMOIRE — défaut à 0 (coupe franche) depuis le 31/08/2026. xfade réclame la tête
// du run suivant pendant qu'il sort la queue du précédent ; comme les deux viennent de
// points très éloignés du même rush, ffmpeg tamponne tout l'intervalle en frames brutes :
// ~20 Go sur 2 min de 1440x2560, SIGKILL sur une machine 16 Go. Donner un décodeur -ss par
// run ne sauve rien, N décodeurs coûtent plus que 1. Pour le réactiver il faudra rendre
// chaque run dans un fichier temporaire puis fondre les fichiers en seconde passe.
// Le delta de zoom au raccord (règle plus bas, ellipse > 3 s) reste la parade en place.
const RETAKE_GAP = 3.0;
const FADE = Math.max(0, Math.round((brand.cut.retakeFade ?? 0) * FPS) / FPS);
const joins = [];   // index i => fondu entre plans[i-1] et plans[i]
if (FADE > 0) {
  for (let i = 1; i < plans.length; i++) {
    if (plans[i].a - plans[i - 1].b > RETAKE_GAP) joins.push(i);
  }
}
const vend = plans.map((P) => P.b);
for (const i of joins) vend[i - 1] = Math.min(plans[i - 1].b + FADE, plans[i].a - 0.02);

// Un "run" = suite de plans raccordés franchement ; les runs se rejoignent en xfade.
const runs = [];
if (joins.length) {
  let cur = [];
  plans.forEach((P, i) => {
    if (joins.includes(i) && cur.length) { runs.push(cur); cur = []; }
    cur.push(i);
  });
  runs.push(cur);
}
// UN DÉCODEUR PAR RUN, sinon OOM (SIGKILL observé sur ADS4 le 31/08/2026). Avec une seule
// entrée, le décodeur unique alimente les ~25 branches trim en même temps ; concat les
// consomme dans l'ordre du décodage donc rien ne s'accumule, mais xfade réclame la tête du
// run k+1 pendant qu'il sort la queue du run k. Le décodeur ne peut pas se mettre en pause
// pour une seule branche, alors les frames des runs suivants s'entassent : ~20 Go de frames
// brutes sur 2 min de 1440x2560. Une entrée -ss par run rend la contre-pression de ffmpeg
// effective run par run. L'entrée 0 reste sans -ss : elle ne sert qu'à l'audio.
const runStart = runs.map((r) => plans[r[0]].a);
const vsrc = (i) => {
  if (!runs.length) return { idx: 0, off: 0 };
  const k = runs.findIndex((r) => r.includes(i));
  return { idx: k + 1, off: runStart[k] };
};
const inputArgs = [`-i ${q(rush)}`]
  // -ss une demi-image AVANT le début du run (08/09/2026 soir) : le seek précis jette les
  // images de pts < -ss, et l'EDL arrondie à 3 décimales (113.467) dépasse le pts de l'image
  // (113.4667) → la première image du run était la suivante (+33 ms). L'index start_frame
  // reste relatif au début nominal du run.
  .concat(runStart.map((s) => `-ss ${(s - 0.5 / FPS).toFixed(4)} -i ${q(rush)}`))
  .join(" ");

let g = "";
const vlab = [], alab = [];
plans.forEach((P, i) => {
  const zoom = !PI.enabled || !SW || !SH ? "" : P.prog ? progChain(P.z0) : P.z0 > 1.001 ? hardChain(P.z0) : "";
  const { idx, off } = vsrc(i);
  // trim par INDEX d'image (08/09/2026) : sur une source CFR, start_frame/end_frame rend
  // exactement round(dur*FPS) images, donc la même durée que l'atrim audio du segment.
  g += `[${idx}:v]trim=start_frame=${Math.round((P.a - off) * FPS)}:end_frame=${Math.round((vend[i] - off) * FPS)},setpts=PTS-STARTPTS${frameCrop}${zoom}[v${i}];`;
  vlab.push(`[v${i}]`);
});
segments.forEach(([a, b], i) => {
  // Trous de paquets AAC À L'INTÉRIEUR d'un segment gardé (09/09/2026, ADS6 client A : 32 ms à
  // 12,1-12,3 s dans un segment de 4,4 s) : atrim suit les timestamps mais ne comble pas le
  // trou, les samples sont collés → l'audio du segment sort plus court que sa vidéo et tout
  // l'audio suivant joue en avance (37 ms mesurés jusqu'à la fin du cut). Même filtre que le
  // WAV d'analyse (A16 sans le 16000) : le cut est sample-aligné sur audio16k.wav.
  g += `[0:a]aresample=async=1:min_hard_comp=0.001:first_pts=0,atrim=${a.toFixed(3)}:${b.toFixed(3)},asetpts=PTS-STARTPTS,afade=t=in:st=0:d=0.010,afade=t=out:st=${Math.max(0, b - a - 0.010).toFixed(3)}:d=0.010[a${i}];`;
  alab.push(`[a${i}]`);
});
if (joins.length === 0) {
  g += vlab.join("") + `concat=n=${vsegs.length}:v=1:a=0[vc];`;
} else {
  const runDur = runs.map((r) => r.reduce((s, i) => s + (vend[i] - plans[i].a), 0));
  // xfade refuse deux entrées de timebases différentes ("main timebase do not match"), et
  // concat sort en 1/1000000 quand une branche brute reste en 1/15360. On normalise chaque
  // run avant le fondu. fps= est un no-op ici (même cadence que la source), il ne sert qu'à
  // caler la timebase.
  const NORM = `fps=${FPS.toFixed(3)},settb=AVTB,format=yuv420p`;
  runs.forEach((r, k) => {
    if (r.length === 1) { g += `[v${r[0]}]${NORM}[r${k}];`; return; }
    g += r.map((i) => `[v${i}]`).join("") + `concat=n=${r.length}:v=1:a=0,${NORM}[r${k}];`;
  });
  let acc = "[r0]", accDur = runDur[0];
  for (let k = 1; k < runs.length; k++) {
    const lab = k === runs.length - 1 ? "[vc]" : `[x${k}]`;
    g += `${acc}[r${k}]xfade=transition=fade:duration=${FADE.toFixed(3)}:offset=${(accDur - FADE).toFixed(3)}${lab};`;
    acc = lab; accDur += runDur[k] - FADE;
  }
}
g += alab.join("") + `concat=n=${segments.length}:v=0:a=1[ac];`;
g += `[vc]scale=${scale}:flags=lanczos[vout]`;
console.log(`[cut] visual cuts: ${vsegs.length} plans (${vsegs.length - segments.length} virtual) from ${segments.length} chunks, ${joins.length} fondus de raccord (${(FADE * 1000).toFixed(0)} ms)`);
writeFileSync(p("fg.txt"), g);
console.log(`[cut] render ${segments.length} chunks -> ${out}`);
const VENC = (vtArgs(brand.render) || ["-c:v", "libx264", "-preset", "medium", "-crf", "18"]).join(" ");
sh(`ffmpeg -loglevel error ${inputArgs} -/filter_complex ${q(p("fg.txt"))} -map "[vout]" -map "[ac]" -fps_mode cfr -r ${FPS.toFixed(3)} ${VENC} -c:a aac -b:a 160k ${q(out)} -y`);

// GATE3 (08/09/2026) : la piste vidéo et la piste audio du cut ont la même durée à 1 image
// près, sinon l'image dérive par rapport au son à chaque coupe (audit client A 07/09 :
// +33 ms par coupe, 200 ms en fin d'ad, dernier mot sur image figée). Bloquant.
{
  const pr = (sel) => Number(sh(`ffprobe -v error -select_streams ${sel} -show_entries stream=duration -of csv=p=0 ${q(out)}`).trim()) || 0;
  const vd = pr("v:0"), ad = pr("a:0"), edlSum = segments.reduce((s, [a, b]) => s + (b - a), 0);
  const nfr = Number(sh(`ffprobe -v error -select_streams v:0 -count_packets -show_entries stream=nb_read_packets -of csv=p=0 ${q(out)}`).trim()) || 0;
  const want = Math.round(edlSum * FPS);
  const msg = `video ${vd.toFixed(3)}s (${nfr} images, attendu ${want}) / audio ${ad.toFixed(3)}s / EDL ${edlSum.toFixed(3)}s`;
  // Tolérance audio/vidéo : une trame AAC (21,3 ms) + arrondi, pas 1,5 image (50 ms laissaient
  // passer les 26 ms manquants d'ADS6, 09/09/2026).
  if (Math.abs(vd - ad) > 0.030 || Math.abs(nfr - want) > 1) {
    console.log(`GATE3 FAIL A/V : ${msg}`);
    process.exit(3);
  }
  console.log(`GATE3 PASS A/V : ${msg}`);
}

// 5) objective gates
sh(`ffmpeg -loglevel error -i ${q(out)} -vn -ac 1 -ar 16000 ${q(p("cut.wav"))} -y`);
console.log("[cut] verify (acoustic seams + silence):");
let gate1ok = true;
try {
  console.log(sh(`python ${q(join(HERE, "verify.py"))} ${q(p("cut.wav"))} ${q(p("keep.edl.json"))} ${q(p("audio16k.wav"))}`).trim());
} catch (e) {
  gate1ok = false;
  console.log((e.stdout ? e.stdout.toString() : "") + (e.stderr ? e.stderr.toString() : ""));
}

// 6) content re-check (re-transcribe output, expect no "--" disfluency markers)
if (!A["no-verify-content"] && transcriber === "scribe") {
  try {
    sh(`node ${q(join(HERE, "scribe.mjs"))} ${q(p("cut.wav"))} ${q(p("cut.words.json"))} ${lang}`);
    const w = JSON.parse(readFileSync(p("cut.words.json"), "utf8")).words;
    const marks = w.filter((x) => /--/.test(x.text)).length;
    console.log(`[cut] content gate: Scribe '--' markers in output = ${marks} ${marks === 0 ? "(clean)" : "(RESIDUAL DISFLUENCY!)"}`);
    // Fin de script présente dans le cut ? Une fenêtre de hook trop courte (ADS4-H2 06/09,
    // « et moins ça marche » perdu) ou un CTA reformulé jeté (ADS7 31/08) finissent ici.
    const tk = (s) => String(s).toLowerCase().split(/[\s'’\-]+/).map((x) => x.replace(/[^a-zàâäéèêëîïôöùûüç0-9]/g, "")).filter(Boolean);
    const sTail = tk(readFileSync(script, "utf8")).slice(-3);
    const cTail = tk(w.map((x) => x.text).join(" ")).slice(-8);
    if (sTail.length && !sTail.some((x) => cTail.includes(x)))
      warnings.push(`WARN fin de script absente du cut : script finit par « ${sTail.join(" ")} », le cut par « ${cTail.slice(-4).join(" ")} » (fenêtre trop courte ? CTA reformulé ?)`);
  } catch { console.log("[cut] content gate skipped (scribe error)"); }
}
for (const wl of warnings) console.log(`[cut] ${wl}`);
if (warnings.length) console.log(`[cut] ${warnings.length} warning(s) à lire avant montage — un cut avec warning ne va pas au montage.`);
console.log(gate1ok ? "[cut] DONE — cut verified." : "[cut] WARNING — GATE1 failed, cut has severed seams.");
process.exit(gate1ok ? 0 : 2);
