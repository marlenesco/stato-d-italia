import "server-only";
import { DOMAIN_CAPABILITIES, type DataKind, type DomainId, type TemporalMode, type TerritoryLevel } from "./domain-capabilities";

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

export type TerritoryIdentity = {
  territoryId: string;
  territoryVersionId: string;
  name: string;
  level: TerritoryLevel;
  istatCode: string;
  referenceDate: string;
  parents: Array<{ territoryId: string; territoryVersionId?: string; name: string; level: string; istatCode: string }>;
};

export type SoilTerritoryProfile = {
  territory: TerritoryIdentity;
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

type SoilIndex = { maps: string[]; rankings: string[]; geometry: string[]; mapGeometry?: Record<string, string>; provenance: string; profileShards: string[] };

export type SoilData = { releaseId: string; provenance: Record<string, unknown>; maps: MapOption[]; rankings: Record<string, string>; geometry: Record<string, string>; mapGeometry?: Record<string, string> };

export type WaterObservation = { metricId: string; periodEnd: string; value: number; unit: string };
export type WaterProfile = {
  territory?: { territoryId: string; territoryVersionId: string; level: TerritoryLevel };
  kind?: "derived_metric_profile";
  officialStatus?: "derived_by_stato_italia";
  latestObservations: WaterObservation[];
  historicalSeries: Array<{ metricId: string; values: Array<[number, number]>; points?: Array<{ referenceYear: number; value: number; territoryGeometryReference?: string; territoryVersionId?: string; methodologyReference?: string }> ; comparison?: TerritoryComparison }>;
  territoryGeometryReferences?: string[];
};

export type WaterData = SoilData & { profileUrls: Record<string, string> };
export type WaterOverview = { releaseId: string; countryProfile: WaterProfile };
export type DissestoData = SoilData;
export type ForestData = SoilData;
export type EmissionsOverview = {
  releaseId: string;
  greenhouseGases: { label: string; coverage: string; unit: string; seriesLabel: string; series: Array<[number, number]>; metrics: string[] };
  airPollutantsNfr: { label: string; coverage: string; metrics: number; sourceDimensions: string[] };
  provincialDisaggregation: { label: string; coverage: string; metrics: number; sourceDimensions: string[] };
  map?: { metricId: string; snapCode: string; label: string; detail: string; coverage: string; periods: number[]; territoryLevel: "province" };
  provenanceRef: string;
};
export type EmissionsNationalSeries = { id: string; metricId: string; metricLabel: string; dimensionCode: string; dimensionLabel: string; sourceUnit: string; unit: string; values: Array<[number, number]> };
export type EmissionsNationalDataset = { kind: "official_national_series"; series: EmissionsNationalSeries[] };
export type EmissionsProvincialCombination = { id: string; metricId: string; pollutantCode: string; pollutantLabel: string; snapCode: string; snapLabel: string; unit: string; mapPaths: Record<string, string> };
export type EmissionsData = { overview: EmissionsOverview; nationalUrls: { greenhouseGases: string; airPollutantsNfr: string }; provincial: EmissionsProvincialCombination[]; geometryByPeriod: Record<string, string> };

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

export type HomeDomainSignal = {
  id: "soil" | "water" | "forests" | "emissions" | "risk";
  title: string;
  label: string;
  displayValue: string;
  unit: string;
  period: string;
  note: string;
  href: string;
  status: "available" | "unavailable";
  kind: "official" | "modelled" | "derived";
};

export type TerritoryInsightPoint = {
  metricId?: string;
  periodStart: string;
  periodEnd: string;
  value: number;
  unit: string;
  geometryReference?: string;
  methodologyReference?: string;
};
export type ComparisonReason = "single_snapshot" | "missing_previous_period" | "geometry_changed" | "methodology_changed" | "unit_changed" | "comparison_not_supported" | "different_metric" | "not_in_published_coverage" | "source_not_published_at_this_level";
export type TerritoryComparison = { status: "available" | "unavailable"; direction?: "improving" | "worsening" | "changed" | "stable"; delta?: number; percent?: number; from?: string; to?: string; reason?: ComparisonReason };
type TerritoryInsightDomainId = DomainId;

type TerritoryDomainInsightBase = {
  id: TerritoryInsightDomainId;
  title: string;
};

export type TerritoryDomainInsight = TerritoryDomainInsightBase & ({
  availability: "unavailable";
  reason: "source_not_published_at_this_level" | "not_in_published_coverage";
} | {
  availability: "available";
  id: "soil" | "water" | "forests" | "risk" | "emissions";
  label: string;
  source: string;
  kind: "official_observation" | "official_model" | "derived_metric";
  latest: TerritoryInsightPoint;
  series: TerritoryInsightPoint[];
  comparison: TerritoryComparison;
  href: string;
  groups?: Array<{ id: string; title: string; kind: DataKind; source: string; metrics: Array<{ label: string; series: TerritoryInsightPoint[] }> }>;
  snapshots?: Array<{ family: "Alluvioni" | "Frane"; metricId: string; label: string; latest: TerritoryInsightPoint; series: TerritoryInsightPoint[] }>;
});

export type TerritoryDomainProfile = {
  id: DomainId;
  title: string;
  availability: "available" | "unavailable";
  reason?: "source_not_published_at_this_level" | "not_in_published_coverage";
  dataKind: DataKind;
  temporal: TemporalMode;
  source: string;
  label?: string;
  latest?: TerritoryInsightPoint;
  series?: TerritoryInsightPoint[];
  comparison?: TerritoryComparison;
  href: string;
  geometryReferences?: string[];
  groups?: Extract<TerritoryDomainInsight, { availability: "available" }>["groups"];
  snapshots?: Extract<TerritoryDomainInsight, { availability: "available" }>["snapshots"];
  detail?: { kind: "soil"; profile: SoilTerritoryProfile } | { kind: "water"; profile: WaterProfile };
};

export type TerritoryProfile = {
  territory: TerritoryIdentity;
  domains: TerritoryDomainProfile[];
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

async function optionalAssetJson(base: string, release: Release, logicalPath: string) {
  return release.objects.some((item) => item.logicalPath === logicalPath)
    ? fetchJson<Record<string, unknown>>(asset(base, release, logicalPath), 300)
    : null;
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

async function waterRelease() {
  const { base, release } = await activeRelease();
  const index = await fetchJson<{ maps: string[]; geometry: string[]; mapGeometry?: Record<string, string>; provenance: string; profiles?: string[] }>(asset(base, release, "delivery/water/index.json"), 300);
  return { base, release, index };
}

async function dissestoRelease() {
  const { base, release } = await activeRelease();
  const index = await fetchJson<SoilIndex>(asset(base, release, "delivery/dissesto/index.json"), 300);
  return { base, release, index };
}

async function forestsRelease() {
  const { base, release } = await activeRelease();
  const index = await fetchJson<SoilIndex>(asset(base, release, "delivery/foreste/index.json"), 300);
  return { base, release, index };
}

async function emissionsRelease() {
  const { base, release } = await activeRelease();
  const index = await fetchJson<{ overview: string; provenance: string; national: { greenhouseGases: string; airPollutantsNfr: string }; provincialCatalog: string; geometry?: string[] }>(asset(base, release, "delivery/emissions/index.json"), 300);
  return { base, release, index };
}

function geometryUrls(base: string, release: Release, paths: string[]) {
  return Object.fromEntries(paths.map((path) => [path.match(/istat-(municipality|province|region)-\d{4}/)?.[1] ?? "unknown", `${asset(base, release, path)}?release=${release.releaseId}`]));
}

async function profileFromShard(base: string, release: Release, logicalPath: string, territoryId?: string) {
  const shard = await fetchJson<{ profiles: SoilTerritoryProfile[] }>(asset(base, release, logicalPath), 300);
  const profile = territoryId ? shard.profiles.find((candidate) => candidate.territory.territoryId === territoryId) : shard.profiles[0];
  if (!profile) throw new Error(`Territory profile absent from shard: ${logicalPath}`);
  return profile;
}

async function profileFromShards(base: string, release: Release, logicalPaths: string[], territoryId: string) {
  const shards = await Promise.all(logicalPaths.map((logicalPath) => fetchJson<{ profiles: SoilTerritoryProfile[] }>(asset(base, release, logicalPath), 300)));
  const profile = shards.flatMap((shard) => shard.profiles).find((candidate) => candidate.territory.territoryId === territoryId);
  if (!profile) throw new Error(`Territory profile absent from shards: ${territoryId}`);
  return profile;
}

type TerritoryInsightsShard = { profiles: Array<{ territoryId: string; domains: TerritoryDomainInsight[] }> };

async function loadTerritoryInsights(base: string, release: Release, level: "municipality" | "province" | "region", istatCode: string, territoryId: string) {
  const shard = level === "municipality" ? istatCode.slice(0, 3) : "all";
  const logicalPath = `delivery/territory-insights/${level}/${shard}.json`;
  if (!release.objects.some((item) => item.logicalPath === logicalPath)) return [];
  const payload = await fetchJson<TerritoryInsightsShard>(asset(base, release, logicalPath), 300);
  return payload.profiles.find((profile) => profile.territoryId === territoryId)?.domains ?? [];
}

export async function loadSoilData(): Promise<SoilData> {
  const { base, release, index } = await soilRelease();
  const provenance = await fetchJson<Record<string, unknown>>(asset(base, release, index.provenance), 300);
  return {
    releaseId: release.releaseId,
    provenance,
    maps: index.maps.map((path) => parseMap(path, asset(base, release, path))),
    rankings: Object.fromEntries(index.rankings.map((path) => [path, asset(base, release, path)])),
    geometry: geometryUrls(base, release, index.geometry),
  };
}

export async function loadDissestoData(): Promise<DissestoData> {
  const { base, release, index } = await dissestoRelease();
  const provenance = await fetchJson<Record<string, unknown>>(asset(base, release, index.provenance), 300);
  return {
    releaseId: release.releaseId,
    provenance,
    maps: index.maps.map((path) => parseMap(path, asset(base, release, path))),
    rankings: {},
    geometry: geometryUrls(base, release, index.geometry),
  };
}

export async function loadForestData(): Promise<ForestData> {
  const { base, release, index } = await forestsRelease();
  const provenance = await fetchJson<Record<string, unknown>>(asset(base, release, index.provenance), 300);
  return {
    releaseId: release.releaseId,
    provenance,
    maps: index.maps.map((path) => parseMap(path, asset(base, release, path))),
    rankings: Object.fromEntries(index.rankings.map((path) => [path, asset(base, release, path)])),
    geometry: geometryUrls(base, release, index.geometry),
    mapGeometry: Object.fromEntries(Object.entries(index.mapGeometry ?? {}).map(([mapPath, geometryPath]) => [mapPath, `${asset(base, release, geometryPath)}?release=${release.releaseId}`])),
  };
}

export async function loadEmissionsData(): Promise<EmissionsData> {
  const { base, release, index } = await emissionsRelease();
  const provincialCatalog = await fetchJson<{ combinations: Array<Omit<EmissionsProvincialCombination, "mapPaths"> & { mapPaths: Record<string, string> }> }>(asset(base, release, index.provincialCatalog), 300);
  return {
    overview: await fetchJson<EmissionsOverview>(asset(base, release, index.overview), 300),
    nationalUrls: { greenhouseGases: asset(base, release, index.national.greenhouseGases), airPollutantsNfr: asset(base, release, index.national.airPollutantsNfr) },
    provincial: provincialCatalog.combinations.map((item) => ({ ...item, mapPaths: Object.fromEntries(Object.entries(item.mapPaths).map(([year, path]) => [year, asset(base, release, path)])) })),
    geometryByPeriod: Object.fromEntries((index.geometry ?? []).map((path) => [path.match(/istat-province-(\d{4})/)?.[1] ?? "unknown", `${asset(base, release, path)}?release=${release.releaseId}`])),
  };
}

export async function loadWaterData(): Promise<WaterData> {
  const { base, release, index } = await waterRelease();
  const provenance = await fetchJson<Record<string, unknown>>(asset(base, release, index.provenance), 300);
  return {
    releaseId: release.releaseId,
    provenance,
    maps: index.maps.map((path) => parseMap(path, asset(base, release, path))),
    rankings: {},
    geometry: geometryUrls(base, release, index.geometry),
    mapGeometry: Object.fromEntries(Object.entries(index.mapGeometry ?? {}).map(([mapPath, geometryPath]) => [mapPath, `${asset(base, release, geometryPath)}?release=${release.releaseId}`])),
    profileUrls: Object.fromEntries((index.profiles ?? []).map((path) => [path.replace("delivery/water/profiles/", "").replace(".json", ""), asset(base, release, path)])),
  };
}

export async function loadWaterOverview(): Promise<WaterOverview> {
  const { base, release, index } = await waterRelease();
  const profilePath = index.profiles?.find((path) => path === "delivery/water/profiles/country/IT.json");
  if (!profilePath) throw new Error("Country water profile unavailable in active release");
  return { releaseId: release.releaseId, countryProfile: await fetchJson<WaterProfile>(asset(base, release, profilePath), 300) };
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

type HomeMapDataset = { values: Array<[string, number]>; unit: string; periodStart: string; periodEnd: string };

function unavailableSignal(id: HomeDomainSignal["id"], title: string, href: string): HomeDomainSignal {
  return { id, title, label: "Release non disponibile", displayValue: "—", unit: "", period: "—", note: "Dati non presenti nella release attiva.", href, status: "unavailable", kind: "official" };
}

export async function loadHomeDomainSignals(): Promise<HomeDomainSignal[]> {
  const tasks: Array<Promise<HomeDomainSignal>> = [
    loadHomeOverview().then((overview) => ({ id: "soil", title: "Suolo", label: "Incremento netto nazionale", displayValue: overview.latestNet.value.toLocaleString("it-IT", { maximumFractionDigits: 0 }), unit: overview.latestNet.unit, period: overview.periodKey, note: "Osservazione ufficiale ISPRA/SNPA.", href: `/suolo?metric=soil_net_consumption_hectares&level=region&period=${overview.periodKey.replace("–", "-")}#mappa`, status: "available", kind: "official" })),
    loadWaterOverview().then((overview) => {
      const observation = overview.countryProfile.latestObservations.find((item) => item.metricId === "water_total_precipitation_mm");
      if (!observation) throw new Error("Home water signal unavailable");
      return { id: "water", title: "Acqua", label: "Precipitazione totale Italia", displayValue: observation.value.toLocaleString("it-IT", { maximumFractionDigits: 1 }), unit: observation.unit, period: observation.periodEnd.slice(0, 4), note: "Stima modellistica ufficiale BIGBANG 10.0.", href: `/acqua?metric=${observation.metricId}&period=${observation.periodEnd.slice(0, 4)}#atlante`, status: "available", kind: "modelled" };
    }),
    loadForestData().then(async (data) => {
      const option = data.maps.find((item) => item.metricId === "tree_cover_mean" && item.periodKey === "2023-2023" && item.level === "region");
      if (!option) throw new Error("Home forest signal unavailable");
      const dataset = await fetchJson<HomeMapDataset>(option.url, 300);
      return { id: "forests", title: "Foreste", label: "Regioni con valore pubblicato", displayValue: dataset.values.length.toLocaleString("it-IT"), unit: "regioni", period: dataset.periodEnd.slice(0, 4), note: "Elaborazione zonale nazionale su Copernicus; non statistica territoriale ufficiale.", href: "/foreste?metric=tree_cover_mean&level=region&period=2023-2023#mappa", status: "available", kind: "derived" };
    }),
    emissionsRelease().then(async ({ base, release, index }) => {
      const overview = await fetchJson<EmissionsOverview>(asset(base, release, index.overview), 300);
      const latest = overview.greenhouseGases.series.at(-1);
      if (!latest) throw new Error("Home emissions signal unavailable");
      return { id: "emissions", title: "Emissioni", label: "Emissioni nette nazionali", displayValue: latest[1].toLocaleString("it-IT", { maximumFractionDigits: 0 }), unit: overview.greenhouseGases.unit, period: String(latest[0]), note: "Totale ufficiale ISPRA, incluse categorie indicate dalla fonte.", href: "/emissioni", status: "available", kind: "official" };
    }),
    loadDissestoData().then(async (data) => {
      const option = data.maps.find((item) => item.metricId === "hydrogeological_flood_high_hazard_area_km2" && item.level === "municipality");
      if (!option) throw new Error("Home risk signal unavailable");
      const dataset = await fetchJson<HomeMapDataset>(option.url, 300);
      return { id: "risk", title: "Dissesto", label: "Comuni con valore pubblicato", displayValue: dataset.values.length.toLocaleString("it-IT"), unit: "comuni", period: dataset.periodEnd.slice(0, 4), note: "Snapshot ufficiale ISPRA IdroGEO; non ranking.", href: "/dissesto?metric=hydrogeological_flood_high_hazard_area_km2&level=municipality#mappa", status: "available", kind: "official" };
    }),
  ];
  const fallbacks = [unavailableSignal("soil", "Suolo", "/suolo"), unavailableSignal("water", "Acqua", "/acqua"), unavailableSignal("forests", "Foreste", "/foreste"), unavailableSignal("emissions", "Emissioni", "/emissioni"), unavailableSignal("risk", "Dissesto", "/dissesto")];
  const results = await Promise.allSettled(tasks);
  return results.map((result, index) => result.status === "fulfilled" ? result.value : fallbacks[index]);
}

type TerritoryIdentityIndex = { shards: string[] };
type TerritoryIdentityShard = { territories: TerritoryIdentity[] };

async function loadTerritoryIdentity(base: string, release: Release, level: TerritoryLevel, istatCode: string): Promise<TerritoryIdentity> {
  const index = await fetchJson<TerritoryIdentityIndex>(asset(base, release, "delivery/territories/index.json"), 300);
  const territoryId = level === "country" ? `it:country:${istatCode}` : `it:${level}:${istatCode}`;
  const shard = level === "municipality" ? istatCode.slice(0, 3) : "all";
  const logicalPath = `delivery/territories/${level}/${shard}.json`;
  if (!index.shards.includes(logicalPath)) throw new Error(`Territory identity shard unavailable: ${logicalPath}`);
  const payload = await fetchJson<TerritoryIdentityShard>(asset(base, release, logicalPath), 300);
  const identity = payload.territories.find((candidate) => candidate.territoryId === territoryId);
  if (!identity) throw new Error(`Territory identity absent from shard: ${territoryId}`);
  return identity;
}

async function loadSoilTerritoryProfile(base: string, release: Release, level: TerritoryLevel, istatCode: string, territoryId: string): Promise<SoilTerritoryProfile | null> {
  if (!release.objects.some((item) => item.logicalPath === "delivery/soil/index.json")) return null;
  const index = await fetchJson<SoilIndex>(asset(base, release, "delivery/soil/index.json"), 300);
  if (level === "province") {
    const paths = index.profileShards.filter((path) => path.startsWith("delivery/soil/profiles/province/"));
    return paths.length ? profileFromShards(base, release, paths, territoryId) : null;
  }
  const logicalPath = `delivery/soil/profiles/${level}/${level === "municipality" ? istatCode.slice(0, 3) : "all"}.json`;
  return index.profileShards.includes(logicalPath) ? profileFromShard(base, release, logicalPath, territoryId) : null;
}

async function loadWaterTerritoryProfile(base: string, release: Release, level: TerritoryLevel, istatCode: string) {
  if (!release.objects.some((item) => item.logicalPath === "delivery/water/index.json")) return null;
  const index = await fetchJson<{ profiles?: string[] }>(asset(base, release, "delivery/water/index.json"), 300);
  const logicalPath = `delivery/water/profiles/${level}/${istatCode}.json`;
  return index.profiles?.includes(logicalPath)
    ? fetchJson<WaterProfile>(asset(base, release, logicalPath), 300)
    : null;
}

function profileDomainFromInsight(insight: TerritoryDomainInsight, level: TerritoryLevel): TerritoryDomainProfile {
  const capability = DOMAIN_CAPABILITIES[insight.id];
  const levelCapability = capability.levels[level];
  if (insight.availability === "unavailable") return {
    id: insight.id, title: capability.title, availability: "unavailable", reason: insight.reason,
    dataKind: levelCapability?.dataKind ?? capability.dataKind, temporal: levelCapability?.temporal ?? "snapshot",
    source: capability.primarySource, href: `/${insight.id === "risk" ? "dissesto" : insight.id}`,
  };
  return {
    id: insight.id, title: capability.title, availability: "available", dataKind: insight.kind,
    temporal: levelCapability?.temporal ?? "snapshot", source: insight.source, label: insight.label,
    latest: capability.summary === "numeric" ? insight.latest : undefined,
    series: capability.summary === "numeric" ? insight.series : undefined,
    comparison: insight.comparison, href: insight.href, groups: insight.groups, snapshots: insight.snapshots,
  };
}

function waterDomain(profile: WaterProfile | null, level: TerritoryLevel, territoryId: string, insight?: TerritoryDomainInsight): TerritoryDomainProfile | null {
  if (!profile) return null;
  const metric = level === "province" ? "water_total_precipitation_mm_zonal_mean" : "water_total_precipitation_mm";
  const latest = profile.latestObservations.find((item) => item.metricId === metric);
  if (!latest) return null;
  const capability = DOMAIN_CAPABILITIES.water.levels[level];
  if (!capability) return null;
  const series = profile.historicalSeries.find((item) => item.metricId === metric);
  const points = series?.values.map(([year, value], index) => ({
    metricId: metric, periodStart: `${year}-01-01`, periodEnd: `${year}-12-31`, value, unit: latest.unit,
    geometryReference: series?.points?.[index]?.territoryGeometryReference,
    methodologyReference: series?.points?.[index]?.methodologyReference,
  })) ?? [];
  const geometryReferences = profile.territoryGeometryReferences ?? series?.points?.flatMap((point) => point.territoryGeometryReference ? [point.territoryGeometryReference] : []) ?? [];
  return {
    id: "water", title: "Acqua", availability: "available", dataKind: capability.dataKind, temporal: capability.temporal,
    source: level === "province" ? "Elaborazione Stato d’Italia su raster ISPRA BIGBANG 10.0" : "Stima modellistica ufficiale ISPRA BIGBANG 10.0",
    label: "Precipitazione totale", latest: { periodStart: `${latest.periodEnd.slice(0, 4)}-01-01`, periodEnd: latest.periodEnd, value: latest.value, unit: latest.unit },
    series: points, comparison: insight?.availability === "available" ? insight.comparison : series?.comparison ?? { status: "unavailable", reason: "comparison_not_supported" },
    geometryReferences: [...new Set(geometryReferences)],
    href: `/acqua?level=${level === "province" ? "province" : "region"}&metric=${metric}&period=${latest.periodEnd.slice(0, 4)}&territory=${territoryId}#atlante`,
    detail: { kind: "water", profile },
  };
}

export async function loadTerritoryProfile(level: TerritoryLevel, istatCode: string) {
  if (!/^[0-9A-Z]{2,6}$/.test(istatCode)) throw new Error("Codice ISTAT non valido");
  const { base, release } = await activeRelease();
  const identity = await loadTerritoryIdentity(base, release, level, istatCode);
  const territoryId = identity.territoryId;
  const [insights, water, soilProfile, provenanceEntries] = await Promise.all([
    level === "country" ? Promise.resolve([]) : loadTerritoryInsights(base, release, level, istatCode, territoryId),
    loadWaterTerritoryProfile(base, release, level, istatCode),
    loadSoilTerritoryProfile(base, release, level, istatCode, territoryId),
    Promise.all(["soil", "water", "dissesto", "emissions", "foreste"].map(async (domain) => [domain, await optionalAssetJson(base, release, `delivery/${domain}/provenance.json`)] as const)),
  ]);
  const byId = new Map(insights.map((insight) => [insight.id, profileDomainFromInsight(insight, level)]));
  const waterDomainProfile = waterDomain(water, level, territoryId, insights.find((item) => item.id === "water"));
  if (waterDomainProfile) byId.set("water", waterDomainProfile);
  const domains = (Object.keys(DOMAIN_CAPABILITIES) as DomainId[]).map((id) => byId.get(id) ?? {
    id, title: DOMAIN_CAPABILITIES[id].title, availability: "unavailable" as const,
    reason: "source_not_published_at_this_level" as const, dataKind: DOMAIN_CAPABILITIES[id].levels[level]?.dataKind ?? DOMAIN_CAPABILITIES[id].dataKind,
    temporal: DOMAIN_CAPABILITIES[id].levels[level]?.temporal ?? "snapshot", source: DOMAIN_CAPABILITIES[id].primarySource,
    href: `/${id === "risk" ? "dissesto" : id}`,
  });
  const soilDomain = byId.get("soil");
  if (soilDomain?.availability === "available" && soilProfile) soilDomain.detail = { kind: "soil", profile: soilProfile };
  return { releaseId: release.releaseId, profile: { territory: identity, domains }, provenance: Object.fromEntries(provenanceEntries) };
}

export async function loadRomeProfile() {
  return loadTerritoryProfile("municipality", "058091");
}
