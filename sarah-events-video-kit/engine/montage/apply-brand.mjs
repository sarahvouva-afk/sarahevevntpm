/**
 * apply-brand — pushes brand.json into a composition's CSS variables.
 *
 *   node engine/montage/apply-brand.mjs <compo.html> [--brand brand.json]
 *
 * Rewrites everything between the BRAND:START and BRAND:END markers, in place.
 * Run it after editing brand.json, or after copying template.html into a new composition.
 */
import { readFileSync, writeFileSync, existsSync, copyFileSync } from "node:fs";
import { basename, join, resolve } from "node:path";
import { loadBrand, packPath } from "../lib/brand.mjs";

const args = process.argv.slice(2);
const file = args.find((a) => !a.startsWith("--"));
const brandIdx = args.indexOf("--brand");
if (!file) {
  console.error("usage: node apply-brand.mjs <compo.html> [--brand brand.json]");
  process.exit(1);
}
if (!existsSync(file)) { console.error(`apply-brand: ${file} not found`); process.exit(1); }

const b = loadBrand(brandIdx !== -1 ? args[brandIdx + 1] : undefined);
const html = readFileSync(file, "utf8");

const START = "/* BRAND:START";
const END = "/* BRAND:END */";
const iStart = html.indexOf(START);
const iEnd = html.indexOf(END);
if (iStart === -1 || iEnd === -1 || iEnd < iStart) {
  console.error("apply-brand: markers BRAND:START / BRAND:END not found — is this a kit composition?");
  process.exit(1);
}

// @font-face rules so the composition renders with the user's own fonts, offline.
const faces = [];
for (const [role, f] of Object.entries(b.fonts)) {
  const abs = packPath(f.file);
  if (!abs || !existsSync(abs)) {
    console.warn(`apply-brand: font file missing for "${role}" (${f.file}) — falling back to a system font`);
    continue;
  }
  // The composition is rendered from its own directory, so copy the font next to it.
  const local = join(resolve(file, ".."), basename(abs));
  if (resolve(local) !== resolve(abs)) copyFileSync(abs, local);
  const fmt = abs.endsWith(".woff2") ? "woff2" : abs.endsWith(".otf") ? "opentype" : "truetype";
  faces.push(`@font-face{font-family:"${f.family}";src:url("${basename(abs)}") format("${fmt}");font-display:block}`);
}

const block = `${START} — rewritten by apply-brand.mjs from brand.json, do not edit by hand */
${faces.join("\n")}
:root{
  --bg:${b.colors.background};
  --accent:${b.colors.accent};
  --text:${b.colors.text};
  --font-heading:"${b.fonts.heading.family}";
  --font-body:"${b.fonts.body.family}";
}
html,body{width:${b.width}px;height:${b.format === "9:16" ? b.montage.topHeight : b.height}px}
${END}`;

writeFileSync(file, html.slice(0, iStart) + block + html.slice(iEnd + END.length), "utf8");
console.log(`[apply-brand] ${file} ← bg ${b.colors.background}, accent ${b.colors.accent}, ${faces.length} police(s) embarquée(s)`);
