/**
 * qa — rapport de confiance d'un fichier final (ou d'un batch), sans visionnage humain.
 * Créé 28/08/2026 (demande un client : « batch 8x3 sûr sans que je regarde tout »).
 * Refonte 06/09/2026 : verdict hiérarchisé + le RUSH comme référence + second avis Whisper.
 *   Avant : tout mot du script absent = FLAG. Batch client A 31/08 = « 0 vert / 13 à regarder »,
 *   4 vrais défauts (hook amputé, CTA coupé, mots avalés) noyés dans 28 reformulations → livrés.
 *
 *   node qa.mjs --file final.mp4 --script script-full.txt [--rush rush.words.json] [--json r.json] [--whisper]
 *   node qa.mjs --manifest batch.json [--json report.json] [--whisper]
 *       batch.json = [{ "file": "...mp4", "script": "...txt", "rush": "...words.json" }, …]
 *       rush = transcript Scribe de reconnaissance du rush (recon/<rush>.words.json), ou le média
 *       (.mp4/.mov/.wav) : transcrit une fois et mis en cache à côté (<média>.words.json).
 *
 * Checks par fichier :
 *   1. probe        : durée, résolution, fps, start_time vidéo/audio = 0 (frames noires sinon)
 *   2. black        : blackdetect sur tout le fichier (aucune plage noire tolérée)
 *   3. stereo       : RMS par canal (les 2 oreilles portent du signal, écart < 1 dB)
 *   4. transcript   : re-transcription Scribe du fichier FINAL comparée mot à mot au script.
 *      Chaque bloc du script absent de l'audio est CLASSÉ :
 *        ROUGE fin tronquée      : manque dans la dernière 1,5 s / après le dernier mot entendu
 *        ROUGE coupé au montage  : le rush contient là des mots que le final n'a pas (≥ 3, ou
 *                                  les mots manquants eux-mêmes) → un morceau dit a été jeté
 *        ROUGE clause manquante  : ≥ 3 mots, pas de rush fourni pour trancher
 *        À ÉCOUTER mot court     : 1-2 mots, pas de rush ; --whisper tranche (fenêtre ±3 s)
 *        info reformulation      : le rush ne contient rien de plus à cet endroit → le speaker
 *                                  a dit autre chose, ce n'est pas un défaut de montage
 *        info variante de forme  : les mots manquants sont dans le final à ±3 s (« l'enfance »
 *                                  vs « ton enfance »)
 *      Un mot audio absent du script = déviation dite par le speaker (info).
 * Verdict : VERT / À ÉCOUTER / ROUGE. Exit 1 si au moins un ROUGE dans le batch.
 * La QA de GOÛT (cadrage, colo, style) reste à l'œil humain sur un échantillon.
 * Prérequis : env.sh sourcé + ELEVENLABS_API_KEY ; --whisper = `whisper` (openai-whisper) dans le PATH.
 */
import { readFileSync, writeFileSync, mkdtempSync, rmSync, existsSync } from "node:fs";
import { execSync, execFileSync } from "node:child_process";
import { join, dirname, basename } from "node:path";
import { fileURLToPath } from "node:url";
import { tmpdir } from "node:os";

const HERE = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const flag = (n) => { const i = args.indexOf(`--${n}`); return i !== -1 ? args[i + 1] : undefined; };
const has = (n) => args.includes(`--${n}`);
const sh = (c) => execSync(c, { stdio: ["ignore", "pipe", "pipe"] }).toString();
const shBoth = (c) => execSync(c + " 2>&1", { stdio: ["ignore", "pipe", "pipe"] }).toString();  // Windows : cmd.exe, Mac : /bin/sh

const jobs = flag("manifest")
  ? JSON.parse(readFileSync(flag("manifest"), "utf8"))
  : [{ file: flag("file"), script: flag("script"), rush: flag("rush") }];
