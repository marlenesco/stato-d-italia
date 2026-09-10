import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER, PHASE_PRODUCTION_BUILD } from "next/constants";
import path from "node:path";
import { copyFileSync, mkdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";


const nextConfig: NextConfig = {
  reactStrictMode: true,
  turbopack: { root: path.resolve(__dirname) },
  allowedDevOrigins: ["127.0.0.1"],
};

export default function config(phase: string): NextConfig {
  if (phase === PHASE_DEVELOPMENT_SERVER || phase === PHASE_PRODUCTION_BUILD) {
    // MapLibre's ESM worker and its relative import must survive bundling together.
    const requireFromApp = createRequire(path.join(__dirname, "package.json"));
    const maplibrePackage = requireFromApp.resolve("maplibre-gl/package.json");
    const { version } = JSON.parse(readFileSync(maplibrePackage, "utf8"));
    const workerDirectory = path.join(__dirname, "public/vendor/maplibre", version);
    mkdirSync(workerDirectory, { recursive: true });
    for (const file of ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"]) {
      copyFileSync(path.join(path.dirname(maplibrePackage), "dist", file), path.join(workerDirectory, file));
    }
  }
  return nextConfig;
}
