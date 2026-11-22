/**
 * Final assembly — burns subtitles, normalises the voice, and (in split mode) composites
 * an animated top half above the face cam with a soft junction fade.
 *
 *   node engine/montage/assemble.mjs --cut cut.mp4 --out final.mp4 [--subs subs.ass]
 *                                    [--top top.mp4] [--mode split|plain] [--brand brand.json]
 *                                    [--broll "file:start:end"]...
 *
 * plain  : the cut fills the frame. Works in 9:16 and 16:9. Subtitles optional.
 * split  : top.mp4 (brand.montage.topHeight tall) sits above the face cam, whose top edge
 *          fades into the background over junctionHeight pixels. 9:16 only.
 * broll  : overlays an asset from clients/<c>/broll/ between start and end (seconds, on the
 *          CUT's timeline) — inserted before the subtitle chain, so always behind the subs
 *          and in front of the video; the voice and audio are never touched. Repeatable.
 *          .mp4/.mov = full-frame cutaway (looped if shorter than the window, centre-cropped
 *          to the brand format) ; .jpg/.png/.webp = still with a light Ken Burns zoom.
 *          The asset's own audio is ignored. Times are parsed from the RIGHT, so file names
 *          may contain spaces (never ":").
 * card   : --card "file:start:end[:y]" (15/09/2026, demande un client : « les résultats au
 *          milieu/en haut de l'écran sans prendre toute la place, avec une animation »).
 *          A still (screenshot de preuve, commentaire Instagram, témoignage) posé en CARTE :
 *          mise à l'échelle dans une boîte 78 % W × 46 % H (ratio gardé, jamais recadrée),
 *          centrée en X, haut de carte à y (défaut 150 px sur 1920), coins arrondis, ombre
 *          portée, entrée 280 ms (fondu + glissement −80 px, ease-out), sortie 200 ms fondu.
 *          Derrière les sous-titres, devant la vidéo et les b-rolls ; l'audio n'est pas touché.
 *
 * Why alphamerge + overlay and never maskedmerge: maskedmerge drags the whole filter graph
 * into gray and half-blends chroma through the mask's neutral planes — the output comes out
 * black and white. This cost a full render cycle to find; do not "simplify" it back.
 */
import { execFileSync, execSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { loadBrand, packPath } from "../lib/brand.mjs";
import { vtArgs } from "../lib/encoder.mjs";

const args = process.argv.slice(2);
const opt = (name, fallback = null) => {
  const i = args.indexOf(`--${name}`);
  return i !== -1 && args[i + 1] && !args[i + 1].startsWith("--") ? args[i + 1] : fallback;
};
const optAll = (name) => {
  const out = [];
  for (let i = 0; i < args.length; i++) {
    if (args[i] === `--${name}` && args[i + 1] && !args[i + 1].startsWith("--")) out.push(args[i + 1]);
  }
  return out;
};

const cut = opt("cut");
const out = opt("out");
const subs = opt("subs");
const top = opt("top");
const mode = opt("mode", top ? "split" : "plain");
const brand = loadBrand(opt("brand"));

if (!cut || !out) {
  console.error("usage: node assemble.mjs --cut <cut.mp4> --out <final.mp4> [--subs subs.ass] [--top top.mp4] [--mode split|plain] [--broll \"file:start:end\"]... [--card \"file:start:end[:y]\"]...");
  process.exit(1);
}
if (!existsSync(cut)) { console.error(`assemble: cut not found — ${cut}`); process.exit(1); }
if (mode === "split") {
  if (!top) { console.error("assemble: --mode split needs --top"); process.exit(1); }
  if (!existsSync(top)) { console.error(`assemble: top not found — ${top}`); process.exit(1); }
  if (brand.format !== "9:16") { console.error(`assemble: split mode is 9:16 only (brand.format = ${brand.format})`); process.exit(1); }
}

// B-roll overlays — "file:start:end", times in seconds on the cut's timeline, parsed from
// the right so the file part may contain spaces. Two kinds by extension: video = full-frame
// cutaway (fond), still = labelled insert with a light Ken Burns. The one-fond-per-ad and
// 30-45s placement rules live in the video-montage skill, not here.
const STILL_EXT = /\.(jpe?g|png|webp)$/i;
const VIDEO_EXT = /\.(mp4|mov|m4v|webm)$/i;
const BROLLS = optAll("broll").map((spec) => {
  const parts = spec.split(":");
  if (parts.length < 3) { console.error(`assemble: --broll needs "file:start:end" — ${spec}`); process.exit(1); }
  const end = parseFloat(parts.pop());
  const start = parseFloat(parts.pop());
  const file = parts.join(":");
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start) {
    console.error(`assemble: --broll invalid window (need 0 <= start < end, seconds) — ${spec}`); process.exit(1);
  }
  if (!existsSync(file)) { console.error(`assemble: broll not found — ${file}`); process.exit(1); }
  const still = STILL_EXT.test(file);
  if (!still && !VIDEO_EXT.test(file)) {
    console.error(`assemble: broll extension not supported (video mp4/mov/m4v/webm or still jpg/png/webp) — ${file}`);
    process.exit(1);
  }
  const dur = end - start;
  if (dur > 8 || dur < 1) console.warn(`assemble: ⚠ broll window ${dur.toFixed(2)}s hors des 1-8s recommandés — ${file}`);
  return { file, start, end, still };
});