if (!jobs.length || !jobs[0].file || !jobs[0].script) {
  console.error("usage: qa.mjs --file f.mp4 --script s.txt [--rush r.words.json] | --manifest batch.json  [--json report.json] [--whisper]");
  process.exit(1);
}
const WHISPER = has("whisper");
const END_ZONE = 1.5;        // s : manque dans la dernière 1,5 s = fin tronquée
const NEAR = 3.0;            // s : fenêtre « variante de forme » dans le final
const STEM = (w) => w.slice(0, 5);
const STOP = new Set(["le","la","les","un","une","des","de","du","et","ou","à","a","en","que","qui","ce","c'est","cest","tu","te","toi","ton","ta","tes","il","elle","on","ne","pas","pour","par","sur","dans","au","aux","y","se","sa","son","ses","je","j","me","mais","donc","si","est","es","ben","eh"]);
const content = (ws) => ws.filter((w) => w.length > 2 && !STOP.has(w));
// Mots-nombres : dans une ad, un chiffre du script qui ne s'entend pas = argent perdu (« pour
// atteindre euros par mois », ADS7 31/08, le « vingt mille » avait sauté).
const NUMW = /^(\d+|zéro|un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|treize|quatorze|quinze|seize|vingt|trente|quarante|cinquante|soixante|cent|cents|mille|million|millions|milliard|milliards)$/;
const hasNum = (ws) => ws.some((w) => NUMW.test(w));

