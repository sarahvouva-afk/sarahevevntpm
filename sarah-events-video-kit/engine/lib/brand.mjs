/**
 * Brand loader — reads brand.json once and hands typed, defaulted values to every engine.
 *
 * Every engine script imports this instead of hardcoding a colour, a font or a dimension.
 * Missing keys fall back to the defaults below, so a half-filled brand.json still runs.
 */
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve, isAbsolute } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
export const PACK_ROOT = resolve(HERE, "..", "..");

const FORMATS = {
  "9:16": { width: 1080, height: 1920 },
  "16:9": { width: 1920, height: 1080 },
};

const DEFAULTS = {
  format: "9:16",
  colors: { background: "#F4EFE4", accent: "#F59E0B", text: "#111111" },
  fonts: {
    heading: { family: "Cabinet Grotesk Extrabold", file: "fonts/heading.ttf" },
    body: { family: "General Sans", file: "fonts/body.woff2" },
  },
  subtitles: {
    family: null,          // null → falls back to fonts.heading.family
    file: null,            // null → falls back to fonts.heading.file
    size: 70,
    case: "natural",       // "natural" | "upper"
    activeWordColor: null, // null → colors.accent
    wordColor: "#FFFFFF",
    box: { enabled: true, opacity: 0.8, blur: 6 },
    positionY: null,       // null → computed from the montage junction, or 82% of height
    maxWords: 3,
    maxChars: 16,
    replacements: {},
  },
  montage: { topHeight: 760, junctionStart: 770, junctionHeight: 60, faceCrop: null },
  audio: { loudness: -14, truePeak: -1.5, range: 11 },
  transcription: { provider: "scribe", language: "fra" },
  cut: { lead: 0.045, trail: 0.02 },
};

function isPlainObject(v) {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

function deepMerge(base, override) {
  if (!isPlainObject(override)) return base;
  const out = { ...base };
  for (const [k, v] of Object.entries(override)) {
    out[k] = isPlainObject(v) && isPlainObject(base[k]) ? deepMerge(base[k], v) : v;
  }
  return out;
}

/**
 * "#F59E0B" → "&H000B9EF5" (ASS is BGR with a leading alpha byte).
 * Style lines take this form as-is; inline overrides need a trailing "&" — use assInline().
 */
export function hexToAss(hex, alpha = 0) {
  const m = /^#?([0-9a-f]{6})$/i.exec(String(hex).trim());
  if (!m) throw new Error(`brand: invalid hex colour "${hex}" (expected #RRGGBB)`);
  const [r, g, b] = [0, 2, 4].map((i) => m[1].slice(i, i + 2).toUpperCase());
  const a = Math.round(Math.min(Math.max(alpha, 0), 1) * 255)
    .toString(16).toUpperCase().padStart(2, "0");
  return `&H${a}${b}${g}${r}`;
}

/** Inline colour override for an ASS event: "#F59E0B" → "\\c&H0B9EF5&". */
export function assInline(hex) {
  return `\\c&H${hexToAss(hex).slice(4)}&`;
}

/** Resolve a brand-relative path (fonts/x.ttf) against the pack root. */
export function packPath(p) {
  if (!p) return null;
  return isAbsolute(p) ? p : join(PACK_ROOT, p);
}

/**
 * A style file may declare `extends: "../brand.json"` (path relative to itself): the parent
 * is loaded first and the child overrides it. This is how one client carries many subtitle
 * styles without duplicating montage/audio/cut config. Chains are allowed, cycles are not.
 */
function readBrandFile(file, seen = new Set(), from = null) {
  if (seen.has(file)) throw new Error(`brand: circular extends chain at ${file}`);
  seen.add(file);
  let user = {};
  // Une cible `extends` introuvable n'est JAMAIS un cas normal : avant le 06/09/2026 elle
  // retombait silencieusement sur {} (chemin absolu d'une autre machine dans un override lu sur le
  // MacBook → police, style, compression et replacements du client perdus, ADS4 rendue avec
  // les DEFAULTS du pack sans un mot d'erreur). Seul le fichier racine absent reste toléré.
  if (from && !existsSync(file)) {
    throw new Error(`brand: extends introuvable : ${file} (depuis ${from}). Utiliser un chemin RELATIF au fichier (ex. ../../clients/<client>/brand.json), jamais un chemin absolu d'une autre machine.`);
  }
  if (existsSync(file)) {
    try {
      user = JSON.parse(readFileSync(file, "utf8"));
    } catch (e) {
      throw new Error(`brand: ${file} is not valid JSON — ${e.message}`);
    }
  }
  if (user.extends) {
    const parent = readBrandFile(resolve(dirname(file), user.extends), seen, file);
    const { extends: _x, ...child } = user;
    return deepMerge(parent, child);
  }
  return user;
}

export function loadBrand(explicitPath) {
  const file = explicitPath ? resolve(explicitPath) : join(PACK_ROOT, "brand.json");
  const user = readBrandFile(file);
  const b = deepMerge(DEFAULTS, user);

  const dims = FORMATS[b.format];
  if (!dims) {
    throw new Error(`brand: format "${b.format}" is not supported (use "9:16" or "16:9")`);
  }
  b.width = dims.width;
  b.height = dims.height;
  b.scale = `${dims.width}:${dims.height}`;

  // Subtitle fallbacks — a user who only set fonts.heading still gets coherent subtitles.
  const s = b.subtitles;
  s.family ||= b.fonts.heading.family;
  s.file ||= b.fonts.heading.file;
  s.activeWordColor ||= b.colors.accent;
  if (s.positionY == null) {
    s.positionY = b.montage.junctionStart != null && b.format === "9:16"
      ? b.montage.junctionStart + Math.round(b.montage.junctionHeight / 2)
      : Math.round(b.height * 0.82);
  }
  s.fontPath = packPath(s.file);
  s.fontsDir = s.fontPath ? dirname(s.fontPath) : join(PACK_ROOT, "fonts");

  return b;
}

export default loadBrand;
