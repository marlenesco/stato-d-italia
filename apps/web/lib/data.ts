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

export type Observation = { observationId: string; metricId: string; periodStart: string; periodEnd: string; value: number; unit: string };

type DerivedMetric = {
  metricId: string;
  algorithmVersion: string;
  changes?: Record<string, { status?: string | null; value?: number | null; unit?: string | null; reason?: string | null }>;
  trend?: { status?: string | null; direction?: string | null; slope_per_year?: number | null; unit?: string | null; reason?: string | null };
  benchmarks?: Record<string, { percentile?: number | null; percentileStatus?: string | null; rank?: number | null; rankStatus?: string | null }>;
};

export type TerritoryProfileData = {
  territory: { territoryId: string; name: string; level: "country" | "municipality" | "province" | "region"; istatCode: string; referenceDate: string; parents: Array<{ territoryId: string; name: string; level: string; istatCode: string }> };
  latestObservations: Observation[];
  historicalSeries: Array<{ metricId: string; columns: string[]; values: Array<[string, string, string, number, string]> }>;
  derivedMetrics: DerivedMetric[];
  comparisons: Record<string, Array<{ scope: string; status: string; territoryId?: string; observation?: Observation }>>;
  provenanceRef: string;
};

type Ranking = {
  algorithmVersion: string;
  metricId: string;
  periodStart: string;
  periodEnd: string;
  territoryLevel: string;
  rows: Array<{ territoryId: string; name: string; istatCode: string; value: number; percentile: number | null; rank: number | null }>;
};

type SoilIndex = { maps: string[]; rankings: string[]; geometry: string[]; provenance: string; profileShards: string[] };

export type SoilData = { releaseId: string; provenance: Record<string, unknown>; maps: MapOption[]; rankings: Record<string, string>; geometry: Record<string, string> };

export type HomeOverview = {
  releaseId: string;
  algorithmVersion: string;
  latestNet: Observation;
  previousChange: { status?: string | null; value?: number | null; unit?: string | null; reason?: string | null } | undefined;
  netSeries: Array<[string, string, string, number, string]>;
  watchRegions: Ranking["rows"];
  lowerChangeRegions: Ranking["rows"];
  periodKey: string;
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
  return { logicalPath, url, metricId: parts[3], periodKey: parts[4], level: parts[5].replace(".json", "") as MapOption["level"] };
}

async function soilRelease() {
  const { base, release } = await activeRelease();
  const index = await fetchJson<SoilIndex>(asset(base, release, "delivery/soil/index.json"), 300);
  return { base, release, index };
}

async function profileFromShard(base: string, release: Release, logicalPath: string, territoryId?: string) {
  const shard = await fetchJson<{ profiles: TerritoryProfileData[] }>(asset(base, release, logicalPath), 300);
  const profile = territoryId ? shard.profiles.find((candidate) => candidate.territory.territoryId === territoryId) : shard.profiles[0];
  if (!profile) throw new Error(`Territory profile absent from shard: ${logicalPath}`);
  return profile;
}

export async function loadSoilData(): Promise<SoilData> {
  const { base, release, index } = await soilRelease();
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
  const index = await fetchJson<{ maps: string[]; geometry: string[]; provenance: string }>(asset(base, release, "delivery/water/index.json"), 300);
  const provenance = await fetchJson<Record<string, unknown>>(asset(base, release, index.provenance), 300);
  return { releaseId: release.releaseId, provenance, maps: index.maps.map((path) => parseMap(path, asset(base, release, path))), rankings: {}, geometry: { region: `${asset(base, release, index.geometry[0])}?release=${release.releaseId}` } };
}

export async function loadHomeOverview(): Promise<HomeOverview> {
  const { base, release, index } = await soilRelease();
  const country = await profileFromShard(base, release, "delivery/soil/profiles/country/all.json");
  const latestNet = country.latestObservations.find((item) => item.metricId === "soil_net_consumption_hectares");
  const netSeries = country.historicalSeries.find((item) => item.metricId === "soil_net_consumption_hectares")?.values;
  const netAnalytics = country.derivedMetrics.find((item) => item.metricId === "soil_net_consumption_hectares");
  if (!latestNet || !netSeries) throw new Error("Home overview assets unavailable in active release");
  const periodKey = `${latestNet.periodStart.slice(0, 4)}-${latestNet.periodEnd.slice(0, 4)}`;
  const rankingPath = index.rankings.find((item) => item === `delivery/soil/rankings/soil_net_consumption_hectares/${periodKey}/region.json`);
  if (!rankingPath) throw new Error("Home overview ranking unavailable in active release");
  const ranking = await fetchJson<Ranking>(asset(base, release, rankingPath), 300);
  return { releaseId: release.releaseId, algorithmVersion: ranking.algorithmVersion, latestNet, previousChange: netAnalytics?.changes?.previous, netSeries, watchRegions: ranking.rows.slice(0, 5), lowerChangeRegions: [...ranking.rows].reverse().slice(0, 5), periodKey: `${ranking.periodStart.slice(0, 4)}–${ranking.periodEnd.slice(0, 4)}` };
}

export async function loadTerritoryProfile(level: "municipality" | "province" | "region" | "country", istatCode: string) {
  if (!/^[0-9A-Z]{2,6}$/.test(istatCode)) throw new Error("Codice ISTAT non valido");
  const { base, release, index } = await soilRelease();
  const shard = level === "municipality" ? istatCode.slice(0, 3) : level === "province" ? istatCode.slice(0, 2) : "all";
  const logicalPath = `delivery/soil/profiles/${level}/${shard}.json`;
  if (!index.profileShards.includes(logicalPath)) throw new Error(`Profile shard unavailable: ${logicalPath}`);
  const territoryId = level === "country" ? `it:country:${istatCode}` : `it:${level}:${istatCode}`;
  const profile = await profileFromShard(base, release, logicalPath, territoryId);
  const provenance = await fetchJson<Record<string, unknown>>(asset(base, release, index.provenance), 300);
  return { releaseId: release.releaseId, profile, provenance };
}

export async function loadRomeProfile() {
  return loadTerritoryProfile("municipality", "058091");
}
