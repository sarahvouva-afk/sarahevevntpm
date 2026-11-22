/**
 * spellfix — l'orthographe du SCRIPT fait foi dans les sous-titres (28/08/2026).
 *
 *   node spellfix.mjs <words.json> <script.txt> [out.json]
 *
 * Scribe transcrit à l'oreille : les accords muets du français sortent faux
 * (« les blocage inconscient », « de leur blocage transgénérationnel hérité »).
 * Le script étant la vérité orthographique, on aligne le transcript sur lui
 * (Needleman-Wunsch sur formes normalisées) et pour chaque paire alignée dont
 * les formes diffèrent PEU (accord/graphie, pas une vraie déviation de texte),
 * on reprend la graphie du script en préservant la ponctuation et la casse de
 * début de phrase du transcript (le phrasé réel vient de l'audio).
 * Un vrai écart (le speaker a dit autre chose) reste tel quel : on sous-titre
 * ce qui est DIT, pas ce qui était prévu.
 */
import { readFileSync, writeFileSync } from "node:fs";

const [wp, sp, op] = process.argv.slice(2);
if (!wp || !sp) { console.error("usage: node spellfix.mjs <words.json> <script.txt> [out.json]"); process.exit(1); }
const J = JSON.parse(readFileSync(wp, "utf8"));
const norm = (w) => w.toLowerCase().normalize("NFC").replace(/[^a-zàâäéèêëîïôöùûüç0-9']/g, "");
const S = readFileSync(sp, "utf8").split(/\s+/).filter(Boolean);
const T = J.words.map((w) => norm(w.text));
const Sn = S.map(norm);

// NW linéaire : le transcript vient d'un CUT déjà fidèle au script, pas de retakes —
// MIS > 2*GAP pour préférer la substitution (c'est elle qui porte les accords).
const m = T.length, n = Sn.length, MATCH = 2, MIS = -1, GAP = -1.25;
const dp = Array.from({ length: m + 1 }, () => new Float64Array(n + 1));
for (let i = 1; i <= m; i++) dp[i][0] = i * GAP;
for (let j = 1; j <= n; j++) dp[0][j] = j * GAP;
for (let i = 1; i <= m; i++)
  for (let j = 1; j <= n; j++)
    dp[i][j] = Math.max(dp[i-1][j-1] + (T[i-1] === Sn[j-1] ? MATCH : MIS), dp[i-1][j] + GAP, dp[i][j-1] + GAP);
const pairs = [];
let i = m, j = n;
while (i > 0 && j > 0) {
  if (dp[i][j] === dp[i-1][j-1] + (T[i-1] === Sn[j-1] ? MATCH : MIS)) { pairs.push([i-1, j-1]); i--; j--; }
  else if (dp[i][j] === dp[i-1][j] + GAP) i--;
  else j--;
}

// Seuls les accords MUETS se corrigent (même prononciation, graphie différente) : un
// écart audible = le speaker a réellement dit autre chose, on n'y touche pas (vécu :
// « n'était » ≠ « c'était », faux positif d'une règle par distance d'édition).
const phon = (w) => w
  .replace(/aient$/, "ait")        // imparfait/conditionnel pluriel
  .replace(/é(e|es|s)$/, "é")      // participes accordés
  .replace(/er$/, "é")             // infinitif / participe homophones (« demander » / « demandé »)
  .replace(/(s|x)$/, "");          // pluriel muet

// Ancrage : une substitution n'est digne de confiance que si un voisin immédiat est
// aligné EXACTEMENT (continuité diagonale). Sans ça, une phrase improvisée hors script
// s'apparie sur une occurrence lointaine du même mot et la « correction » va à l'envers
// (vécu : « leurs blocages transgénérationnels » ad-lib appariés sur « ce blocage
// enfoui » du script).
const sOf = new Map(pairs.map(([a, b]) => [a, b]));
const isExact = (a) => sOf.has(a) && T[a] === Sn[sOf.get(a)];

let fixed = 0;
for (const [ti, sj] of pairs) {
  const t = T[ti], s = Sn[sj];
  if (!t || !s || t === s) continue;
  if (phon(t) !== phon(s)) continue;
  if (!((sOf.get(ti - 1) === sj - 1 && isExact(ti - 1)) ||
        (sOf.get(ti + 1) === sj + 1 && isExact(ti + 1)))) continue;
  const raw = J.words[ti].text;
  const lead = (raw.match(/^[«"('‘“]+/) || [""])[0];
  const trail = (raw.match(/[»")',.:;!?…’”]+$/) || [""])[0];
  let core = S[sj].replace(/^[«"('‘“]+/, "").replace(/[»")',.:;!?…’”]+$/, "");
  // la casse de début de phrase vient du transcript (phrasé réel de l'audio)
  core = /^[A-ZÀÂÉÈÊËÎÏÔÖÙÛÜ]/.test(raw)
    ? core.charAt(0).toUpperCase() + core.slice(1)
    : core.charAt(0).toLowerCase() + core.slice(1);
  const next = lead + core + trail;
  if (next !== raw) { J.words[ti].text = next; fixed++; }
}
// Quasi-homophones multi-mots (08/09/2026, ADS3 client A : Scribe écrit « nous ait » pour
// « n'osait », le sous-titre affichait la faute). Entre deux ancrages EXACTS, si ≤ 3 mots
// du transcript font face à ≤ 3 mots du script et que les deux chaînes collées (sans
// apostrophes ni espaces) sont à ≤ 1 lettre près, c'est une confusion d'oreille : on
// reprend les mots du script, les temps couvrent l'ensemble. Un vrai écart (> 1 lettre)
// reste tel quel.
const flat = (ws) => ws.join("").replace(/'/g, "");
const lev = (x, y) => { const d = Array.from({ length: x.length + 1 }, (_, i) => [i, ...Array(y.length).fill(0)]); for (let j = 1; j <= y.length; j++) d[0][j] = j;
  for (let i = 1; i <= x.length; i++) for (let j = 1; j <= y.length; j++) d[i][j] = Math.min(d[i-1][j] + 1, d[i][j-1] + 1, d[i-1][j-1] + (x[i-1] === y[j-1] ? 0 : 1)); return d[x.length][y.length]; };
const exactT = new Set(pairs.filter(([a, b]) => T[a] === Sn[b]).map(([a]) => a));
const anchors = [...exactT].sort((x, y) => x - y);
let phrases = 0;
const dropped = new Set();
for (let k = 0; k + 1 < anchors.length; k++) {
  const a0 = anchors[k], a1 = anchors[k + 1];
  const s0 = sOf.get(a0), s1 = sOf.get(a1);
  const tIdx = []; for (let x = a0 + 1; x < a1; x++) tIdx.push(x);
  const sIdx = []; for (let y = s0 + 1; y < s1; y++) sIdx.push(y);
  if (!tIdx.length || !sIdx.length || tIdx.length > 3 || sIdx.length > 3) continue;
  const ft = flat(tIdx.map((x) => T[x])), fs = flat(sIdx.map((y) => Sn[y]));
  if (ft === fs || !ft || !fs || lev(ft, fs) > 1) continue;
  // remplacement : le 1er mot du transcript porte tout le texte du script, les autres sont retirés
  const first = J.words[tIdx[0]], last = J.words[tIdx[tIdx.length - 1]];
  const raw = first.text;
  const lead = (raw.match(/^[«"('‘“]+/) || [""])[0];
  const trail = (last.text.match(/[»")',.:;!?…’”]+$/) || [""])[0];
  let core = sIdx.map((y) => S[y]).join(" ").replace(/^[«"('‘“]+/, "").replace(/[»")',.:;!?…’”]+$/, "");
  core = /^[A-ZÀÂÉÈÊËÎÏÔÖÙÛÜ]/.test(raw) ? core.charAt(0).toUpperCase() + core.slice(1) : core.charAt(0).toLowerCase() + core.slice(1);
  first.text = lead + core + trail; first.end = last.end;
  for (const x of tIdx.slice(1)) dropped.add(x);
  phrases++;
}
if (dropped.size) J.words = J.words.filter((_, idx) => !dropped.has(idx));
writeFileSync(op || wp, JSON.stringify(J, null, 1));
console.log(`[spellfix] ${fixed} graphie(s) + ${phrases} quasi-homophone(s) repris du script -> ${op || wp}`);
