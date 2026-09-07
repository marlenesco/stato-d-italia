import { describe, expect, it } from "vitest";
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

describe("Water explorer model", () => {
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
