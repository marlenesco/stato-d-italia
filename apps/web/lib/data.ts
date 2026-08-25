import "server-only";

type ReleaseObject = { key: string; logicalPath?: string; name: string };
type Manifest = { releaseId: string; releaseKey: string };
type Release = { releaseId: string; objects: ReleaseObject[] };

export type MapOption = {
  logicalPath: string;
  url: string;
  metricId: string;
  periodKey: string;
  level: "country" | "municipality" | "province" | "region";
};

export type SoilData = {
  releaseId: string;
  provenance: Record<string, unknown>;
  maps: MapOption[];
  rankings: Record<string, string>;
  geometry: Record<string, string>;
};

function root() {
  const value = process.env.NEXT_PUBLIC_DATA_BASE_URL?.replace(/\/$/, "");
  if (!value) throw new Error("NEXT_PUBLIC_DATA_BASE_URL mancante");
  return value;
}

async function fetchJson<T>(url: string, revalidate: number): Promise<T> {
  const response = await fetch(url, { next: { revalidate } });
  if (!response.ok) throw new Error(`Data fetch failed: ${response.status}`);
  return response.json() as Promise<T>;
}

async function fetchNoStore<T>(url: string): Promise<T> {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`Data fetch failed: ${response.status}`);
  return response.json() as Promise<T>;
}

async function activeRelease() {
  const base = root();
  const manifest = await fetchJson<Manifest>(`${base}/manifest.json`, 60);
  const release = await fetchJson<Release>(`${base}/${manifest.releaseKey}`, 300);
  if (release.releaseId !== manifest.releaseId) throw new Error("Manifest/release mismatch");
  return { base, release };
}

function asset(base: string, release: Release, logicalPath: string) {
  const object = release.objects.find((candidate) => candidate.logicalPath === logicalPath);
  if (!object) throw new Error(`Release asset missing: ${logicalPath}`);
  return `${base}/${object.key}`;
}

function parseMap(logicalPath: string, url: string): MapOption {
  const parts = logicalPath.split("/");
  return {
    logicalPath,
    url,
    metricId: parts[3],
    periodKey: parts[4],
    level: parts[5].replace(".json", "") as MapOption["level"],
  };
}

export async function loadSoilData(): Promise<SoilData> {
  const { base, release } = await activeRelease();
  const index = await fetchJson<{ maps: string[]; rankings: string[]; geometry: string[]; provenance: string }>(asset(base, release, "delivery/soil/index.json"), 300);
  const provenance = await fetchJson<Record<string, unknown>>(asset(base, release, index.provenance), 300);
  return {
    releaseId: release.releaseId,
    provenance,
    maps: index.maps.map((path) => parseMap(path, asset(base, release, path))),
    rankings: Object.fromEntries(index.rankings.map((path) => [path, asset(base, release, path)])),
    geometry: Object.fromEntries(index.geometry.map((path) => [path.match(/istat-(municipality|province|region)-2025/)?.[1] ?? "unknown", `${asset(base, release, path)}?release=${release.releaseId}`])),
  };
}

export async function loadWaterData(): Promise<SoilData> {
  const { base, release } = await activeRelease();
  const index = await fetchJson<{ maps: string[]; profiles: string[]; geometry: string[]; provenance: string }>(asset(base, release, "delivery/water/index.json"), 300);
  const provenance = await fetchJson<Record<string, unknown>>(asset(base, release, index.provenance), 300);
  return {
    releaseId: release.releaseId,
    provenance,
    maps: index.maps.map((path) => parseMap(path, asset(base, release, path))),
    rankings: {},
    geometry: { region: `${asset(base, release, index.geometry[0])}?release=${release.releaseId}` },
  };
}

export async function loadRomeProfile() {
  const { base, release } = await activeRelease();
  const logicalPath = "delivery/soil/profiles/municipality/058.json";
  const shard = await fetchNoStore<{ profiles: Array<Record<string, unknown>> }>(asset(base, release, logicalPath));
  const profile = shard.profiles.find((candidate) => (candidate.territory as { territoryId?: string }).territoryId === "it:municipality:058091");
  if (!profile) throw new Error("Roma profile absent from delivery shard");
  const provenance = await fetchJson<Record<string, unknown>>(asset(base, release, "delivery/soil/provenance.json"), 300);
  return { releaseId: release.releaseId, profile, provenance };
}
