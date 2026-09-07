import type { MapOption } from "./data";
import { resolveExplorerModel, type ExplorerFeatures, type ExplorerModelInput } from "./explorer-model";

export type WaterLevel = "region" | "province";

export type WaterMetricFamily = {
  id: string;
  label: string;
  byLevel: Record<WaterLevel, string>;
};

export const WATER_METRIC_FAMILIES: WaterMetricFamily[] = [
  { id: "precipitation", label: "Precipitazione totale", byLevel: { region: "water_total_precipitation_mm", province: "water_total_precipitation_mm_zonal_mean" } },
  { id: "evapotranspiration", label: "Evapotraspirazione effettiva", byLevel: { region: "water_actual_evapotranspiration_mm", province: "water_actual_evapotranspiration_mm_zonal_mean" } },
  { id: "internal-flow", label: "Risorsa idrica rinnovabile", byLevel: { region: "water_internal_flow_mm", province: "water_internal_flow_mm_zonal_mean" } },
  { id: "aquifer-recharge", label: "Ricarica acquiferi", byLevel: { region: "water_aquifer_recharge_mm", province: "water_aquifer_recharge_mm_zonal_mean" } },
  { id: "surface-runoff", label: "Ruscellamento superficiale", byLevel: { region: "water_surface_runoff_mm", province: "water_surface_runoff_mm_zonal_mean" } },
];

export type WaterExplorerModelInput = Pick<ExplorerModelInput,
  "maps" | "geometry" | "mapGeometry" | "currentTerritoryIds" | "requestedMetric" | "requestedLevel" | "requestedPeriod"
>;

export type WaterExplorerModel = {
  metricFamily?: WaterMetricFamily;
  metricId?: string;
  level?: WaterLevel;
  periodKey?: string;
  selectedOption?: MapOption;
  availableMetricFamilies: WaterMetricFamily[];
  availableLevels: WaterLevel[];
  availablePeriods: string[];
  geometryUrl?: string;
  features: ExplorerFeatures;
};

const WATER_LEVELS: WaterLevel[] = ["region", "province"];

function familyForMetric(metric: string | null | undefined) {
  return WATER_METRIC_FAMILIES.find((family) => family.id === metric || Object.values(family.byLevel).includes(metric ?? ""));
}

function requestedWaterLevel(level: string | null | undefined): WaterLevel | undefined {
  return level === "region" || level === "province" ? level : undefined;
}

function modelFor(family: WaterMetricFamily, level: WaterLevel, input: WaterExplorerModelInput) {
  const metricId = family.byLevel[level];
  return resolveExplorerModel({
    domain: "water",
    maps: input.maps.filter((option) => option.metricId === metricId),
    geometry: input.geometry,
    // Water delivery declares an exact geometry for every published map. Never
    // fall back to a generic/current geometry when that declaration is absent.
    mapGeometry: input.mapGeometry ?? {},
    currentTerritoryIds: input.currentTerritoryIds,
    requestedMetric: metricId,
    requestedLevel: level,
    requestedPeriod: input.requestedPeriod,
    preferences: { defaultMetric: metricId, preferredLevel: level },
  });
}

export function resolveWaterExplorerModel(input: WaterExplorerModelInput): WaterExplorerModel {
  const candidates = new Map<WaterMetricFamily, Map<WaterLevel, ReturnType<typeof modelFor>>>();
  for (const family of WATER_METRIC_FAMILIES) {
    const levels = new Map<WaterLevel, ReturnType<typeof modelFor>>();
    for (const level of WATER_LEVELS) {
      const candidate = modelFor(family, level, input);
      if (candidate.features.map.status === "available") levels.set(level, candidate);
    }
    if (levels.size) candidates.set(family, levels);
  }

  const requestedLevel = requestedWaterLevel(input.requestedLevel);
  const requestedFamily = familyForMetric(input.requestedMetric);
  const availableFamilies = [...candidates.keys()];
  const configuredFamilies = WATER_METRIC_FAMILIES.filter((family) => WATER_LEVELS.some((level) => input.maps.some((option) => option.metricId === family.byLevel[level])));
  const metricFamily = requestedFamily && (candidates.has(requestedFamily) || configuredFamilies.includes(requestedFamily))
    ? requestedFamily
    : availableFamilies.find((family) => requestedLevel && candidates.get(family)?.has(requestedLevel))
      ?? availableFamilies.find((family) => candidates.get(family)?.has("region"))
      ?? configuredFamilies.find((family) => requestedLevel && input.maps.some((option) => option.metricId === family.byLevel[requestedLevel]))
      ?? configuredFamilies.find((family) => input.maps.some((option) => option.metricId === family.byLevel.region))
      ?? availableFamilies[0];
  const levelCandidates = metricFamily ? candidates.get(metricFamily) : undefined;
  const availableLevels = WATER_LEVELS.filter((level) => levelCandidates?.has(level));
  const level = requestedLevel && levelCandidates?.has(requestedLevel)
    ? requestedLevel
    : availableLevels.includes("region") ? "region" : availableLevels[0] ?? requestedLevel ?? "region";
  const resolved = metricFamily && level ? levelCandidates?.get(level) ?? modelFor(metricFamily, level, input) : undefined;

  return {
    metricFamily,
    metricId: resolved?.metricId ?? (metricFamily && level ? metricFamily.byLevel[level] : undefined),
    level,
    periodKey: resolved?.periodKey,
    selectedOption: resolved?.selectedOption,
    availableMetricFamilies: availableFamilies.filter((family) => level && candidates.get(family)?.has(level)),
    availableLevels,
    availablePeriods: resolved?.availablePeriods ?? [],
    geometryUrl: resolved?.geometryUrl,
    features: resolved?.features ?? resolveExplorerModel({ domain: "water", maps: [], geometry: input.geometry, mapGeometry: input.mapGeometry ?? {}, currentTerritoryIds: input.currentTerritoryIds }).features,
  };
}
