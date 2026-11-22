/**
 * Word-by-word karaoke subtitles: ElevenLabs Scribe JSON → ASS (burned in by libass).
 *
 *   node engine/montage/gen-subs.mjs <scribe.json> <out.ass> [--brand path/to/brand.json]
 *                                    [--emphasis emphasis.json] [--dump]
 *
 * Everything visual comes from brand.json → subtitles. Nothing is hardcoded here.
 *
 * Two rendering modes, switched by brand.subtitles.karaoke:
 *   karaoke: true   — original behaviour: one event per word, active word in accent colour,
 *                     optional soft box behind the segment (two layers, see below).
 *   karaoke: false  — "segment" mode (style ads Submagic-like): one event per segment,
 *                     three treatments driven by an emphasis map:
 *                       white  — plain text, drop shadow
 *                       green  — full segment in accent colour
 *                       box    — text in emphasis.textColor on a solid accent box,
 *                                pop-in animation (scale + slight rotation)
 *
 * Segment mode itself has two reveals, switched by brand.subtitles.reveal:
 *   "appear" (default) — words are invisible until spoken (style Submagic "William 2").
 *   "ghost"            — the next word pre-shows semi-transparent (subtitles.ghost.opacity)
 *                        a beat (ghost.lead) before it is spoken, the active word is slightly
 *                        zoomed (subtitles.activeZoom) and settles when the next word lands.
 *                        Cards wrap on subtitles.maxLineWidth px and green emphasis words are
 *                        bigger (emphasis.sizeBoost), centre-aligned per line like the
 *                        reference (style Submagic "Claire 2", ADS 1 HOOK 1). Needs the font's
 *                        .metrics.json sidecar (engine/lib/font-metrics.py) for exact layout.
 *
 * The emphasis map (--emphasis) is JSON: { "<segment index>": "green" | "box" | [wordIdx…] }.
 * The array form marks individual words green (ghost styles highlight words, not cards).
 * Segments absent from the map are white. Use --dump to print the segment list
 * (index, times, text, words) as JSON and exit — that's what the montage skill reads to
 * choose the emphasis levels before the real run.
 *
 * The soft box (karaoke mode) needs TWO layers per card: layer 0 = box only (text made
 * invisible) with \blur, layer 1 = sharp karaoke text with no box. A single BorderStyle-3
 * layer with \blur blurs the glyphs too AND breaks the box apart between inline colour
 * segments.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { loadBrand, hexToAss, assInline } from "../lib/brand.mjs";

const args = process.argv.slice(2);
const positional = args.filter((a) => !a.startsWith("--") && a !== "true" && a !== "false");
const flagValue = (name) => {
  const i = args.indexOf(`--${name}`);
  return i !== -1 ? args[i + 1] : undefined;
};
const RAW = positional[0];
const OUT = positional[1];
const DUMP = args.includes("--dump");
// Fenêtres b-roll ("start:end,start:end" en secondes, mêmes bornes que --broll d'assemble) :
// une carte qui chevauche une fenêtre s'affiche ENTIÈRE (décision un client 28/08 — sur un
// fond plein écran, le reveal mot-à-mot laisse des fragments flottants type « ta d »).
const BROLL_WINS = (flagValue("broll-windows") || "")
  .split(",").map((w) => w.split(":").map(Number)).filter((w) => w.length === 2 && w[1] > w[0]);
if (!RAW || (!OUT && !DUMP)) {
  console.error("usage: node gen-subs.mjs <scribe.json> <out.ass> [--brand brand.json] [--emphasis emphasis.json] [--dump]");
  process.exit(1);
}

const brand = loadBrand(flagValue("brand"));
const S = brand.subtitles;
const KARAOKE = S.karaoke !== false;
const REVEAL = S.reveal || "appear";
const GHOST = { opacity: 0.45, lead: 0.45, ...(S.ghost || {}) };
// ghost.opacity 0 = "ghost" layout/pop mechanics WITHOUT the pre-shown words (style claire2
// validé sans fantôme le 27/08 ; la variante avec = claire2-ghost.json). Lead 0 makes every
// ghost event zero-length, so nothing is emitted and cards start at their first spoken word.
if (GHOST.opacity <= 0) GHOST.lead = 0;

// Exact per-character advances (font-metrics.py sidecar). Ghost mode lays every word out
// at its final position before it is spoken: an eyeballed width table would shift the
// whole card, so exact metrics are mandatory there and a hard error when missing.
let FM = null;
const metricsPath = S.fontPath ? S.fontPath.replace(/\.(ttf|otf)$/i, ".metrics.json") : null;
try { FM = JSON.parse(readFileSync(metricsPath, "utf8")); } catch { /* handled below */ }
if (REVEAL === "ghost" && !FM) {
  console.error(`gen-subs: reveal "ghost" needs ${metricsPath} — run: .venv/bin/python3 engine/lib/font-metrics.py ${S.file}`);
  process.exit(1);
}
// Letter tracking in px. libass IGNORES the style Spacing field (vérifié 27/08) : il faut
// le tag inline \fsp sur chaque événement. Counted in the layout estimates. Défaut 0 =
// rendu naturel de la police (william2 validé ainsi).
const LS = S.letterSpacing ?? 0;
const FSP = LS ? `\\fsp${LS}` : "";
const advPx = (text, fs) => {
  let u = 0, n = 0;
  for (const ch of text) { u += FM.advances[ch] ?? FM.advances["x"] ?? FM.unitsPerEm * 0.5; n++; }
  return (u * fs) / FM.unitsPerEm + LS * Math.max(0, n - 1);
};
// libass maps \fs to the win cell height (usWinAscent+usWinDescent), NOT the em square:
// a font with a tall cell (Baloo 2: 1.65 em) renders visibly smaller than \fs suggests.
// Brand sizes are true em pixels (measured on the reference frames); emFs converts them.
const FSCALE = FM && FM.winAscent ? (FM.winAscent + FM.winDescent) / FM.unitsPerEm : 1;
const emFs = (em) => Math.round(em * FSCALE);
const EMPH = {
  textColor: "#000000",
  animation: true,
  animMs: 150,
  pad: 16,
  sizeBoost: 1,
  ...(S.emphasis || {}),
};

