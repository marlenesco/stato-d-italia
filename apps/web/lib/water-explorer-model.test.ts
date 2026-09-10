import { describe, expect, it } from "vitest";
import { normalizedWaterPeriodQuery } from "../components/water-workspace";
import { resolveWaterExplorerModel } from "./water-explorer-model";
import type { MapOption } from "./data";
import { waterMapSeriesProps } from "../components/water-map";
import { currentProfileHref } from "./current-profile";
import { shouldRenderProfileLink } from "./explorer-rendering";
import { DOMAIN_CAPABILITIES } from "./domain-capabilities";
import { retainTerritoryForLevel } from "./explorer-model";

function map(metricId: string, periodKey: string, level: "region" | "province"): MapOption {
  const logicalPath = `delivery/water/maps/${metricId}/${periodKey}/${level}.json`;
  return { logicalPath, url: `https://example.test/${logicalPath}`, metricId, periodKey, level };
}

function input(maps: MapOption[], overrides: Partial<Parameters<typeof resolveWaterExplorerModel>[0]> = {}) {
  return {
    maps,
    geometry: { region: "region.pmtiles", province: "province.pmtiles" },
    mapGeometry: Object.fromEntries(maps.map((option) => [option.logicalPath, `${option.level}.pmtiles`])),
    ...overrides,
  };
}

const historicalYears = [
  "2002", "2003", "2004", "2005", "2006", "2007", "2008", "2009", "2010",
  "2012", "2013", "2014", "2015", "2016", "2017", "2018", "2019", "2020",
  "2022", "2023", "2024", "2025",
];
const provincialMetrics = [
  "water_total_precipitation_mm_zonal_mean",
  "water_actual_evapotranspiration_mm_zonal_mean",
  "water_internal_flow_mm_zonal_mean",
  "water_aquifer_recharge_mm_zonal_mean",
  "water_surface_runoff_mm_zonal_mean",
];