// Cartes preuve — "file:start:end[:y]" (y optionnel = haut de carte en px, défaut CARD.y).
const CARDS = optAll("card").map((spec) => {
  const parts = spec.split(":");
  if (parts.length < 3) { console.error(`assemble: --card needs "file:start:end[:y]" — ${spec}`); process.exit(1); }
  let y = null;
  // 4 champs numériques à droite = y présent ; sinon 3 (file peut contenir ":" ? non — jamais)
  if (parts.length >= 4 && /^\d+(\.\d+)?$/.test(parts[parts.length - 1]) && /^\d+(\.\d+)?$/.test(parts[parts.length - 2]) && /^\d+(\.\d+)?$/.test(parts[parts.length - 3])) {
    y = parseFloat(parts.pop());
  }
  const end = parseFloat(parts.pop());
  const start = parseFloat(parts.pop());
  const file = parts.join(":");
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start) {
    console.error(`assemble: --card invalid window (need 0 <= start < end, seconds) — ${spec}`); process.exit(1);
  }
  if (!existsSync(file)) { console.error(`assemble: card not found — ${file}`); process.exit(1); }
  if (!STILL_EXT.test(file)) { console.error(`assemble: card must be a still (jpg/png/webp) — ${file}`); process.exit(1); }
  return { file, start, end, y };
});

const { width: W, height: H } = brand;
const BG = brand.colors.background;
const M = brand.montage;
const A = brand.audio;