// Drop shadow, brand-tunable: subtitles.shadow = { depth, opacity, blur }. In segment
// mode the white/green shadow is a dedicated blurred layer (diffuse halo); depth doubles
// as its x/y offset. Hl (box) keeps the classic ASS shadow.
const SH = { depth: 3, opacity: 0.44, blur: 3, ...(S.shadow || {}) };
const SH_ALPHA = "&H" + Math.round((1 - SH.opacity) * 255).toString(16).toUpperCase().padStart(2, "0") + "&";

let emphMap = {};
const emphPath = flagValue("emphasis");
if (emphPath) {
  const parsed = JSON.parse(readFileSync(emphPath, "utf8"));
  emphMap = parsed.segments || parsed;
}

// Accepts both shapes: the raw ElevenLabs response (entries carry a `type`, and spacing /
// audio_event entries must be dropped) and the normalised words.json the cut engine writes
// (word entries only, no `type` field at all).
const j = JSON.parse(readFileSync(RAW, "utf8"));
if (!Array.isArray(j.words)) {
  console.error(`gen-subs: ${RAW} has no "words" array — is it a Scribe transcript?`);
  process.exit(1);
}
const words = j.words
  .filter((w) => (w.type === undefined || w.type === "word") && typeof w.text === "string")
  .filter((w) => w.text.trim() !== "" && typeof w.start === "number" && typeof w.end === "number")
  .map((w) => ({ text: w.text, start: w.start, end: w.end }));
if (words.length === 0) {
  console.error(`gen-subs: no timed words found in ${RAW} — nothing to subtitle.`);
  process.exit(1);
}

// Chiffres en chiffres (subtitles.numerals, ON par défaut — demande un client 31/08/2026) :
// « quinze mille euros » se lit mal à l'écran, « 15 000 euros » saute aux yeux. On fusionne
// la suite de mots-nombres en UN token (timings = début du premier -> fin du dernier), avant
// la segmentation, donc l'indexation des cartes reste cohérente entre --dump et le rendu.
// « un »/« une » seuls ne sont jamais convertis : ce sont des articles dans 99 % des cas.
const NUM_U = { zéro: 0, zero: 0, un: 1, une: 1, deux: 2, trois: 3, quatre: 4, cinq: 5, six: 6,
  sept: 7, huit: 8, neuf: 9, dix: 10, onze: 11, douze: 12, treize: 13, quatorze: 14,
  quinze: 15, seize: 16 };
const NUM_T = { vingt: 20, vingts: 20, trente: 30, quarante: 40, cinquante: 50, soixante: 60 };
const NUM_S = { cent: 100, cents: 100, mille: 1000, mil: 1000,
  million: 1e6, millions: 1e6, milliard: 1e9, milliards: 1e9 };
