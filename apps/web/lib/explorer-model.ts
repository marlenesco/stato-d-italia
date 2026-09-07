import type { MapOption } from "./data";
import { DOMAIN_CAPABILITIES, type DomainCapability, type DomainId, type TemporalMode, type TerritoryLevel } from "./domain-capabilities";

export type ExplorerFeatureStatus = "available" | "not_published" | "not_supported";
export type ExplorerFeatureReason = "domain_not_supported" | "not_published" | "single_snapshot" | "single_change_period" | "insufficient_published_periods" | "missing_compatible_geometry" | "comparison_not_supported" | "missing_comparison_evidence" | "ranking_not_published";
export type ExplorerFeature = { status: ExplorerFeatureStatus; reason?: ExplorerFeatureReason };
export type ExplorerFeatures = {
  map: ExplorerFeature;
  timeline: ExplorerFeature;
  territorySeries: ExplorerFeature;
  comparison: ExplorerFeature;
  ranking: ExplorerFeature;
  percentile: ExplorerFeature;
  profile: ExplorerFeature;
};

export type MappableLevel = Exclude<TerritoryLevel, "country">;
export type ExplorerSelectionPreferences = {
  defaultMetric?: string;
  preferredLevel?: MappableLevel;
  metricAliases?: Record<string, string>;
};
export type ExplorerModelInput = {
  domain: DomainId;
  maps: MapOption[];
  geometry: Partial<Record<TerritoryLevel, string>>;
  mapGeometry?: Record<string, string>;
  rankings?: Record<string, string>;
  currentTerritoryIds?: Partial<Record<TerritoryLevel, string[]>>;
  requestedMetric?: string | null;
  requestedLevel?: string | null;
  requestedPeriod?: string | null;
  preferences?: ExplorerSelectionPreferences;
  capability?: DomainCapability;
};
export type ExplorerModel = {
  metricId?: string;
  level?: MappableLevel;
  periodKey?: string;
  selectedOption?: MapOption;
  availableMetrics: string[];
  availableLevels: MappableLevel[];
  availablePeriods: string[];
  geometryUrl?: string;
  rankingUrl?: string;
  features: ExplorerFeatures;
};

export function retainTerritoryForLevel(previousLevel: MappableLevel | undefined, nextLevel: MappableLevel | undefined, territoryId: string | undefined) {
  return previousLevel === nextLevel ? territoryId : undefined;
}

const DELIVERY_ROOT: Partial<Record<DomainId, string>> = { soil: "soil", forests: "foreste", risk: "dissesto" };
const LEVEL_ORDER: MappableLevel[] = ["municipality", "province", "region"];

function unavailable(reason: ExplorerFeatureReason): ExplorerFeature {
  return { status: "not_published", reason };
}

function unsupported(reason: ExplorerFeatureReason = "domain_not_supported"): ExplorerFeature {
  return { status: "not_supported", reason };
}

function available(): ExplorerFeature {
  return { status: "available" };
}

function comparePeriods(left: string, right: string) {
  return Number(left.slice(0, 4)) - Number(right.slice(0, 4)) || left.localeCompare(right);
}

function geometryFor(option: MapOption, input: ExplorerModelInput) {
  // A populated mapGeometry is authoritative: a historical map may not silently
  // fall back to the generic/current geometry for the level.
  if (input.mapGeometry) return input.mapGeometry[option.logicalPath];
  return input.geometry[option.level];
}

function isMappableLevel(level: TerritoryLevel): level is MappableLevel {
  return level !== "country";
}

function timelineFeature(temporal: TemporalMode, options: MapOption[]): ExplorerFeature {
  if (temporal === "snapshot") return unsupported("single_snapshot");
  if (temporal === "change_period") return unsupported("single_change_period");
  if (options.length < 2) {
    const onlyPeriod = options[0]?.periodKey.split("-");
    if (temporal === "mixed") return unsupported(onlyPeriod && onlyPeriod[0] !== onlyPeriod[1] ? "single_change_period" : "single_snapshot");
    return unavailable("insufficient_published_periods");
  }
  return available();
}