describe("Water explorer model", () => {
  it("exposes exactly the 22 published H1F years for all five provincial families", () => {
    const maps = provincialMetrics.flatMap((metric) => [...historicalYears].reverse().map((year) => map(metric, year, "province")));
    for (const requestedMetric of provincialMetrics) {
      const model = resolveWaterExplorerModel(input(maps, { requestedMetric, requestedLevel: "province" }));
      expect(model.availablePeriods).toEqual(historicalYears);
      expect(new Set(model.availablePeriods).size).toBe(22);
      expect(model.availablePeriods).not.toContain("2011");
      expect(model.availablePeriods).not.toContain("2021");
      expect(model.availablePeriods[model.availablePeriods.indexOf("2010") + 1]).toBe("2012");
      expect(model.availablePeriods[model.availablePeriods.indexOf("2020") + 1]).toBe("2022");
      expect(model.periodKey).toBe("2025");
      expect(model.metricId).toBe(requestedMetric);
      expect(model.availableMetricFamilies.map((family) => family.byLevel.province)).toEqual(provincialMetrics);
      expect(DOMAIN_CAPABILITIES.water.levels.province).toMatchObject({ dataKind: "derived_metric", temporal: "sparse_series" });
      expect(model.features).toMatchObject({
        timeline: { status: "available" }, territorySeries: { status: "available" },
        ranking: { status: "not_supported" }, percentile: { status: "not_supported" },
        comparison: { status: "not_published", reason: "missing_comparison_evidence" },
      });
    }
  });

  it.each(["2011", "2021"])("resolves unsupported %s to latest publication and normalizes only the URL period", (requestedPeriod) => {
    const maps = historicalYears.map((year) => map(provincialMetrics[0], year, "province"));
    const model = resolveWaterExplorerModel(input(maps, { requestedLevel: "province", requestedPeriod }));
    expect(model.periodKey).toBe("2025");
    expect(model.availablePeriods).toEqual(historicalYears);
    expect(model.availablePeriods).not.toContain(requestedPeriod);
    const query = new URLSearchParams({ level: "province", metric: provincialMetrics[0], period: requestedPeriod, territory: "it:province:057", extra: "kept" });
    const normalized = normalizedWaterPeriodQuery(query.toString(), model)!;
    expect(Object.fromEntries(new URLSearchParams(normalized))).toEqual({ ...Object.fromEntries(query), period: "2025" });
    expect(normalizedWaterPeriodQuery(normalized, model)).toBeUndefined();
    expect(normalizedWaterPeriodQuery("level=province", model)).toBeUndefined();
    expect(normalizedWaterPeriodQuery(query.toString(), resolveWaterExplorerModel(input([])))).toBeUndefined();
    expect(new URLSearchParams(normalizedWaterPeriodQuery(`level=region&period=${requestedPeriod}&territory=it:region:12`, model)).has("territory")).toBe(false);
    const valid = resolveWaterExplorerModel(input(maps, { requestedLevel: "province", requestedPeriod: "2012" }));
    expect(valid.periodKey).toBe("2012");
    expect(normalizedWaterPeriodQuery("level=province&period=2012&territory=it:province:057", valid)).toBeUndefined();
  });

  it("excludes a historical year without exact mapGeometry despite current and adjacent geometries", () => {
    const maps = ["2009", "2010", "2012", "2025"].map((year) => map(provincialMetrics[0], year, "province"));
    const mapGeometry = Object.fromEntries(maps.map((option) => [option.logicalPath, `province-${option.periodKey}.pmtiles`]));
    for (const option of maps) {
      const model = resolveWaterExplorerModel(input(maps, { mapGeometry, requestedLevel: "province", requestedPeriod: option.periodKey }));
      expect(model.periodKey).toBe(option.periodKey);
      expect(model.geometryUrl).toBe(mapGeometry[option.logicalPath]);
    }
    delete mapGeometry[maps[1].logicalPath];
    const model = resolveWaterExplorerModel(input(maps, { mapGeometry, requestedLevel: "province", requestedPeriod: "2010" }));
    expect(model.availablePeriods).toEqual(["2009", "2012", "2025"]);
    expect(model.periodKey).toBe("2025");
    expect(model.selectedOption).toEqual(maps[3]);
    expect(model.geometryUrl).toBe("province-2025.pmtiles");
    const missing = resolveWaterExplorerModel(input([maps[1]], { mapGeometry, requestedLevel: "province", requestedPeriod: "2010" }));
    expect(missing.features.map).toEqual({ status: "not_published", reason: "missing_compatible_geometry" });
    expect(missing.geometryUrl).toBeUndefined();
    expect(missing.selectedOption).toBeUndefined();
  });

  it("keeps regional official annual maps as a series but fails comparison closed", () => {
    const maps = ["2021", "2022", "2023"].map((period) => map("water_total_precipitation_mm", period, "region"));
    const model = resolveWaterExplorerModel(input(maps, { requestedMetric: "water_total_precipitation_mm", requestedLevel: "region", requestedPeriod: "2021" }));
    expect(model).toMatchObject({ metricId: "water_total_precipitation_mm", level: "region", periodKey: "2021" });
    expect(model.features).toMatchObject({ timeline: { status: "available" }, territorySeries: { status: "available" }, comparison: { status: "not_published", reason: "missing_comparison_evidence" }, ranking: { status: "not_supported" }, percentile: { status: "not_supported" } });
  });

  it("keeps provincial derived sparse maps as a series without turning them into a ranking", () => {
    const maps = ["2018", "2023"].map((period) => map("water_total_precipitation_mm_zonal_mean", period, "province"));
    const model = resolveWaterExplorerModel(input(maps, { requestedMetric: "water_total_precipitation_mm_zonal_mean", requestedLevel: "province" }));
    expect(model).toMatchObject({ metricId: "water_total_precipitation_mm_zonal_mean", level: "province", periodKey: "2023" });
    expect(DOMAIN_CAPABILITIES.water.levels.province?.dataKind).toBe("derived_metric");
    expect(model.features).toMatchObject({ timeline: { status: "available" }, territorySeries: { status: "available" }, comparison: { status: "not_published" }, ranking: { status: "not_supported" }, percentile: { status: "not_supported" } });
  });

  it("preserves the family while resolving the level-specific metric and period", () => {
    const maps = [
      map("water_total_precipitation_mm", "2022", "region"),
      map("water_total_precipitation_mm", "2023", "region"),
      map("water_total_precipitation_mm_zonal_mean", "2023", "province"),
      map("water_total_precipitation_mm_zonal_mean", "2025", "province"),
    ];
    const province = resolveWaterExplorerModel(input(maps, { requestedMetric: "water_total_precipitation_mm", requestedLevel: "province", requestedPeriod: "2023" }));
    const region = resolveWaterExplorerModel(input(maps, { requestedMetric: province.metricId, requestedLevel: "region", requestedPeriod: province.periodKey }));
    expect(province).toMatchObject({ metricId: "water_total_precipitation_mm_zonal_mean", level: "province", periodKey: "2023" });
    expect(region).toMatchObject({ metricId: "water_total_precipitation_mm", level: "region", periodKey: "2023" });
  });

  it("uses only release-published families and levels, with deterministic invalid URL fallback", () => {
    const maps = [map("water_total_precipitation_mm", "2021", "region"), map("water_total_precipitation_mm", "2023", "region")];
    const model = resolveWaterExplorerModel(input(maps, { requestedMetric: "unknown", requestedLevel: "municipality", requestedPeriod: "1900" }));
    expect(model.availableMetricFamilies.map((family) => family.id)).toEqual(["precipitation"]);
    expect(model.availableLevels).toEqual(["region"]);
    expect(model).toMatchObject({ metricId: "water_total_precipitation_mm", level: "region", periodKey: "2023" });
  });

  it("keeps a one-year Water release semantically supported but not published as a timeline", () => {
    const model = resolveWaterExplorerModel(input([map("water_total_precipitation_mm", "2023", "region")]));
    expect(model.features.timeline).toEqual({ status: "not_published", reason: "insufficient_published_periods" });
    expect(model.features.territorySeries).toEqual({ status: "not_published", reason: "insufficient_published_periods" });
  });

  it("requires exact published Water map geometry and current identities for profiles", () => {
    const option = map("water_total_precipitation_mm", "2023", "region");
    expect(resolveWaterExplorerModel(input([option], { mapGeometry: {} })).features.map).toEqual({ status: "not_published", reason: "missing_compatible_geometry" });
    expect(resolveWaterExplorerModel(input([option])).features.profile.status).toBe("not_published");
    expect(resolveWaterExplorerModel(input([option], { currentTerritoryIds: { region: [] } })).features.profile.status).toBe("not_published");
    expect(resolveWaterExplorerModel(input([option], { currentTerritoryIds: { region: ["it:region:01"] } })).features.profile.status).toBe("available");
  });

  it("passes a fail-closed comparison status to an otherwise available Water series", () => {
    const maps = ["2022", "2023"].map((period) => map("water_total_precipitation_mm", period, "region"));
    const model = resolveWaterExplorerModel(input(maps));
    expect(model.features.territorySeries.status).toBe("available");
    expect(waterMapSeriesProps(model.features)).toEqual({ comparisonStatus: "not_published" });
  });

  it("does not expose a profile link for a selected historical identity", () => {
    const option = map("water_total_precipitation_mm", "2023", "region");
    const model = resolveWaterExplorerModel(input([option], { currentTerritoryIds: { region: ["it:region:01"] } }));
    const historicalHref = currentProfileHref("region", "it:region:02", "02", ["it:region:01"]);
    expect(shouldRenderProfileLink(model.features, historicalHref)).toBeUndefined();
  });

  it("clears Water territory selection across levels without a crosswalk", () => {
    expect(retainTerritoryForLevel("region", "province", "it:region:01")).toBeUndefined();
  });
});
