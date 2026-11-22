/**
 * encoder — sélection d'encodeur vidéo (perf, 28/08/2026).
 *
 * h264_videotoolbox = media engine Apple (circuit dédié, CPU quasi libre, 3-5x plus
 * rapide que libx264 medium). Légèrement moins efficace à qualité égale → q:v 62 vise
 * le même rendu visuel que crf 18-22 en généreux sur le débit (les ads partent sur Meta
 * qui ré-encode de toute façon).
 *
 * brand.render.encoder : "libx264" (défaut) | "videotoolbox" | "auto".
 * "auto"/"videotoolbox" retombent sur libx264 si l'encodeur n'existe pas dans le ffmpeg
 * courant (le statique du kit l'inclut sur macOS, mais on ne présume rien).
 */
import { execSync } from "node:child_process";

let hasVT;
export function vtArgs(render = {}) {
  const pref = render.encoder || "libx264";
  if (pref !== "videotoolbox" && pref !== "auto") return null;
  if (hasVT === undefined) {
    try {
      hasVT = execSync("ffmpeg -hide_banner -encoders", { stdio: ["ignore", "pipe", "pipe"] })
        .toString().includes("h264_videotoolbox");
    } catch { hasVT = false; }
  }
  if (!hasVT) return null;
  return ["-c:v", "h264_videotoolbox", "-q:v", String(render.vtQuality ?? 62), "-allow_sw", "1"];
}