const numTok = (t) => t.toLowerCase().replace(/[.,;:!?…»«"']+$/g, "").replace(/^[«"']+/g, "");
const isNum = (t) => t in NUM_U || t in NUM_T || t in NUM_S;
function frGroup(n) {
  const s = String(n);
  // Espace insécable : « 15 000 » ne doit jamais se couper en fin de ligne.
  return n < 1000 ? s : s.replace(/\B(?=(\d{3})+(?!\d))/g, "\u00A0");
}
function parseRun(subs) {
  let total = 0, cur = 0, seen = false;
  for (let k = 0; k < subs.length; k++) {
    const t = subs[k];
    if (t === "et") { if (!seen || k === subs.length - 1) return null; continue; }
    if (t in NUM_U) { cur += NUM_U[t]; seen = true; continue; }
    if (t in NUM_T) { cur = t.startsWith("vingt") && cur === 4 ? 80 : cur + NUM_T[t]; seen = true; continue; }
    if (t in NUM_S) {
      const m = NUM_S[t];
      if (m >= 1000) { total += (cur || 1) * m; cur = 0; } else { cur = (cur || 1) * m; }
      seen = true; continue;
    }
    return null;
  }
  return seen ? total + cur : null;
}
function numerals(ws) {
  const out = [];
  for (let i = 0; i < ws.length; ) {
    const subsOf = (w) => numTok(w.text).split("-").filter(Boolean);
    if (!subsOf(ws[i]).every(isNum)) { out.push(ws[i]); i++; continue; }
    let j = i, subs = [];
    while (j < ws.length) {
      const s = subsOf(ws[j]);
      if (!s.every(isNum) && !(s.length === 1 && s[0] === "et" && j > i)) break;
      subs = subs.concat(s); j++;
      // Énumération (référence, 03/10/2026) : une virgule ou un point FERME le nombre. Sans ça
      // « dix, quinze, vingt mille euros » s'affichait « 45 000 euros » et « deux, trois minutes »
      // « 5 minutes » : un chiffre faux à l'écran. Résultat voulu : « 10, 15, 20 000 euros ».
      if (/[.,;:!?…]$/.test(ws[j - 1].text)) break;
    }
    while (subs.length && subs[subs.length - 1] === "et") { subs.pop(); j--; }
    // « 3 millions » (15/09/2026) : quand un chiffre précède déjà un mot-multiplicateur seul
    // (« millions », « mille » posé par une passe amont type numfix), on garde le mot — sinon
    // « millions » devenait « 1 000 000 » et l'écran affichait « 3 1 000 000 d'euros ».
    const prevOut = out[out.length - 1];
    if (prevOut && /\d$/.test(prevOut.text) && subs.every((t) => t in NUM_S)) { out.push(ws[i]); i++; continue; }
    const v = parseRun(subs);
    // « un » / « une » isolé = article, on ne touche pas.
    if (v === null || (j - i === 1 && v === 1 && /^une?$/.test(numTok(ws[i].text)))) {
      out.push(ws[i]); i++; continue;
    }
    const last = ws[j - 1];
    const tail = (/[.,;:!?…]+$/.exec(last.text) || [""])[0];
    out.push({ text: frGroup(v) + tail, start: ws[i].start, end: last.end });
    i = j;
  }
  return out;
}
// Remplacements de PHRASE : une clé de `replacements` qui contient une espace vise une
// suite de mots et la remplace par un seul token (timings = début du premier -> fin du
// dernier). Les remplacements mot à mot ne peuvent ni fusionner ni supprimer de mots, or
// Scribe transforme parfois une expression courte en une plus longue : sur ADS5 (31/08/2026)
// client A dit « Ce yo-yo », Scribe écrit « Ce lieu que tu vis », 5 mots pour 2. Sans ça le
// sous-titre affiche une phrase qui n'a aucun sens et que le spectateur n'entend pas.
{
  const phrases = Object.entries(S.replacements || {})
    .filter(([k]) => k.trim().includes(" "))
    .map(([k, v]) => ({ toks: k.toLowerCase().split(/\s+/).map(numTok), out: v }))
    .sort((a, b) => b.toks.length - a.toks.length);   // la plus longue gagne
  if (phrases.length) {
    const out = [];
    let n = 0;
    for (let i = 0; i < words.length; ) {
      const hit = phrases.find((p) => p.toks.every((t, k) =>
        words[i + k] && numTok(words[i + k].text) === t));
      if (!hit) { out.push(words[i]); i++; continue; }
      const last = words[i + hit.toks.length - 1];
      const tail = (/[.,;:!?…]+$/.exec(last.text) || [""])[0];
      out.push({ text: hit.out + tail, start: words[i].start, end: last.end });
      i += hit.toks.length; n++;
    }
    if (n) console.error(`[subs] phrases: ${n} expression(s) remplacée(s)`);
    words.length = 0; words.push(...out);
  }
}

if (S.numerals !== false) {
  const before = words.length;
  const after = numerals(words);
  // stderr, jamais stdout : --dump écrit le JSON des cartes sur stdout, un log s'y glisserait
  // en tête de fichier et le rendrait illisible (vu le 31/08/2026).
  if (after.length !== before) console.error(`[subs] chiffres: ${before - after.length} mots-nombres fusionnés en chiffres`);
  words.length = 0; words.push(...after);
}
// « 14 % » (référence, 03/10/2026) : le signe colle au chiffre en UN token, jamais seul en tête de carte.
{
  const out = [];
  for (const w of words) {
    const p = out[out.length - 1];
    if (p && /^%[.,;:!?…]*$/.test(w.text) && /\d$/.test(p.text)) { p.text = p.text + "\u00A0" + w.text; p.end = w.end; }
    else out.push({ ...w });
  }
  words.length = 0; words.push(...out);
}

// Display form: strip trailing punctuation, apply the brand's case rule, then any
// literal replacement the user declared (e.g. a spoken keyword shown differently on screen).
const replacements = new Map(
  Object.entries(S.replacements || {}).map(([k, v]) => [k.toLowerCase(), v])
);
function disp(w) {
  const m = /[.,;:!?…]+$/.exec(w.text);
  const tail = m ? m[0] : "";
  let core = tail ? w.text.slice(0, -tail.length) : w.text;
  const hit = replacements.get(core.toLowerCase());
  if (hit !== undefined) core = hit;
  // The case rule applies AFTER replacements: vocab values carry the canonical display form
  // ("Yehuda", "GHL") and an upper style still uppercases them.
  if (S.case === "upper") core = core.toUpperCase();
  // subtitles.punctuation (Submagic "Punctuation: Yes") keeps the trailing marks on screen.
  // Énumération de chiffres (« 10, 15, 20 000 euros ») : la virgule après un chiffre reste à
  // l'écran même sans ponctuation, sinon on lit « 15 20 000 » comme un seul nombre.
  if (!S.punctuation && tail[0] === "," && /^\d[\d\u00A0]*$/.test(core)) return core + ",";
  return S.punctuation ? core + tail : core;
}

// Segmentation: cap on words and characters, break on sentence punctuation or a real pause.
const segs = [];
let cur = [];
const flush = () => { if (cur.length) { segs.push(cur); cur = []; } };
for (const w of words) {
  if (cur.length) {
    const prev = cur[cur.length - 1];
    const gap = w.start - prev.end;
    const len = cur.reduce((n, x) => n + disp(x).length + 1, 0) + disp(w).length;
    if (gap > 0.35 || cur.length >= S.maxWords || len > S.maxChars || /[.!?]$/.test(prev.text)) flush();
  }
  cur.push(w);
}
flush();

// Ghost mode: cards are capped at 2 lines (retour un client 27/08). Split any segment whose
// estimated white-size width exceeds two lines BEFORE --dump, so emphasis indices chosen on
// the dump stay valid at render time (both paths run this same code).
if (!KARAOKE && REVEAL === "ghost" && FM) {
  const MAXW0 = S.maxLineWidth ?? Math.round(brand.width * 0.61);
  const SPW0 = S.wordSpacing ?? 1;
  const wOf = (arr) => arr.reduce((n, w, i) => n + advPx(disp(w), S.size) + (i ? SPW0 * advPx(" ", S.size) : 0), 0);
  const out = [];
  for (let seg of segs) {
    while (seg.length > 2 && wOf(seg) > (S.maxLines ?? 2) * MAXW0 * 0.92) {
      let best = null;
      for (let c = 1; c < seg.length; c++) {
        const m = Math.max(wOf(seg.slice(0, c)), wOf(seg.slice(c)));
        if (!best || m < best.m) best = { c, m };
      }
      out.push(seg.slice(0, best.c));
      seg = seg.slice(best.c);
    }
    out.push(seg);
  }
  segs.length = 0;
  segs.push(...out);
}

if (DUMP) {
  const list = segs.map((seg, i) => ({
    i,
    start: Number(seg[0].start.toFixed(2)),
    end: Number(seg[seg.length - 1].end.toFixed(2)),
    text: seg.map(disp).join(" "),
    words: seg.map(disp),
  }));
  console.log(JSON.stringify(list, null, 1));
  process.exit(0);
}

const ACTIVE = assInline(S.activeWordColor);
const IDLE = assInline(S.wordColor);

function ts(t) {
  // Intégral en centisecondes : Math.round((t%1)*100) donnait cs=100 sans retenue
  // ("0:00:29.100", timestamp ASS invalide — vu sur les subs client A 28/08).
  const T = Math.max(0, Math.round(t * 100));
  const h = Math.floor(T / 360000), m = Math.floor((T % 360000) / 6000),
        s = Math.floor((T % 6000) / 100), cs = T % 100;
  return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}.${String(cs).padStart(2, "0")}`;
}

const POS_X = Math.round(brand.width / 2);
const POS_Y = S.positionY;
const BLUR = S.box.blur;

// Ghost cards hand off early: card N appears (first word in ghost) ghost.lead before its
// first spoken word, and card N-1 clears at that same instant — never before its own last
// word has finished.
const ghostStart = [];
if (!KARAOKE && REVEAL === "ghost") {
  for (let i = 0; i < segs.length; i++) {
    const prevEnd = i ? segs[i - 1][segs[i - 1].length - 1].end : 0;
    ghostStart.push(Math.max(prevEnd, segs[i][0].start - GHOST.lead));
  }
}

let ev = "";
for (let si = 0; si < segs.length; si++) {
  const seg = segs[si];
  // gapFree (Submagic "Gap-free captions"): a card holds until the next one lands, so the
  // screen is never empty mid-speech. Capped at 1.2s so a long silence still clears it.
  const HOLD = S.gapFree ? 1.2 : 0.30;
  const segEnd = si + 1 < segs.length
    ? Math.min(seg[seg.length - 1].end + HOLD, segs[si + 1][0].start)
    : seg[seg.length - 1].end + 0.30;
  const plain = seg.map(disp).join(" ").trim();
  if (!plain) continue;

  if (!KARAOKE && REVEAL === "ghost") {
    // Style "Claire 2" (frame-by-frame study of ADS 1 HOOK 1, 27/08/2026): the whole card
    // is laid out at its final position; each word pre-shows semi-transparent, pops to full
    // slightly zoomed when spoken, and settles to 100% when the next word lands. Green
    // emphasis words are bigger and sit centre-aligned with their line (not baseline).
    const level = emphMap[si] ?? emphMap[String(si)];
    // "green" (toute la carte) | [idx…] (mots verts) | {green:[…], big:[…]} — big = mot
    // agrandi (même boost que le vert) mais qui RESTE blanc.
    const green = new Set(
      Array.isArray(level) ? level
      : level === "green" ? seg.map((_, k) => k)
      : level && typeof level === "object" ? level.green || [] : []);
    const big = new Set(level && typeof level === "object" && !Array.isArray(level) ? level.big || [] : []);
    const disps = seg.map(disp);
    const cardStart = ghostStart[si];
    const lastEnd = seg[seg.length - 1].end;
    const cardEnd = si + 1 < segs.length ? Math.min(lastEnd + 1.2, ghostStart[si + 1]) : lastEnd + 0.30;
    if (cardEnd - cardStart < 0.01) continue;
    const inBroll = BROLL_WINS.some(([wa, wb]) => seg[0].start < wb && lastEnd > wa);

    const fsOf = (k) => (green.has(k) || big.has(k) ? Math.round(S.size * (EMPH.sizeBoost || 1)) : S.size);
    const MAXW = S.maxLineWidth ?? Math.round(brand.width * 0.61);
    const SPW = S.wordSpacing ?? 1;   // widen word spaces so the pop never makes words touch

    // Balanced wrap, 2 lines max: one line when it fits, otherwise the break point that
    // minimises the widest line (greedy fill made ragged 3-line staircases). The pre-split
    // above guarantees a 2-line budget at white size; a green boost may overflow MAXW a
    // little, which beats adding a 3rd line.
    // Deux modes d'espacement : legacy (chasse de l'espace) ou "ink" (S.wordGap défini +
    // bounds dans le sidecar) — le gap est alors mesuré entre les ENCRES des mots voisins,
    // donc visuellement constant quelles que soient les lettres de bordure (retour un client
    // 27/08 : écarts inégaux d'un mot à l'autre).
    const INK = S.wordGap != null && FM.bounds;
    const mkLine = (idx) => {
      const words = idx.map((k) => {
        const fs = fsOf(k), sc = fs / FM.unitsPerEm;
        const gl = [...disps[k]];
        const b0 = FM.bounds ? FM.bounds[gl[0]] : null;
        const bL = FM.bounds ? FM.bounds[gl[gl.length - 1]] : null;
        const advLast = FM.advances[gl[gl.length - 1]] ?? FM.unitsPerEm * 0.5;
        return {
          k,
          wd: advPx(disps[k], fs),
          inkL: b0 ? b0[0] * sc : 0,
          inkRg: bL ? (advLast - bL[1]) * sc : 0,
        };
      });
      for (let i = 0; i < words.length; i++) {
        const w2 = words[i];
        if (i === 0) { w2.left = 0; continue; }
        const prev = words[i - 1];
        if (INK) {
          const gap = S.wordGap * (Math.max(fsOf(w2.k), fsOf(prev.k)) / S.size);
          w2.left = prev.left + prev.wd - prev.inkRg + gap - w2.inkL;
        } else {
          w2.left = prev.left + prev.wd + SPW * advPx(" ", Math.max(fsOf(w2.k), fsOf(prev.k)));
        }
      }
      const first = words[0], last = words[words.length - 1];
      const inkA = first.left + (INK ? first.inkL : 0);
      const inkB = last.left + last.wd - (INK ? last.inkRg : 0);
      return { words, w: inkB - inkA, inkA };
    };
    const all = seg.map((_, k) => k);
    let lines;
    if (mkLine(all).w <= MAXW || seg.length === 1) lines = [mkLine(all)];
    else {
      let best = null;
      for (let c = 1; c < seg.length; c++) {
        const l1 = mkLine(all.slice(0, c)), l2 = mkLine(all.slice(c));
        const m = Math.max(l1.w, l2.w);
        if (!best || m < best.m) best = { m, lines: [l1, l2] };
      }
      lines = best.lines;
    }

    // positionY = vertical CENTRE of line 1; the block grows downward, line advance scales
    // with the sizes of the two lines it separates (measured 0.70–0.85 em on the reference).
    // Mixed sizes share the LINE BASELINE (a small white word next to a big green one sits on
    // the same bottom, reference frame 91.4s) — with \an5 the anchor must be lowered by the
    // half-cell asymmetry of the size difference, hence the (S.size - fs) * OFF term.
    const pos = new Array(seg.length);
    const LHf = S.lineHeight ?? 0.78;
    const OFF = (FM.winAscent - FM.winDescent) / (2 * FM.unitsPerEm);
    let yC = S.positionY;
    for (let li = 0; li < lines.length; li++) {
      if (li > 0) {
        const up = Math.max(...lines[li - 1].words.map((w) => fsOf(w.k)));
        const dn = Math.max(...lines[li].words.map((w) => fsOf(w.k)));
        yC += (LHf * (up + dn)) / 2;
      }
      const off = POS_X - lines[li].w / 2 - lines[li].inkA;
      for (const { k, wd, left } of lines[li].words)
        pos[k] = { x: Math.round(off + left + wd / 2), y: Math.round(yC + (S.size - fsOf(k)) * OFF) };
    }

    const MINSTATE = 0.1;
    const appear = [];
    for (let k = 0; k < seg.length; k++) {
      const t0 = k === 0 ? seg[0].start : Math.max(seg[k].start, appear[k - 1] + MINSTATE);
      appear.push(t0);
    }
    // Dernier mot de carte : garanti visible >= lastHold avant la fin de carte. À 282 wpm
    // un « mois. » ou un « à » de fin de carte ne s'affichait que 60-200 ms = mot perçu
    // comme manquant (client A 28/08). Passe ARRIÈRE : on anticipe la queue de la carte sur
    // la parole (au plus maxEarly par mot, ce que fait Submagic) — jamais en retardant la
    // carte suivante, position fixe oblige.
    const LAST_HOLD = (S.appear && S.appear.lastHold) ?? 0.35;
    const MAX_EARLY = (S.appear && S.appear.maxEarly) ?? 0.25;
    for (let k = seg.length - 1; k >= 1; k--) {
      const want = k === seg.length - 1 ? cardEnd - LAST_HOLD : appear[k + 1] - MINSTATE;
      if (appear[k] > want) appear[k] = Math.max(want, seg[k].start - MAX_EARLY);
    }
    for (let k = 0; k < seg.length; k++) {
      if (k > 0) appear[k] = Math.max(appear[k], appear[k - 1] + MINSTATE);
      appear[k] = Math.min(appear[k], cardEnd - 0.05);
    }

    // Reveal mechanics (panneau Submagic « Claire 2 », preview fournie par un client) :
    //   - the CURRENT word renders in the MAIN weight (S.bold/boldStroke) ;
    //   - long words TYPE letter by letter (>= appear.typeMin chars), left-anchored so
    //     nothing shifts ; short words slide down + fade in (frame-by-frame ADS 1) ;
    //   - once the next word lands, a spoken white word DEMOTES to the secondary weight
    //     (TxtSec = plain Circular Medium, no synthetic bold) — greens stay green and big.
    // With the static ghost pre-show on (claire2-ghost), words are already placed: no
    // slide/typing, they snap ghost → full like the reference after a ghost hold.
    const AP = { slide: 0.45, ms: 150, fade: 100, typeMin: 6, typeMs: 28, demote: true, ...(S.appear || {}) };
    const GH_A = "&H" + Math.round((1 - GHOST.opacity) * 255).toString(16).toUpperCase().padStart(2, "0") + "&";
    for (let k = 0; k < seg.length; k++) {
      const isGreen = green.has(k);
      const st = isGreen ? "Green" : "Txt";
      const fs = fsOf(k);
      // boldStroke scales with the word size, so green (bigger) words keep the same
      // relative fattening as white ones.
      const bord = S.boldStroke ? `\\bord${((S.boldStroke * fs) / S.size).toFixed(1)}` : "";
      const tag = `\\an5\\fs${emFs(fs)}${bord}${FSP}`;
      const { x, y } = pos[k];
      const wd = advPx(disps[k], fs);
      if (inBroll) {
        // Carte entière pendant le cutaway : tous les mots dès le début de carte, graisse
        // principale du début à la fin, pas de fantôme/typewriter/slide/demote.
        ev += `Dialogue: 0,${ts(seg[0].start)},${ts(cardEnd)},Shd,,0,0,0,,{${tag}\\pos(${x + SH.depth},${y + SH.depth})\\blur${SH.blur}\\alpha${SH_ALPHA}}${disps[k]}\n`;
        ev += `Dialogue: 1,${ts(seg[0].start)},${ts(cardEnd)},${st},,0,0,0,,{${tag}\\pos(${x},${y})}${disps[k]}\n`;
        continue;
      }
      const g0 = Math.max(cardStart, appear[k] - GHOST.lead);
      if (appear[k] - g0 >= 0.01)
        ev += `Dialogue: 1,${ts(g0)},${ts(appear[k])},${st},,0,0,0,,{${tag}\\pos(${x},${y})\\alpha${GH_A}}${disps[k]}\n`;
      if (cardEnd - appear[k] < 0.01) continue;

      const settle = k + 1 < seg.length ? Math.min(appear[k + 1], cardEnd) : cardEnd;
      const demote = AP.demote && !isGreen && settle < cardEnd - 0.01;
      const boldEnd = demote ? settle : cardEnd;
      const glyphs = [...disps[k]];
      const anim = GHOST.opacity > 0 ? "hold" : glyphs.length >= AP.typeMin && !isGreen && !big.has(k) ? "type" : "slide";

      if (anim === "type") {
        // Letter-by-letter, left-anchored at the word's slot so glyphs never shift.
        const xL = Math.round(x - wd / 2);
        const typeDur = Math.min(AP.typeMs / 1000 * glyphs.length, 0.25, (boldEnd - appear[k]) * 0.6);
        const step = typeDur / glyphs.length;
        for (let c = 1; c <= glyphs.length; c++) {
          const t0 = appear[k] + (c - 1) * step;
          const t1 = c < glyphs.length ? appear[k] + c * step : boldEnd;
          const part = glyphs.slice(0, c).join("");
          ev += `Dialogue: 0,${ts(t0)},${ts(t1)},Shd,,0,0,0,,{\\an4\\fs${emFs(fs)}${bord}${FSP}\\pos(${xL + SH.depth},${y + SH.depth})\\blur${SH.blur}\\alpha${SH_ALPHA}}${part}\n`;
          ev += `Dialogue: 1,${ts(t0)},${ts(t1)},${st},,0,0,0,,{\\an4\\fs${emFs(fs)}${bord}${FSP}\\pos(${xL},${y})}${part}\n`;
        }
      } else {
        // Slide UP into place (retour un client 27/08 : le mot naît en dessous et monte).
        const dy = anim === "slide" ? Math.round(fs * AP.slide) : 0;
        const mv = dy
          ? { m: `\\move(${x},${y + dy},${x},${y},0,${AP.ms})\\fad(${AP.fade},0)`,
              s: `\\move(${x + SH.depth},${y + dy + SH.depth},${x + SH.depth},${y + SH.depth},0,${AP.ms})\\fad(${AP.fade},0)` }
          : { m: `\\pos(${x},${y})`, s: `\\pos(${x + SH.depth},${y + SH.depth})` };
        ev += `Dialogue: 0,${ts(appear[k])},${ts(boldEnd)},Shd,,0,0,0,,{${tag}${mv.s}\\blur${SH.blur}\\alpha${SH_ALPHA}}${disps[k]}\n`;
        ev += `Dialogue: 1,${ts(appear[k])},${ts(boldEnd)},${st},,0,0,0,,{${tag}${mv.m}}${disps[k]}\n`;
      }
      if (demote) {
        const secTag = `\\an5\\fs${emFs(fs)}${FSP}`;
        ev += `Dialogue: 0,${ts(boldEnd)},${ts(cardEnd)},ShdSec,,0,0,0,,{${secTag}\\pos(${x + SH.depth},${y + SH.depth})\\blur${SH.blur}\\alpha${SH_ALPHA}}${disps[k]}\n`;
        ev += `Dialogue: 1,${ts(boldEnd)},${ts(cardEnd)},TxtSec,,0,0,0,,{${secTag}\\pos(${x},${y})}${disps[k]}\n`;
      }
    }
    continue;
  }

  if (!KARAOKE) {
    // Reference behaviour (frame-by-frame study of ADS 2 HOOK 1, 27/08/2026): short cards
    // shown WHOLE that replace each other — no in-card accumulation. Box cards get either
    // a pop-in (short) or a typewriter reveal where the box grows with the text (long).
    const level = emphMap[si] || emphMap[String(si)] || "white";
    const a = seg[0].start;
    if (segEnd - a < 0.01) continue;

    if (level === "box") {
      const boost = EMPH.sizeBoost && EMPH.sizeBoost !== 1 ? `\\fs${Math.round(S.size * EMPH.sizeBoost)}` : "";
      // Le typewriter (boîte qui se déroule) est un trait du style William 2 UNIQUEMENT :
      // en reveal "card" (Jack 2) la boîte apparaît entière en pop (retour un client 28/08).
      if (plain.length <= 8 || !EMPH.animation || REVEAL === "card") {
        let fx = `\\an5\\pos(${POS_X},${POS_Y})${boost}`;
        if (EMPH.animation) fx += `\\fscx20\\fscy20\\frz-8\\t(0,${EMPH.animMs},\\fscx100\\fscy100\\frz0)`;
        ev += `Dialogue: 1,${ts(a)},${ts(segEnd)},Hl,,0,0,0,,{${fx}}${plain}\n`;
      } else {
        // Typewriter: ~1 glyph per 35ms, never longer than half the card's life. States
        // are CENTRE-anchored (the box grows symmetrically): left-anchoring needs the
        // final text width, and any estimate leaves the finished card off-centre.
        const fs = Math.round(S.size * (EMPH.sizeBoost || 1));
        const typeDur = Math.min(0.035 * plain.length, (segEnd - a) * 0.5, 0.8);
        const step = typeDur / plain.length;
        for (let k = 1; k <= plain.length; k++) {
          const t0 = a + (k - 1) * step;
          const t1 = k < plain.length ? a + k * step : segEnd;
          const part = plain.slice(0, k);
          if (part.trim() === "") continue;
          ev += `Dialogue: 1,${ts(t0)},${ts(t1)},Hl,,0,0,0,,{\\an5\\pos(${POS_X},${POS_Y})${boost ? `\\fs${fs}` : ""}}${part}\n`;
        }
      }
      continue;
    }

    if (REVEAL === "card") {
      // Style "Jack 2" (étude frame-by-frame de ADS 6 HOOK 3, 28/08/2026) : la carte
      // apparaît ENTIÈRE (pas de mot-à-mot), 2 lignes max centrées (\N + \an5), mots-clés
      // verts PAR MOT (emphasis = [wordIdx…]), entrée "letter spacing in" ~70 ms (tracking
      // légèrement serré qui s'ouvre — mesuré : largeur 95 % → 100 % en 2 frames). Le
      // stroke noir vit dans le style Txt (S.stroke), l'ombre douce dans la couche Shd.
      const green = new Set(Array.isArray(level) ? level : level === "green" ? seg.map((_, k) => k) : []);
      const disps2 = seg.map(disp);
      const accentInline = hexToAss(brand.colors.accent);
      const whiteInline = hexToAss(S.wordColor);
      const idx = seg.map((_, k) => k);
      let linesIdx = [idx];
      const MAXW = S.maxLineWidth ?? Math.round(brand.width * 0.72);
      // \fs = hauteur de CELLULE win, pas l'em : les avances se mesurent à l'em réel
      // (S.size / FSCALE), sinon tout paraît trop large et wrappe à tort.
      const emSz = S.size / (FSCALE || 1);
      if (FM) {
        const wAdv = (ids) => ids.reduce((n, k) => n + advPx(disps2[k], emSz), 0) + (ids.length - 1) * advPx(" ", emSz);
        if (wAdv(idx) > MAXW && seg.length > 1) {
          let best = null;
          for (let c = 1; c < seg.length; c++) {
            const m = Math.max(wAdv(idx.slice(0, c)), wAdv(idx.slice(c)));
            if (!best || m < best.m) best = { m, c };
          }
          linesIdx = [idx.slice(0, best.c), idx.slice(best.c)];
        }
      }
      const mkTxt = (ids) => ids.map((k) => (green.has(k) ? `{\\1c${accentInline}}${disps2[k]}{\\1c${whiteInline}}` : disps2[k])).join(" ");
      // Glow : couche sous le texte net, même couleur que chaque mot (\1c ET \3c), bordure
      // épaisse floutée = halo doux. C'est la « grosse ombre de la couleur du texte » de la
      // référence (pas de bordure noire sur ce style).
      const mkGlow = (ids) => ids.map((k) => (green.has(k)
        ? `{\\1c${accentInline}\\3c${accentInline}}${disps2[k]}{\\1c${whiteInline}\\3c${whiteInline}}`
        : disps2[k])).join(" ");
      const mkPlain = (ids) => ids.map((k) => disps2[k]).join(" ");
      const GLOW = S.glow ? { size: 5, blur: 6, opacity: 1, ...(typeof S.glow === "object" ? S.glow : {}) } : null;
      const GLOW_A = GLOW ? "&H" + Math.round((1 - GLOW.opacity) * 255).toString(16).toUpperCase().padStart(2, "0") + "&" : null;
      const IN = { ms: 70, spacing: -2.5, ...(S.intro || {}) };
      const intro = IN.ms > 0 ? `\\fsp${(S.letterSpacing ?? 0) + IN.spacing}\\t(0,${IN.ms},\\fsp${S.letterSpacing ?? 0})` : FSP;
      // 2 lignes = 2 événements positionnés (l'interligne \N suit la cellule de la police,
      // 1.76 em chez Poppins — bien trop aéré ; la référence est à ~1.05 em).
      const lineAdv = Math.round((S.lineHeight ?? 1.05) * emSz);
      const yOf = (li) => linesIdx.length === 1 ? POS_Y : POS_Y + Math.round((li - (linesIdx.length - 1) / 2) * lineAdv);
      for (let li = 0; li < linesIdx.length; li++) {
        ev += `Dialogue: 0,${ts(a)},${ts(segEnd)},Shd,,0,0,0,,{\\an5\\pos(${POS_X + SH.depth},${yOf(li) + SH.depth})\\blur${SH.blur}\\alpha${SH_ALPHA}${intro}}${mkPlain(linesIdx[li])}\n`;
        if (GLOW) ev += `Dialogue: 0,${ts(a)},${ts(segEnd)},Txt,,0,0,0,,{\\an5\\pos(${POS_X},${yOf(li)})\\bord${GLOW.size}\\3c${whiteInline}\\blur${GLOW.blur}\\alpha${GLOW_A}${intro}}${mkGlow(linesIdx[li])}\n`;
        ev += `Dialogue: 1,${ts(a)},${ts(segEnd)},Txt,,0,0,0,,{\\an5\\pos(${POS_X},${yOf(li)})${intro}}${mkTxt(linesIdx[li])}\n`;
      }
      continue;
    }

    // White/green cards: the WHOLE line is laid out from the first frame at its final,
    // fixed position — unspoken words are rendered fully transparent (\alpha&HFF&) and
    // flip to visible at their spoken time. Nothing ever shifts or re-centres; words
    // just appear in place, one after another (min 100ms apart so fast speech still
    // reads word by word).
    const style = level === "green" ? "Green" : "Txt";
    const MINSTATE = 0.1;
    const appear = [];
    for (let wi = 0; wi < seg.length; wi++) {
      let t0 = wi === 0 ? seg[0].start : Math.max(seg[wi].start, appear[wi - 1] + MINSTATE);
      appear.push(Math.min(t0, segEnd - 0.05));
    }
    const disps = seg.map(disp);
    for (let wi = 0; wi < seg.length; wi++) {
      const a2 = appear[wi];
      const b2 = wi + 1 < seg.length ? appear[wi + 1] : segEnd;
      if (b2 - a2 < 0.01) continue;
      const line = disps
        .map((d, j) => `{\\alpha${j <= wi ? "&H00&" : "&HFF&"}}${d}`)
        .join(" ");
      // Diffuse drop shadow = a second, blurred black copy UNDER the crisp text (ASS \shad
      // is a hard offset copy — the reference shadow is a soft halo). It follows the
      // word-by-word reveal with its own alpha states.
      const shLine = disps
        .map((d, j) => `{\\alpha${j <= wi ? SH_ALPHA : "&HFF&"}}${d}`)
        .join(" ");
      ev += `Dialogue: 0,${ts(a2)},${ts(b2)},Shd,,0,0,0,,{\\an5\\pos(${POS_X + SH.depth},${POS_Y + SH.depth})\\blur${SH.blur}}${shLine}\n`;
      ev += `Dialogue: 1,${ts(a2)},${ts(b2)},${style},,0,0,0,,{\\an5\\pos(${POS_X},${POS_Y})}${line}\n`;
    }
    continue;
  }

  for (let wi = 0; wi < seg.length; wi++) {
    const a = seg[wi].start;
    const b = wi + 1 < seg.length ? seg[wi + 1].start : segEnd;
    if (b - a < 0.01) continue;
    const line = seg.map((w, k) => `{${k === wi ? ACTIVE : IDLE}}${disp(w)}`).join(" ");
    if (S.box.enabled) {
      ev += `Dialogue: 0,${ts(a)},${ts(b)},Box,,0,0,0,,{\\an5\\pos(${POS_X},${POS_Y})\\blur${BLUR}}${plain}\n`;
    }
    ev += `Dialogue: 1,${ts(a)},${ts(b)},Txt,,0,0,0,,{\\an5\\pos(${POS_X},${POS_Y})}${line}\n`;
  }
}

// ASS alpha byte: 00 = fully opaque, FF = fully transparent.
const boxAlpha = Math.round((1 - S.box.opacity) * 255).toString(16).toUpperCase().padStart(2, "0");
const outlineNone = "&H00000000";
const shadowCol = "&H" + Math.round((1 - SH.opacity) * 255).toString(16).toUpperCase().padStart(2, "0") + "000000";
const edgeCol = "&HA0000000";     // faint dark edge that keeps white text readable on white
const accentAss = hexToAss(brand.colors.accent);
const emphTextAss = hexToAss(EMPH.textColor);

// Segment mode styles: Txt/Green = BorderStyle 1 (thin dark edge + drop shadow),
// Hl = BorderStyle 3 (Outline value becomes the box padding, OutlineColour the box fill).
const styles = KARAOKE
  ? `Style: Box,${S.family},${S.size},&HFF000000,&H00FFFFFF,&H${boxAlpha}000000,&H${boxAlpha}000000,0,0,0,0,100,100,1,0,3,14,0,5,40,40,0,1
Style: Txt,${S.family},${S.size},${hexToAss(S.wordColor)},${hexToAss(S.wordColor)},${outlineNone},${outlineNone},0,0,0,0,100,100,1,0,1,0,0,5,40,40,0,1`
  // S.bold = synthetic embolden (for a font with no heavy weight, e.g. Circular Std Medium).
  // S.boldStroke = same-colour outline in px on top of it: fattens the glyphs towards
  // Bold/Black while keeping the true letterforms. The Shd layer gets it in black so the
  // halo matches the fattened silhouette.
  // S.stroke = TRUE contour (style "Jack 2") : outline en px dans S.strokeColor (noir par
  // défaut), sur Txt ET Green ; la couche Shd le reçoit aussi pour que le halo épouse la
  // silhouette contourée. Prioritaire sur boldStroke (les deux ne se cumulent pas).
  : `Style: Txt,${S.family},${S.size},${hexToAss(S.wordColor)},${hexToAss(S.wordColor)},${S.stroke ? hexToAss(S.strokeColor || "#000000") : S.boldStroke ? hexToAss(S.wordColor) : edgeCol},${outlineNone},${S.bold ? -1 : 0},0,0,0,100,100,${LS},0,1,${S.stroke || S.boldStroke || 0},0,5,40,40,0,1
Style: Green,${S.family},${S.size},${accentAss},${accentAss},${S.stroke ? hexToAss(S.strokeColor || "#000000") : S.boldStroke ? accentAss : edgeCol},${outlineNone},${S.bold ? -1 : 0},0,0,0,100,100,${LS},0,1,${S.stroke || S.boldStroke || 0},0,5,40,40,0,1
Style: Shd,${S.family},${S.size},&H00000000,&H00000000,&H00000000,${outlineNone},${S.bold ? -1 : 0},0,0,0,100,100,${LS},0,1,${S.stroke || S.boldStroke || 0},0,5,40,40,0,1
Style: Hl,${S.family},${S.size},${emphTextAss},${emphTextAss},${EMPH.boxColor ? hexToAss(EMPH.boxColor) : accentAss},${shadowCol},${S.bold ? -1 : 0},0,0,0,100,100,${LS},0,3,${EMPH.pad},${SH.depth},5,40,40,0,1
Style: TxtSec,${S.family},${S.size},${hexToAss(S.wordColor)},${hexToAss(S.wordColor)},${outlineNone},${outlineNone},0,0,0,0,100,100,${LS},0,1,0,0,5,40,40,0,1
Style: ShdSec,${S.family},${S.size},&H00000000,&H00000000,${outlineNone},${outlineNone},0,0,0,0,100,100,${LS},0,1,0,0,5,40,40,0,1`;

const ass = `[Script Info]
ScriptType: v4.00+
PlayResX: ${brand.width}
PlayResY: ${brand.height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
${styles}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
${ev}`;

writeFileSync(OUT, ass, "utf8");
console.log(`segments=${segs.length} events=${ev.split("\n").filter(Boolean).length} mode=${KARAOKE ? "karaoke" : "segment"} font="${S.family}" pos=${POS_X},${POS_Y}`);
