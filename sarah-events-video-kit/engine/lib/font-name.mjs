/**
 * Read a font's INTERNAL family name, with zero dependency.
 *
 *   node engine/lib/font-name.mjs fonts/heading.ttf
 *
 * This exists because the `family` you put in brand.json must be the name written INSIDE the
 * font file, not the name of the file. Get it wrong and libass silently falls back to some
 * other font: the video renders, the subtitles just look nothing like what you chose. It is the
 * single most common way to waste an hour on this kit, so the kit reads it for you.
 *
 * Parses the OpenType `name` table directly (spec: docs.microsoft.com/typography/opentype/spec/name).
 * Handles .ttf and .otf. A .woff2 is rejected on sight — libass cannot read one anyway.
 */
import { readFileSync } from "node:fs";

const NAME_FAMILY = 1;      // "Font Family name" — what libass matches on
const NAME_SUBFAMILY = 2;   // "Regular", "Bold", "Extrabold"…
const NAME_FULL = 4;        // full human name
const NAME_TYPO_FAMILY = 16; // "Typographic Family", when the family is split across files

/** @returns {{family:string, subfamily:string|null, full:string|null, typographic:string|null}} */
export function readFontNames(file) {
  const buf = readFileSync(file);
  if (buf.length < 12) throw new Error(`fichier trop court pour être une police : ${file}`);

  const tag = buf.toString("ascii", 0, 4);
  if (tag === "wOFF" || tag === "wOF2") {
    throw new Error(
      `${file} est un woff/woff2. libass ne lit que du .ttf ou du .otf — convertis-le, voir fonts/README.md.`
    );
  }
  if (tag === "ttcf") {
    // font collection: jump to the first font's table directory
    return readTableDirectory(buf, buf.readUInt32BE(12));
  }
  return readTableDirectory(buf, 0);
}

function readTableDirectory(buf, base) {
  const numTables = buf.readUInt16BE(base + 4);
  let nameOffset = null;
  for (let i = 0; i < numTables; i++) {
    const rec = base + 12 + i * 16;
    if (buf.toString("ascii", rec, rec + 4) === "name") {
      nameOffset = buf.readUInt32BE(rec + 8);
      break;
    }
  }
  if (nameOffset == null) throw new Error("cette police n'a pas de table `name`, elle est probablement corrompue.");
  return readNameTable(buf, nameOffset);
}

function readNameTable(buf, off) {
  const count = buf.readUInt16BE(off + 2);
  const storage = off + buf.readUInt16BE(off + 4);
  /** best candidate per nameID — a Windows/Unicode record beats a Mac one */
  const best = new Map();

  for (let i = 0; i < count; i++) {
    const rec = off + 6 + i * 12;
    const platformID = buf.readUInt16BE(rec);
    const encodingID = buf.readUInt16BE(rec + 2);
    const nameID = buf.readUInt16BE(rec + 6);
    const length = buf.readUInt16BE(rec + 8);
    const offset = buf.readUInt16BE(rec + 10);
    if (![NAME_FAMILY, NAME_SUBFAMILY, NAME_FULL, NAME_TYPO_FAMILY].includes(nameID)) continue;

    const slice = buf.subarray(storage + offset, storage + offset + length);
    // platform 3 (Windows) and platform 0 (Unicode) store UTF-16BE; platform 1 (Mac) is single byte
    const value = platformID === 1 ? slice.toString("latin1") : slice.toString("utf16le").length
      ? decodeUtf16be(slice)
      : slice.toString("latin1");

    const rank = platformID === 3 ? 3 : platformID === 0 ? 2 : 1;
    const prev = best.get(nameID);
    if (!prev || rank > prev.rank) best.set(nameID, { value: value.replace(/\0/g, "").trim(), rank });
  }

  const get = (id) => (best.get(id)?.value || null);
  const family = get(NAME_FAMILY);
  if (!family) throw new Error("nom de famille introuvable dans la police.");
  return {
    family,
    subfamily: get(NAME_SUBFAMILY),
    full: get(NAME_FULL),
    typographic: get(NAME_TYPO_FAMILY),
  };
}

function decodeUtf16be(slice) {
  let out = "";
  for (let i = 0; i + 1 < slice.length; i += 2) out += String.fromCharCode((slice[i] << 8) | slice[i + 1]);
  return out;
}

// CLI
if (process.argv[1] && import.meta.url.endsWith(process.argv[1].replace(/\\/g, "/").split("/").pop())) {
  const file = process.argv[2];
  if (!file) {
    console.error("usage : node engine/lib/font-name.mjs <police.ttf>");
    process.exit(1);
  }
  try {
    const n = readFontNames(file);
    console.log(`\n  Nom à mettre dans brand.json → "family": "${n.family}"\n`);
    if (n.typographic && n.typographic !== n.family) {
      console.log(`  (famille typographique : ${n.typographic} · style : ${n.subfamily || "?"})`);
      console.log(`  Si les sous-titres ne s'affichent pas avec "${n.family}", essaie "${n.typographic}".\n`);
    } else if (n.subfamily) {
      console.log(`  (style : ${n.subfamily})\n`);
    }
  } catch (e) {
    console.error(`\n  ${e.message}\n`);
    process.exit(1);
  }
}

export default readFontNames;