function rankingPath(domain: DomainId, option: MapOption) {
  const root = DELIVERY_ROOT[domain];
  return root ? `delivery/${root}/rankings/${option.metricId}/${option.periodKey}/${option.level}.json` : undefined;
}

export function resolveExplorerModel(input: ExplorerModelInput): ExplorerModel {
  const capability = input.capability ?? DOMAIN_CAPABILITIES[input.domain];
  const semanticMaps = input.maps.filter((option) => isMappableLevel(option.level) && capability.levels[option.level]);
  const publishedMaps = semanticMaps.filter((option) => Boolean(geometryFor(option, input)));
  const availableMetrics = [...new Set(publishedMaps.map((option) => option.metricId))].sort();
  const requestedMetric = input.requestedMetric ? input.preferences?.metricAliases?.[input.requestedMetric] ?? input.requestedMetric : undefined;
  const metricId = requestedMetric && availableMetrics.includes(requestedMetric)
    ? requestedMetric
    : input.preferences?.defaultMetric && availableMetrics.includes(input.preferences.defaultMetric)
      ? input.preferences.defaultMetric
      : availableMetrics[0];
  const metricMaps = publishedMaps.filter((option) => option.metricId === metricId);
  const availableLevels = [...new Set(metricMaps.map((option) => option.level))].sort((left, right) => LEVEL_ORDER.indexOf(left as MappableLevel) - LEVEL_ORDER.indexOf(right as MappableLevel)) as MappableLevel[];
  const requestedLevel = input.requestedLevel as MappableLevel | undefined;
  const level = requestedLevel && availableLevels.includes(requestedLevel)
    ? requestedLevel
    : input.preferences?.preferredLevel && availableLevels.includes(input.preferences.preferredLevel)
      ? input.preferences.preferredLevel
      : availableLevels[0];
  const options = metricMaps.filter((option) => option.level === level).sort((left, right) => comparePeriods(left.periodKey, right.periodKey));
  const selectedOption = options.find((option) => option.periodKey === input.requestedPeriod) ?? options.at(-1);
  const geometryUrl = selectedOption ? geometryFor(selectedOption, input) : undefined;
  const temporal = level ? capability.levels[level]?.temporal : undefined;
  const timeline = temporal ? timelineFeature(temporal, options) : unsupported();
  const territorySeries = timeline.status === "available" ? available() : timeline;
  const comparison = capability.comparison === "not_supported"
    ? unsupported("comparison_not_supported")
    : timeline.status !== "available"
      ? timeline
      : capability.comparison === "same_metric_unit_method_geometry"
        ? unavailable("missing_comparison_evidence")
        : available();
  const exactRankingPath = selectedOption ? rankingPath(input.domain, selectedOption) : undefined;
  const rankingUrl = exactRankingPath ? input.rankings?.[exactRankingPath] : undefined;
  const ranking = capability.rankingPolicy === "not_allowed"
    ? unsupported()
    : rankingUrl ? available() : unavailable("ranking_not_published");
  const percentile = capability.percentilePolicy === "not_allowed"
    ? unsupported()
    : ranking.status === "available" ? available() : ranking;
  const map = capability.mapPolicy === "not_allowed"
    ? unsupported()
    : selectedOption && geometryUrl ? available()
      : semanticMaps.length ? unavailable("missing_compatible_geometry") : unavailable("not_published");
  const currentIdentities = level ? input.currentTerritoryIds?.[level] : undefined;
  const profile = capability.profilePolicy === "not_allowed"
    ? unsupported()
    : selectedOption && currentIdentities && currentIdentities.length > 0 ? available() : unavailable("not_published");

  return {
    metricId,
    level,
    periodKey: selectedOption?.periodKey,
    selectedOption,
    availableMetrics,
    availableLevels,
    availablePeriods: options.map((option) => option.periodKey),
    geometryUrl,
    rankingUrl,
    features: { map, timeline, territorySeries, comparison, ranking, percentile, profile },
  };
}