/** ffmpeg filter arguments need ":" and "\" escaped, and Windows paths use both. */
const filterPath = (p) => resolve(p).replace(/\\/g, "/").replace(/:/g, "\\:").replace(/'/g, "\\'");

const subsChain = subs && existsSync(subs)
  ? `,ass='${filterPath(subs)}':fontsdir='${filterPath(brand.subtitles.fontsDir)}'`
  : "";

// Étalonnage léger par client (brand.grade) — appliqué SOUS les sous-titres (le texte reste
// pur). Deux formes : une LUT .cube (grade.lut, chemin relatif au kit) OU des corrections
// douces eq/colortemperature. Jamais agressif : c'est de la retouche d'ambiance, pas un look.
const G = brand.grade || {};
let gradeChain = "";
if (G.lut) {
  const lutPath = packPath(G.lut);
  if (!existsSync(lutPath)) { console.error(`assemble: grade.lut introuvable — ${lutPath}`); process.exit(1); }
  gradeChain = `,lut3d='${filterPath(lutPath)}'`;
} else if (G.enabled) {
  const eq = [];
  if (G.contrast != null) eq.push(`contrast=${G.contrast}`);
  if (G.saturation != null) eq.push(`saturation=${G.saturation}`);
  if (G.brightness != null) eq.push(`brightness=${G.brightness}`);
  if (eq.length) gradeChain += `,eq=${eq.join(":")}`;
  if (G.temperature != null) gradeChain += `,colortemperature=temperature=${G.temperature}`;
}
if (gradeChain) console.log(`[assemble] grade: ${G.lut ? `LUT ${G.lut}` : gradeChain.slice(1)}`);
if (subs && !existsSync(subs)) console.warn(`assemble: subtitles file not found, continuing without — ${subs}`);

const work = mkdtempSync(join(tmpdir(), "cvk-assemble-"));
const run = (bin, argv) => execFileSync(bin, argv, { stdio: ["ignore", "pipe", "pipe"] }).toString();

// Conditional pace-up (--pace-words cut.words.json): measure the spoken rate of the CUT and
// speed the whole finished ad up ONLY if it is slow — never touch a normal delivery. Applied
// after the subtitles are burned, so everything stays in sync; atempo keeps the pitch.
// Thresholds overridable via brand.pace = { slowWpm, verySlowWpm, factor, maxFactor }.
let SPEED = 1;
const paceWords = opt("pace-words");
if (paceWords) {
  if (!existsSync(paceWords)) {
    console.warn(`assemble: --pace-words file not found, pace check skipped — ${paceWords}`);
  } else {
    const P = { slowWpm: 150, verySlowWpm: 138, factor: 1.05, maxFactor: 1.1, ...(brand.pace || {}) };
    const wj = JSON.parse(readFileSync(paceWords, "utf8"));
    const n = wj.words.filter((w) => (w.type === undefined || w.type === "word") && typeof w.start === "number").length;
    const dur = parseFloat(run("ffprobe", [
      "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", resolve(cut),
    ]).trim());
    const wpm = n / (dur / 60);
    SPEED = wpm < P.verySlowWpm ? P.maxFactor : wpm < P.slowWpm ? P.factor : 1;
    console.log(`[assemble] pace: ${Math.round(wpm)} mots/min → ${SPEED === 1 ? "vitesse normale" : `x${SPEED} (ad trop lente)`}`);
  }
}
const FPS_OUT = SPEED !== 1 || BROLLS.length || CARDS.length
  ? run("ffprobe", ["-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate", "-of", "default=nw=1:nk=1", resolve(cut)]).trim()
  : null;
const TAIL = Number(opt("tail") ?? (brand.render && brand.render.tail) ?? 0.25);   // s de queue (image tenue + silence)
const CUT_VDUR = Number(run("ffprobe", ["-v", "error", "-select_streams", "v:0", "-show_entries", "stream=duration", "-of", "csv=p=0", resolve(cut)]).trim()) || 0;
const speedV = SPEED !== 1 ? `,setpts=PTS/${SPEED},fps=${FPS_OUT}` : "";
const speedA = SPEED !== 1 ? `atempo=${SPEED},` : "";

// B-roll filter branches + overlay chain. Inputs are appended after the base inputs; only
// their video is used (the cut's audio always runs through untouched). Each overlay uses
// eof_action=pass + enable=between so the base video simply resumes outside the window.
const KB_ZOOM = 0.07; // Ken Burns: 1.0 → 1.07 over the still's window
const brollInputs = [];
let brollGraph = "";
let brollFinal = null;
if (BROLLS.length) {
  const [fn, fd] = FPS_OUT.split("/").map(Number);
  const fpsNum = fn / (fd || 1);
  const baseIdx = mode === "split" ? 3 : 1;
  BROLLS.forEach((b, k) => {
    const D = +(b.end - b.start).toFixed(3);
    let branch;
    if (b.still) {
      // Single-frame input expanded by zoompan; fed at 2x the brand size so the zoom
      // has real pixels to eat (zoompan on a same-size input visibly stair-steps).
      brollInputs.push("-i", b.file);
      const frames = Math.max(1, Math.round(D * fpsNum));
      branch =
        `scale=${2 * W}:${2 * H}:force_original_aspect_ratio=increase,crop=${2 * W}:${2 * H},` +
        `zoompan=z='min(1+${KB_ZOOM}*on/${frames},${1 + KB_ZOOM})'` +
        `:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=${frames}:s=${W}x${H}:fps=${FPS_OUT}`;
    } else {
      // Looped so a 3s fond covers an 8s window; centre-cropped to the brand format
      // (a 16:9 asset on a 9:16 brand keeps its middle slice, never stretched).
      brollInputs.push("-stream_loop", "-1", "-i", b.file);
      branch =
        `scale=${W}:${H}:force_original_aspect_ratio=increase,crop=${W}:${H},` +
        `fps=${FPS_OUT},trim=duration=${D}`;
    }
    brollGraph += `[${baseIdx + k}:v]${branch},setpts=PTS-STARTPTS+${b.start}/TB,format=yuv420p[b${k}];`;
    console.log(`[assemble] broll: ${b.still ? "still (Ken Burns)" : "video"} ${b.file} @${b.start}s→${b.end}s (${D}s)`);
  });
  let prev = "vbase";
  BROLLS.forEach((b, k) => {
    brollGraph += `[${prev}][b${k}]overlay=eof_action=pass:enable='between(t,${b.start},${b.end})'[bo${k}];`;
    prev = `bo${k}`;
  });
  brollFinal = prev;
}

// Cartes preuve : même mécanique d'overlay (setpts décalé + enable), mais positionnée et
// animée. Coins arrondis par masque alpha geq (anti-aliasé sur 1 px), ombre = copie noire
// de l'alpha, paddée puis floutée, posée 12 px plus bas. Glissement d'entrée via l'expression
// y de l'overlay (t = temps du flux principal), fondu via fade alpha sur le flux de la carte.
const CARD = Object.assign({ boxW: 0.55, boxH: 0.32, y: 150, radius: 36, shadow: 0, shadowPad: 70,
  inMs: 280, outMs: 200, slide: 80 }, (brand.montage && brand.montage.card) || {});
if (CARDS.length) {
  const [fn, fd] = FPS_OUT.split("/").map(Number);
  const fpsNum = fn / (fd || 1);
  const baseIdx = (mode === "split" ? 3 : 1) + BROLLS.length;
  const BW = Math.round(W * CARD.boxW), BH = Math.round(H * CARD.boxH);
  const R = Math.round(CARD.radius * W / 1080), PAD = CARD.shadowPad;
  const tin = (CARD.inMs / 1000).toFixed(3), tout = (CARD.outMs / 1000).toFixed(3);
  let prev = brollFinal || "vbase";
  CARDS.forEach((c, k) => {
    const D = +(c.end - c.start).toFixed(3);
    const Y0 = c.y != null ? Math.round(c.y) : CARD.y;
    brollInputs.push("-framerate", String(fpsNum), "-loop", "1", "-i", c.file);
    const idx = baseIdx + k;
    const alphaExpr = `255*clip(${R}+0.5-sqrt(pow(X-clip(X\,${R}\,W-1-${R})\,2)+pow(Y-clip(Y\,${R}\,H-1-${R})\,2))\,0\,1)`;
    const slide = `${CARD.slide}*pow(1-clip((t-${c.start})/${tin}\,0\,1)\,2)`;
    const useShadow = CARD.shadow > 0;   // 15/09 soir : ombre OFF par défaut (un client : « bordures noires autour de l'image »)
    // Taille exacte de la carte (ratio gardé, dims paires) : le masque de coins doit avoir la même taille.
    // Coins arrondis par alphamerge d'un masque gris (color+geq lum) multiplié par l'alpha d'origine
    // du PNG — JAMAIS geq sur les plans couleur d'une image rgba : ça posait un liseré noir de 8 px
    // en haut/gauche de la carte (vu 15/09 sur le commentaire Instagram).
    const dimsOut = run("ffprobe", ["-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", c.file]).trim().split("\n")[0].replace(/[^0-9,]/g, "");
    const [iw, ih] = dimsOut.split(",").map(Number);
    const f = Math.min(BW / iw, BH / ih);
    const cw = Math.max(2, Math.round(iw * f / 2) * 2), ch = Math.max(2, Math.round(ih * f / 2) * 2);
    const maskExpr = `255*clip(${R}+0.5-sqrt(pow(X-clip(X\\,${R}\\,W-1-${R})\\,2)+pow(Y-clip(Y\\,${R}\\,H-1-${R})\\,2))\\,0\\,1)`;
    brollGraph +=
      `[${idx}:v]format=rgba,scale=${cw}:${ch},trim=duration=${D},split[k${k}a][k${k}b];` +
      `[k${k}b]alphaextract,format=gray[k${k}al];` +
      `color=c=white:s=${cw}x${ch}:r=${fpsNum}:d=${D},format=gray,geq=lum='${maskExpr}'[k${k}m];` +
      `[k${k}m][k${k}al]blend=all_mode=multiply:shortest=1,format=gray[k${k}ma];` +
      `[k${k}a][k${k}ma]alphamerge,fade=t=in:st=0:d=${tin}:alpha=1,fade=t=out:st=${Math.max(0, D - CARD.outMs / 1000).toFixed(3)}:d=${tout}:alpha=1` +
      (useShadow ? `,split[ck${k}][cs${k}0];` : `[ck${k}];`);
    if (useShadow) {
      brollGraph +=
        `[cs${k}0]geq=r=0:g=0:b=0:a='alpha(X\\,Y)*${CARD.shadow}',pad=iw+${2 * PAD}:ih+${2 * PAD}:${PAD}:${PAD}:color=black@0,` +
        `format=yuva444p,boxblur=26:2,setpts=PTS-STARTPTS+${c.start}/TB[cs${k}];` +
        `[${prev}][cs${k}]overlay=x='(W-w)/2':y='${Y0 - PAD + 18}-${slide}':eof_action=pass:enable='between(t,${c.start},${c.end})'[co${k}a];`;
      prev = `co${k}a`;
    }
    brollGraph +=
      `[ck${k}]setpts=PTS-STARTPTS+${c.start}/TB[cc${k}];` +
      `[${prev}][cc${k}]overlay=x='(W-w)/2':y='${Y0}-${slide}':eof_action=pass:enable='between(t,${c.start},${c.end})'[co${k}];`;
    prev = `co${k}`;
    console.log(`[assemble] card: ${c.file} @${c.start}s→${c.end}s (${D}s) y=${Y0} ${cw}x${ch} (boîte ${BW}x${BH})`);
  });
  brollFinal = prev;
}

try {
  let inputs;
  let graph;

  if (mode === "split") {
    // One-time vertical gradient: transparent above the junction, opaque below.
    const mask = join(work, "mask.png");
    const start = M.junctionStart;
    const span = M.junctionHeight;
    run("ffmpeg", [
      "-y", "-loglevel", "error", "-f", "lavfi",
      "-i", `color=c=black:s=${W}x${H}:d=0.1`,
      "-vf", `format=gray,geq=lum='if(lt(Y,${start}),0,if(lt(Y,${start + span}),255*(Y-${start})/${span},255))'`,
      "-frames:v", "1", mask,
    ]);

    const crop = M.faceCrop ? `crop=${M.faceCrop},` : "";
    inputs = ["-i", top, "-i", cut, "-loop", "1", "-i", mask, ...brollInputs];
    const tail = (BROLLS.length || CARDS.length)
      ? `${gradeChain}[vbase];${brollGraph}[${brollFinal}]null${subsChain}${speedV}[v]`
      : `${gradeChain}${subsChain}${speedV}[v]`;
    graph =
      `[0:v]pad=${W}:${H}:0:0:color=${BG}[base];` +
      `[1:v]${crop}pad=${W}:${H}:0:${start}:color=${BG}[ff];` +
      `[2:v]format=gray[mk];[ff][mk]alphamerge[fa];` +
      `[base][fa]overlay=0:0:shortest=1,format=yuv420p${tail}`;
  } else {
    inputs = ["-i", cut, ...brollInputs];
    graph = (BROLLS.length || CARDS.length)
      ? `[0:v]scale=${W}:${H}:flags=lanczos,format=yuv420p${gradeChain}[vbase];${brollGraph}[${brollFinal}]null${subsChain}${speedV}[v]`
      : `[0:v]scale=${W}:${H}:flags=lanczos,format=yuv420p${gradeChain}${subsChain}${speedV}[v]`;
  }

  // Démarrage vidéo à 0 pile (fix 28/08/2026) : les rushs iPhone portent un premier PTS
  // vidéo à +1 frame (33 ms) qui se propage à travers toute la chaîne jusqu'au fichier
  // final — le lecteur affiche du NOIR sur le premier emplacement de frame (« frames
  // noires au début », un client). Recalage des deux flux à 0 ; le décalage A/V résiduel
  // (≤ 1 frame) est sous le seuil de perception.
  graph = graph.replace(/\[v\]$/, `,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=${TAIL}[v]`);

  const audioFrom = mode === "split" ? "1:a" : "0:a";
  console.log(`[assemble] mode=${mode} ${W}x${H} subs=${subsChain ? "yes" : "no"} → ${out}`);
  // Compression voix (brand.audio.compress, 28/08/2026) : remonter les fins de phrases
  // dites en voix qui tombe AVANT le loudnorm — lui ne gère que le niveau GLOBAL, pas la
  // dynamique mot à mot (un « compte. » soufflé reste inaudible sur un HP de téléphone).
  // Doux par design : ratio 2.5 @ -26 dB, l'objectif est la lisibilité, pas l'écrasement.
  const C = A.compress ? (typeof A.compress === "object" ? A.compress : {}) : null;
  const compChain = C
    ? `acompressor=threshold=${C.threshold ?? -26}dB:ratio=${C.ratio ?? 2.5}:attack=${C.attack ?? 12}:release=${C.release ?? 220}:knee=4:makeup=${C.makeup ?? 2},`
    : "";
  if (C) console.log(`[assemble] voice compress: ${C.threshold ?? -26}dB ratio ${C.ratio ?? 2.5}`);
  // Audio: lav mics often land on ONE channel — fold everything to centre and duplicate
  // to true stereo (both ears) BEFORE loudnorm, which then restores the level.
  run("ffmpeg", [
    "-y", "-loglevel", "error", ...inputs,
    "-filter_complex", graph,
    "-map", "[v]", "-map", audioFrom,
    // loudnorm sort en 192 kHz (upsampling interne) → l'AAC retombait à 96 kHz (audit 07/09,
    // 24/24 fichiers). aresample=48000 derrière, et -fps_mode cfr pour ne jamais ré-écrire
    // les timestamps vidéo du cut (CFR garanti par GATE3).
    // loudnorm rallonge la piste de ~70 ms (flush de sa fenêtre de lookahead) : on retaille
    // l'audio à la durée vidéo du cut (÷ SPEED), sinon la fin joue sur une image figée.
    // Marge de fin (08/09/2026) : TAIL s de dernière image tenue + silence, pour ne jamais
    // couper sec derrière le dernier mot (rush trop court derrière « Ciao »).
    // asetpts=N/SR/TB (08/09 soir) : la chaîne loudnorm→aresample→atrim→apad laissait un trou
    // de 35 ms dans les timestamps des paquets AAC du fichier final (ADS3 v11 @77 s) ; on
    // re-timestampe par comptage de samples, la piste redevient contiguë. apad=pad_dur laissait
    // la piste 25 ms trop courte (samples décodés 80.192 pour 80.217 attendus) : apad=whole_dur
    // puis atrim à cut+TAIL+0.12 : l'encodeur AAC perd 37 à 68 ms au flush final (mesuré sur
    // ADS3/ADS1, contenu aligné à 0 ms) ; la piste décodée finit 50 à 80 ms APRÈS la dernière
    // image, en silence (le lecteur tient la dernière image, invisible), jamais avant.
    "-af", `asetpts=PTS-STARTPTS,${speedA}aformat=channel_layouts=stereo,pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1,${compChain}loudnorm=I=${A.loudness}:TP=${A.truePeak}:LRA=${A.range},aresample=48000,atrim=end=${(CUT_VDUR / SPEED).toFixed(3)},apad=whole_dur=${(CUT_VDUR / SPEED + TAIL + 0.3).toFixed(3)},atrim=end=${(CUT_VDUR / SPEED + TAIL + 0.12).toFixed(3)},asetpts=N/SR/TB`,
    "-fps_mode", "cfr",
    ...(vtArgs(brand.render) || ["-c:v", "libx264", "-crf", "22"]),
    "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
    resolve(out),
  ]);

  // A/V (08/09/2026) : pistes vidéo et audio de même durée à 1 image près, sinon la fin de
  // la dernière phrase joue sur une image figée et la dernière carte n'apparaît jamais.
  {
    const pr = (sel) => Number(run("ffprobe", ["-v", "error", "-select_streams", sel, "-show_entries", "stream=duration", "-of", "csv=p=0", resolve(out)]).trim()) || 0;
    const vd = pr("v:0"), ad = pr("a:0");
    const fr = run("ffprobe", ["-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", resolve(out)]).trim();
    const [fn_, fd_] = fr.split("/").map(Number); const fps_ = fd_ ? fn_ / fd_ : 30;
    // audio jamais plus court que la vidéo (−1 image tolérée : conteneur), et pas plus long que
    // 0,2 s (queue de silence du pad, perte AAC variable 37-68 ms)
    if (ad < vd - 1.0 / fps_ || ad > vd + 0.2) { console.error(`[assemble] A/V FAIL : vidéo ${vd.toFixed(3)}s ≠ audio ${ad.toFixed(3)}s`); process.exit(3); }
    console.log(`[assemble] A/V OK : vidéo ${vd.toFixed(3)}s / audio ${ad.toFixed(3)}s`);
  }
  // Stereo check: both ears must carry signal. astats reports on stderr even on success,
  // so run through a shell and merge the streams before parsing per-channel RMS.
  const st = execSync(`ffmpeg -i "${resolve(out)}" -map 0:a -af astats -f null - 2>&1`,
    { stdio: ["ignore", "pipe", "pipe"] }).toString();
  const rms = [...st.matchAll(/RMS level dB:\s*(-?[\d.]+)/g)].map((m) => parseFloat(m[1]));
  if (rms.length >= 3) {
    const [l, r] = rms;   // channel 1, channel 2 (last match is Overall)
    const diff = Math.abs(l - r);
    console.log(`[assemble] stereo check: L=${l}dB R=${r}dB ${diff > 6 ? "⚠ DÉSÉQUILIBRE — un canal est vide" : "OK (les 2 oreilles)"}`);
  } else {
    console.log(`[assemble] stereo check: ⚠ sortie MONO ou astats illisible`);
  }

  const probe = run("ffprobe", [
    "-v", "error", "-select_streams", "v:0",
    "-show_entries", "stream=width,height,nb_frames",
    "-of", "default=noprint_wrappers=1", resolve(out),
  ]).trim().replace(/\r?\n/g, " ");
  console.log(`[assemble] done — ${probe}`);
} catch (e) {
  const detail = (e.stderr ? e.stderr.toString() : "") || e.message;
  console.error(`[assemble] FAILED\n${detail}`);
  process.exitCode = 1;
} finally {
  rmSync(work, { recursive: true, force: true });
}
