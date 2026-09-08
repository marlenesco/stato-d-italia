import type { EmissionsProvincialCombination, MapOption } from "./data";
import { resolveExplorerModel, type ExplorerFeatures, type ExplorerModelInput } from "./explorer-model";

export type EmissionsProvincialModelInput = {
  combinations: EmissionsProvincialCombination[];
  geometryByPeriod: Record<string, string>;
  currentTerritoryIds?: ExplorerModelInput["currentTerritoryIds"];
  requestedCombinationId?: string | null;
  requestedPeriod?: string | null;
  defaultMetricId?: string;
  defaultSnapCode?: string;
};

export type EmissionsProvincialModel = {
  combination?: EmissionsProvincialCombination;
  metricId?: string;
  snapCode?: string;
  periodKey?: string;
  selectedOption?: MapOption;
  availableCombinations: EmissionsProvincialCombination[];
  availablePeriods: string[];
  geometryUrl?: string;
  seriesOptions: MapOption[];
  features: ExplorerFeatures;
};

function compareCombinations(left: EmissionsProvincialCombination, right: EmissionsProvincialCombination) {
  return left.metricId.localeCompare(right.metricId) || left.snapCode.localeCompare(right.snapCode, undefined, { numeric: true }) || left.id.localeCompare(right.id);
}

function mapsFor(combination: EmissionsProvincialCombination): MapOption[] {
  return Object.entries(combination.mapAssets).map(([periodKey, asset]) => ({
    logicalPath: asset.logicalPath,
    url: `${asset.url}#${combination.snapCode}`,
    metricId: combination.metricId,
    level: "province",
    periodKey,
  }));
}

function mapGeometryFor(maps: MapOption[], geometryByPeriod: Record<string, string>) {
  return Object.fromEntries(maps.flatMap((option) => {
    const geometryUrl = geometryByPeriod[option.periodKey];
    return geometryUrl ? [[option.logicalPath, geometryUrl]] : [];
  }));
}

function resolveCombination(combinations: EmissionsProvincialCombination[], input: EmissionsProvincialModelInput) {
  const ordered = [...combinations].sort(compareCombinations);
  const valid = ordered.filter((combination) => mapsFor(combination).some((option) => Boolean(input.geometryByPeriod[option.periodKey])));
  const requested = valid.find((combination) => combination.id === input.requestedCombinationId);
  const editorial = valid.find((combination) => combination.metricId === input.defaultMetricId && combination.snapCode === input.defaultSnapCode);
  const fallback = requested ?? editorial ?? valid[0];
  if (fallback) return { combination: fallback, availableCombinations: valid };

  // Keep a configured combination only to report why no map is usable. It is
  // deliberately excluded from the selectable release-driven combinations.
  const configured = ordered.find((combination) => combination.id === input.requestedCombinationId)
    ?? ordered.find((combination) => combination.metricId === input.defaultMetricId && combination.snapCode === input.defaultSnapCode)
    ?? ordered[0];
  return { combination: configured, availableCombinations: valid };
}

export function resolveEmissionsProvincialModel(input: EmissionsProvincialModelInput): EmissionsProvincialModel {
  const { combination, availableCombinations } = resolveCombination(input.combinations, input);
  const maps = combination ? mapsFor(combination) : [];
  const resolved = resolveExplorerModel({
    domain: "emissions",
    maps,
    geometry: {},
    mapGeometry: mapGeometryFor(maps, input.geometryByPeriod),
    currentTerritoryIds: input.currentTerritoryIds,
    requestedMetric: combination?.metricId,
    requestedLevel: "province",
    requestedPeriod: input.requestedPeriod,
    preferences: { defaultMetric: combination?.metricId, preferredLevel: "province" },
  });
  const seriesOptions = maps.filter((option) => resolved.availablePeriods.includes(option.periodKey));

  return {
    combination,
    metricId: resolved.metricId ?? combination?.metricId,
    snapCode: combination?.snapCode,
    periodKey: resolved.periodKey,
    selectedOption: resolved.selectedOption,
    availableCombinations,
    availablePeriods: resolved.availablePeriods,
    geometryUrl: resolved.geometryUrl,
    seriesOptions,
    features: resolved.features,
  };
}