const norm = (w) => w.toLowerCase().normalize("NFC").replace(/[^a-zàâäéèêëîïôöùûüç0-9']/g, "");
// Un mot Scribe peut être « est-ce », « dix-mille », « t'étais » : on compare des tokens séparés
// sur tirets/apostrophes, sinon « connecte-toi » ne matche jamais « connecte toi ».
const toks = (s) => String(s).split(/[\s'’\-]+/).map(norm).filter(Boolean);
function lev(a, b) {
  const m = a.length, n = b.length; if (Math.abs(m - n) > 2) return 3;
  let prev = Array.from({ length: n + 1 }, (_, j) => j);
  for (let i = 1; i <= m; i++) {
    const cur = [i];
    for (let j = 1; j <= n; j++) cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    prev = cur;
  }
  return prev[n];
}

// LCS mot à mot (difflib-like) : retourne les blocs de divergence
function diffWords(a, b) {
  const m = a.length, n = b.length;
  const dp = Array.from({ length: m + 1 }, () => new Int32Array(n + 1));
  for (let i = m - 1; i >= 0; i--)
    for (let j = n - 1; j >= 0; j--)
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const ops = [];
  let i = 0, j = 0;
  while (i < m && j < n) {
    if (a[i] === b[j]) { i++; j++; continue; }
    const start = { i, j };
    while (i < m && j < n && a[i] !== b[j]) {
      if (dp[i + 1][j] >= dp[i][j + 1]) i++; else j++;
    }
    ops.push({ ai: start.i, aj: i, bi: start.j, bj: j });
  }
  if (i < m) ops.push({ ai: i, aj: m, bi: n, bj: n });
  if (j < n) ops.push({ ai: m, aj: m, bi: j, bj: n });
  return ops;
}

// Carte a[i] -> index dans b pour les mots appariés par le LCS (-1 sinon). Seules les
// suites d'au moins MINRUN mots appariés d'affilée font foi : un « pourquoi » ou un « les »
// isolé s'apparie n'importe où dans un rush à plusieurs prises (ADS7-H3 06/09 : ancre du
// début de hook envoyée dans le hook précédent → faux « coupé au montage »).
function alignMap(a, b, MINRUN = 3) {
  const map = new Array(a.length).fill(-1);
  let i = 0, j = 0;
  for (const op of [...diffWords(a, b), { ai: a.length, aj: a.length, bi: b.length, bj: b.length }]) {
    const run = Math.min(op.ai - i, op.bi - j);
    if (run >= MINRUN) for (let k = 0; k < run; k++) map[i + k] = j + k;
    i = op.aj; j = op.bj;
  }
  return map;
}

// Transcript du rush : words.json fourni, ou média → Scribe une fois, cache à côté
function rushWords(rush) {
  if (!rush) return null;
  let wj = rush;
  if (!/\.json$/i.test(rush)) {
    wj = rush.replace(/\.[^.]+$/, "") + ".words.json";
    if (!existsSync(wj)) {
      const tmp = mkdtempSync(join(tmpdir(), "qa-rush-"));
      const wav = join(tmp, "r.wav");
      sh(`ffmpeg -loglevel error -y -i "${rush}" -vn -ac 1 -ar 16000 "${wav}"`);
      sh(`node "${join(HERE, "../cut/scribe.mjs")}" "${wav}" "${wj}" fra`);
      rmSync(tmp, { recursive: true, force: true });
    }
  }
  return JSON.parse(readFileSync(wj, "utf8")).words.flatMap((w) => toks(w.text).map((n) => ({ n, at: w.start })));
}

// Second avis Whisper sur des fenêtres courtes (une invocation par fichier : le modèle se
// charge une fois). Retourne { idx: [mots normalisés entendus] }.
function whisperWindows(file, items) {
  if (!items.length) return {};
  const tmp = mkdtempSync(join(tmpdir(), "qa-wh-"));
  const wavs = items.map((it, k) => {
    const w = join(tmp, `w${k}.wav`);
    sh(`ffmpeg -loglevel error -y -ss ${Math.max(0, it.at - 3).toFixed(2)} -t 6 -i "${file}" -ac 1 -ar 16000 "${w}"`);
    return w;
  });
  const out = {};
  try {
    sh(`whisper ${wavs.map((w) => `"${w}"`).join(" ")} --model large-v3-turbo --language fr --output_format json --output_dir "${tmp}" --verbose False --fp16 False`);
    items.forEach((it, k) => {
      const j = JSON.parse(readFileSync(join(tmp, `w${k}.json`), "utf8"));
      out[k] = toks(j.text);
    });
  } catch (e) { console.error(`   (whisper indisponible : ${String(e.message).split("\n")[0]})`); }
  rmSync(tmp, { recursive: true, force: true });
  return out;
}

const report = [];
for (const { file, script, rush } of jobs) {
  const rouges = [], ecouter = [], infos = [];
  const name = basename(file);

  // 1. probe
  const streams = sh(`ffprobe -v error -show_entries stream=codec_type,start_time,width,height,r_frame_rate -of json "${file}"`);
  const st = JSON.parse(streams).streams;
  const v = st.find((s) => s.codec_type === "video"), a = st.find((s) => s.codec_type === "audio");
  const durS = parseFloat(sh(`ffprobe -v error -show_entries format=duration -of csv=p=0 "${file}"`).trim());
  if (!v || !a) rouges.push({ kind: "flux", at: 0, text: "flux vidéo ou audio manquant" });
  if (v && Math.abs(parseFloat(v.start_time)) > 0.001) rouges.push({ kind: "start", at: 0, text: `start_time vidéo ${v.start_time} ≠ 0 (frames noires au départ)` });
  // Pistes vidéo et audio de même longueur, sinon désynchro (ADS4-H2 06/09 : concat `-c copy`
  // d'un hook et d'un body aux paramètres H.264 différents → vidéo 93,5 s / audio 98,8 s, lèvres
  // et sous-titres décalés de 5 s, invisible pour tous les checks texte).
  try {
    const dv = parseFloat(sh(`ffprobe -v error -select_streams v:0 -show_entries stream=duration -of csv=p=0 "${file}"`).trim());
    const da = parseFloat(sh(`ffprobe -v error -select_streams a:0 -show_entries stream=duration -of csv=p=0 "${file}"`).trim());
    if (dv > 0 && da > 0 && Math.abs(dv - da) > 0.15)
      rouges.push({ kind: "désynchro", at: Math.min(dv, da), text: `pistes vidéo ${dv.toFixed(2)}s / audio ${da.toFixed(2)}s : désynchro A/V (${Math.abs(dv - da).toFixed(2)}s) — concat de morceaux aux paramètres différents ? re-encoder chaque partie puis concat` });
  } catch { /* probe impossible : les autres checks parleront */ }
  if (a && Math.abs(parseFloat(a.start_time)) > 0.001) rouges.push({ kind: "start", at: 0, text: `start_time audio ${a.start_time} ≠ 0` });

  // 2. black
  const black = shBoth(`ffmpeg -i "${file}" -vf "blackdetect=d=0.05:pix_th=0.08" -an -f null -`)
    .split("\n").filter((l) => l.includes("black_start"));
  for (const l of black) rouges.push({ kind: "noir", at: 0, text: `plage noire : ${l.replace(/.*black_start/, "black_start").trim()}` });

  // 3. stereo
  const rms = [...shBoth(`ffmpeg -i "${file}" -map 0:a -af astats -f null -`)
    .matchAll(/RMS level dB:\s*(-?[\d.]+)/g)].map((x) => parseFloat(x[1]));
  if (rms.length >= 2) {
    const [L, R] = rms;
    if (L < -50 || R < -50) rouges.push({ kind: "stereo", at: 0, text: `canal quasi muet (L=${L} R=${R} dB)` });
    else if (Math.abs(L - R) > 1) rouges.push({ kind: "stereo", at: 0, text: `déséquilibre stéréo L=${L} R=${R} dB` });
  }

  // 4. transcript final vs script (+ rush)
  const tmp = mkdtempSync(join(tmpdir(), "qa-"));
  const wav = join(tmp, "a.wav"), wj = join(tmp, "w.json");
  sh(`ffmpeg -loglevel error -y -i "${file}" -ac 1 -ar 16000 "${wav}"`);
  let tWords = [];
  try {
    sh(`node "${join(HERE, "../cut/scribe.mjs")}" "${wav}" "${wj}" fra`);
    tWords = JSON.parse(readFileSync(wj, "utf8")).words;
  } catch { rouges.push({ kind: "asr", at: 0, text: "re-transcription Scribe impossible (clé/API ?)" }); }
  let R = null;
  try { R = rushWords(rush); } catch (e) { infos.push(`rush illisible (${String(e.message).split("\n")[0]}) : triage sans rush`); }

  const pending = []; // items à trancher avec Whisper
  if (tWords.length) {
    const t = tWords.flatMap((w) => toks(w.text).map((n) => ({ n, at: w.start, end: w.end })));
    const tn = t.map((x) => x.n);
    const s = toks(readFileSync(script, "utf8"));
    const finalToks = [...new Set(tn)];
    const rn = R ? R.map((x) => x.n) : null;
    const t2r = rn ? alignMap(tn, rn) : null;
    const lastHeard = t.length ? t[t.length - 1].end : 0;

    for (const op of diffWords(tn, s)) {
      const said = t.slice(op.ai, op.aj), scripted = s.slice(op.bi, op.bj);
      const at = said[0]?.at ?? t[Math.min(op.ai, t.length - 1)]?.at ?? 0;
      // Mots du rush entre les deux ancres (mot final apparié avant / après le bloc)
      const rushSeg = () => {
        if (!rn) return null;
        // ancre avant = mot fiable le plus proche dans les 6 mots précédents (pas seulement
        // le voisin immédiat, qui peut être un mot isolé non fiable)
        let prev = -1;
        for (let k = op.ai - 1; k >= Math.max(0, op.ai - 6) && prev === -1; k--) prev = t2r[k];
        let next = -1;
        for (let k = op.aj; k < Math.min(t2r.length, op.aj + 6) && next === -1; k++) next = t2r[k];
        const r0 = prev >= 0 ? prev + 1 : 0;
        let r1 = next >= 0 ? next : (prev >= 0 ? rn.length : 0);
        if (next === -1 && prev >= 0) { // fin de fichier : 4 s de rush après l'ancre
          const tPrev = R[prev].at;
          r1 = R.findIndex((x, k) => k > prev && x.at > tPrev + 4);
          if (r1 === -1) r1 = rn.length;
        }
        // Une phrase jetée par le dérush est CONTIGUË dans le rush : ses deux ancres sont à
        // moins de 8 s l'une de l'autre. Un saut plus large (jonction hook→body, prise
        // alternative, intro hors script) est structurel, on n'y cherche rien. Sans ancre
        // avant (début de fichier) on ne sait pas où regarder : rien non plus.
        if (prev < 0) return [];
        const prevT = R[prev].at, nextT = next >= 0 ? R[next].at : Infinity;
        if (next >= 0 && nextT - prevT > 8) return [];
        return R.slice(r0, r1).filter((x) => x.at <= prevT + 4 || x.at >= nextT - 4).map((x) => x.n);
      };
      // Jonction (saut > 8 s dans le rush, ou pas d'ancre après) : un saut y est normal (autre
      // prise, hook suivant)… sauf si les 4 s de rush qui suivent l'ancre partagent des mots
      // avec le bloc de SCRIPT manquant : alors c'est la reformulation de ce bloc que le
      // dérush a jetée (hook ADS6-H3 « qui t'empêche d'aller à fond » vs script « pour jamais
      // y aller » ; punchline ADS7-H2 « …arrêterait pas cinq minutes avec ce genre de bêtises »
      // vs script « on va arrêter avec ce genre de bêtises »). Retourne les mots nouveaux.
      const rephrasedAtJunction = (scriptedWords) => {
        if (!rn) return [];
        let prev = -1;
        for (let k = op.ai - 1; k >= Math.max(0, op.ai - 6) && prev === -1; k--) prev = t2r[k];
        if (prev < 0) return [];
        const prevT = R[prev].at;
        const after = R.filter((x, k) => k > prev && x.at <= prevT + 4).map((x) => x.n);
        const cwS = content(scriptedWords).map(STEM);
        const shared = content(after).some((w) => cwS.includes(STEM(w)));
        if (!shared) return [];
        return novelWords(after);
      };
      // Mots-contenu du segment rush qu'on ne retrouve NULLE PART dans le final (ni à ≤ 2
      // lettres près : « ohana »/« oana », « tous »/« tout » sont des variantes ASR, pas du
      // contenu perdu). Une prise abandonnée répète des mots que le final a gardés (→ 0
      // nouveau) ; une phrase jetée par le dérush, non (→ ses mots-contenu sont nouveaux).
      const novelWords = (seg) => {
        if (!seg) return [];
        const near = new Set(t.map((x) => STEM(x.n)));
        const out = [], seen = new Set();
        for (const w of content(seg)) {
          const k = STEM(w);
          if (near.has(k) || seen.has(k) || /^\d+$/.test(w) || w.length < 3) continue;
          // quasi-doublon (variante ASR) seulement sur les mots longs : « sais »≈« mais » ou
          // « fond »≈« font » sont de vrais mots différents, « brunehilde »≈« brunehild » non
          if (w.length >= 6 && finalToks.some((f) => f.length >= 6 && lev(w, f) <= 2)) continue;
          seen.add(k); out.push(w);
        }
        if (process.env.QA_DEBUG) console.error(`   [debug @${at.toFixed(1)}] seg=« ${seg.join(" ")} » novel=${JSON.stringify(out)}`);
        return out;
      };
      if (!(scripted.length && !said.length)) {
        if (scripted.length && said.length) {
          const saidTxt = said.map((x) => x.n).join(" ");
          // Bloc remplacé : si le rush a là nettement plus de mots que le final n'en a gardé,
          // c'est un morceau dit qui a sauté (ADS7-H2 31/08 : punchline remplacée par le 1er
          // mot du hook suivant, vue comme une simple « déviation »).
          let nov = novelWords(rushSeg());
          const saidN = said.map((x) => x.n);
          if (nov.length < 3) { const j = rephrasedAtJunction(scripted); if (j.length >= 2) nov = j; }
          // Bloc remplacé court À UNE JONCTION dont le 1er mot dit n'est pas dans le script :
          // « je c'est » pour « ce n'est » (ADS7-H1 06/09, fragment « Je- » collé au début du
          // body, avalé dans une « déviation » alors que un client l'entend). Jamais info.
          let junctionRep = false;
          if (rn && said.length <= 3 && !scripted.includes(saidN[0])) {
            let prev = -1, next = -1;
            for (let k = op.ai - 1; k >= Math.max(0, op.ai - 6) && prev === -1; k--) prev = t2r[k];
            for (let k = op.aj; k < Math.min(t2r.length, op.aj + 6) && next === -1; k++) next = t2r[k];
            junctionRep = prev >= 0 && next >= 0 && R[next].at - R[prev].at > 8;
          }
          if (nov.length < 3 && junctionRep)
            ecouter.push({ kind: "mot parasite", at, text: `@${at.toFixed(1)}s mot parasite possible à une jonction : dit « ${saidTxt} » pour script « ${scripted.join(" ")} » (fragment d'une autre prise ?)` });
          else if (nov.length >= 3)
            rouges.push({ kind: "coupé au montage", at, text: `@${at.toFixed(1)}s coupé au montage : dit « ${saidTxt} » pour script « ${scripted.join(" ")} » — le rush dit là « ${nov.join(" ")} », absent du final` });
          else if (hasNum(scripted) && !hasNum(saidN))
            ecouter.push({ kind: "chiffre absent", at, text: `@${at.toFixed(1)}s chiffre du script absent : dit « ${saidTxt} » pour script « ${scripted.join(" ")} »` });
          else if (nov.length >= 2 || (nov.length === 1 && nov[0].length > 4))
            ecouter.push({ kind: "mot du rush absent", at, text: `@${at.toFixed(1)}s dit « ${saidTxt} » pour script « ${scripted.join(" ")} » — le rush dit là « ${nov.join(" ")} », absent du final` });
          else
            infos.push(`déviation @${at.toFixed(1)}s : dit « ${saidTxt} » / script « ${scripted.join(" ")} »`);
        } else {
          // Ajout hors script de 1-2 mots à une JONCTION (les ancres rush avant/après sont à
          // > 8 s) = mot parasite probable : premier mot de la prise suivante tombé dans la
          // fenêtre du hook (« Je… c'est pas de ta faute », ADS7-H1 06/09, entendu par un client
          // alors que la QA l'avait classé info). Ailleurs, un ajout court est une respiration.
          const saidTxt = said.map((x) => x.n).join(" ");
          let junction = false;
          if (rn && said.length <= 2) {
            let prev = -1, next = -1;
            for (let k = op.ai - 1; k >= Math.max(0, op.ai - 6) && prev === -1; k--) prev = t2r[k];
            for (let k = op.aj; k < Math.min(t2r.length, op.aj + 6) && next === -1; k++) next = t2r[k];
            junction = prev >= 0 && next >= 0 && R[next].at - R[prev].at > 8;
          }
          if (junction)
            ecouter.push({ kind: "mot parasite", at, text: `@${at.toFixed(1)}s mot parasite possible à une jonction : « ${saidTxt} » (1er mot d'une autre prise dans la fenêtre du hook ?)` });
          else
            infos.push(`ajout hors script @${at.toFixed(1)}s : « ${saidTxt} »`);
        }
        continue;
      }
      const words = scripted.join(" ");
      // Contre-vérification : la re-transcription QA a sa propre variance ASR (vécu :
      // « pas un hasard » → « un » manquant au 1er passage). On re-transcrit la fenêtre
      // ±2 s seule ; si le mot y est, c'était du bruit de QA, pas un mot avalé.
      try {
        const ww = join(tmp, "win.wav"), wwj = join(tmp, "win.json");
        sh(`ffmpeg -loglevel error -y -ss ${Math.max(0, at - 2).toFixed(2)} -t 4 -i "${file}" -ac 1 -ar 16000 "${ww}"`);
        sh(`node "${join(HERE, "../cut/scribe.mjs")}" "${ww}" "${wwj}" fra`);
        const winWords = JSON.parse(readFileSync(wwj, "utf8")).words.flatMap((w) => toks(w.text));
        if (scripted.every((sw) => winWords.includes(sw))) {
          infos.push(`@${at.toFixed(1)}s « ${words} » manquant au 1er passage QA mais présent au 2e (bruit ASR, fichier OK)`);
          continue;
        }
      } catch { /* fenêtre intranscriptible : on continue le triage */ }

      // Variante de forme : les mots-contenu manquants sont dans le final à ±3 s
      const cw = content(scripted);
      const nearFinal = t.filter((x) => Math.abs(x.at - at) <= NEAR).map((x) => STEM(x.n));
      if (cw.length && cw.every((w) => nearFinal.includes(STEM(w)))) {
        infos.push(`variante de forme @${at.toFixed(1)}s : « ${words} » (mots présents autour dans le final)`);
        continue;
      }

      // Fin tronquée ?
      const endZone = op.ai >= t.length || at >= durS - END_ZONE || (lastHeard - at) < END_ZONE && op.ai >= t.length - 1;

      // Le rush a-t-il là des mots que le final n'a pas ?
      let nov = [], rushHas = false;
      if (rn) {
        const seg = rushSeg();
        nov = novelWords(seg);
        const segStem = seg.map(STEM);
        rushHas = cw.length > 0 && cw.every((w) => segStem.includes(STEM(w)));
        if (!rushHas && nov.length < 3) { const j = rephrasedAtJunction(scripted); if (j.length >= 2) nov = j; }
      }

      // Fin de fichier : l'ancre LCS est fragile (le rush a plusieurs prises de la fin), on
      // regarde directement les 6 dernières secondes du rush = la dernière prise du CTA.
      let endInRush = false;
      if (rn && endZone && R.length) {
        const tEnd = R[R.length - 1].at;
        const tail = R.filter((x) => x.at >= tEnd - 6).map((x) => STEM(x.n));
        endInRush = cw.length > 0 && cw.every((w) => tail.includes(STEM(w)));
      }
      const item = { at, words, scripted, endZone, rushHas };
      if (endZone && (rn ? (rushHas || endInRush) : true)) {
        rouges.push({ kind: "fin tronquée", at, text: `@${at.toFixed(1)}s fin tronquée : « ${words} » (fin de fichier ${durS.toFixed(1)}s${rn ? ", ces mots sont dans la fin du rush" : ""})` });
      } else if (rn && (rushHas || nov.length >= 3)) {
        rouges.push({ kind: "coupé au montage", at, text: `@${at.toFixed(1)}s coupé au montage : « ${words} » — le rush dit là « ${(rushHas ? cw : nov).join(" ")} », absent du final` });
      } else if (hasNum(scripted)) {
        ecouter.push({ kind: "chiffre absent", at, text: `@${at.toFixed(1)}s chiffre du script absent : « ${words} »` });
      } else if (rn && (nov.length >= 2 || (nov.length === 1 && nov[0].length > 4))) {
        ecouter.push({ kind: "mot du rush absent", at, text: `@${at.toFixed(1)}s « ${words} » manquant — le rush dit là « ${nov.join(" ")} », absent du final` });
      } else if (rn) {
        infos.push(`reformulation @${at.toFixed(1)}s : « ${words} » (rien de plus dans le rush à cet endroit)`);
      } else if (scripted.length >= 3) {
        rouges.push({ kind: "clause manquante", at, text: `@${at.toFixed(1)}s clause manquante : « ${words} » (pas de rush fourni pour trancher)` });
        pending.push(item);
      } else {
        ecouter.push({ kind: "mot court", at, text: `@${at.toFixed(1)}s mot court absent : « ${words} »` });
        pending.push(item);
      }
    }
  }

  // Second avis Whisper sur les items sans rush (ou tout ce qui reste rouge/à écouter si demandé)
  if (WHISPER) {
    const targets = pending.length ? pending : [...rouges, ...ecouter].filter((x) => x.scripted || x.at > 0);
    const heard = whisperWindows(file, targets);
    targets.forEach((it, k) => {
      const hw = heard[k]; if (!hw) return;
      const cw = content(it.scripted || String(it.words || "").split(" "));
      const ok = cw.length ? cw.every((w) => hw.map(STEM).includes(STEM(w))) : (it.scripted || []).every((w) => hw.includes(w));
      if (ok) {
        const drop = (arr) => { const i = arr.findIndex((x) => x.at === it.at); if (i !== -1) arr.splice(i, 1); };
        drop(rouges); drop(ecouter);
        infos.push(`@${it.at.toFixed(1)}s « ${it.words} » entendu par Whisper (bruit Scribe, fichier OK)`);
      }
    });
  }
  rmSync(tmp, { recursive: true, force: true });

  const verdict = rouges.length ? "ROUGE" : ecouter.length ? "A ECOUTER" : "VERT";
  const icon = verdict === "VERT" ? "🟢" : verdict === "ROUGE" ? "🔴" : "🟠";
  report.push({ file: name, duration: durS, verdict, rouges, ecouter, infos,
                flags: [...rouges, ...ecouter].map((x) => x.text) });
  console.log(`\n${icon} ${name} — ${durS?.toFixed(1)}s — ${verdict}`);
  for (const f of rouges) console.log(`   ROUGE ${f.text}`);
  for (const f of ecouter) console.log(`   ÉCOUTER ${f.text}`);
  for (const x of infos) console.log(`   info  ${x}`);
}

const nR = report.filter((r) => r.verdict === "ROUGE").length;
const nE = report.filter((r) => r.verdict === "A ECOUTER").length;
const nV = report.length - nR - nE;
console.log(`\n=== batch : ${report.length} fichier(s) — ${nV} vert(s), ${nE} à écouter, ${nR} rouge(s)`);
for (const r of report.filter((r) => r.rouges.length))
  for (const f of r.rouges) console.log(`   🔴 ${r.file} ${f.text}`);
for (const r of report.filter((r) => r.ecouter.length))
  for (const f of r.ecouter) console.log(`   🟠 ${r.file} ${f.text}`);
if (flag("json")) writeFileSync(flag("json"), JSON.stringify(report, null, 1));
process.exit(nR ? 1 : 0);
