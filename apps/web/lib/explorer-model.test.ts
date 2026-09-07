import { describe, expect, it } from "vitest";
import { resolveExplorerModel, retainTerritoryForLevel, type ExplorerModelInput } from "./explorer-model";

function map(metricId: string, periodKey: string, level: "municipality" | "province" | "region", path = `delivery/maps/${metricId}/${periodKey}/${level}.json`) {
  return { logicalPath: path, url: `https://example.test/${path}`, metricId, periodKey, level };
}

function input(overrides: Partial<ExplorerModelInput>): ExplorerModelInput {
  return {
    domain: "soil",
    maps: [],
    geometry: { municipality: "municipal.pmtiles", province: "province.pmtiles", region: "region.pmtiles" },
    rankings: {},
    ...overrides,
  };
}

describe("capability-driven explorer model", () => {
  it("keeps the Soil timeline and exact published ranking available", () => {
    const first = map("soil_net_consumption_hectares", "2022-2022", "province");
    const second = map("soil_net_consumption_hectares", "2024-2024", "province");
    const ranking = "delivery/soil/rankings/soil_net_consumption_hectares/2024-2024/province.json";
    const model = resolveExplorerModel(input({ maps: [first, second], rankings: { [ranking]: "ranking.json" }, requestedLevel: "province" }));
    expect(model.availablePeriods).toEqual(["2022-2022", "2024-2024"]);
    expect(model.features.timeline.status).toBe("available");
    expect(model.features.ranking.status).toBe("available");
    expect(model.features.percentile.status).toBe("available");
  });

  it("does not let a Risk snapshot acquire timeline, series, comparison, ranking, or percentile", () => {
    const model = resolveExplorerModel(input({ domain: "risk", maps: [map("hydrogeological_flood_high_hazard_area_km2", "2020-2020", "municipality")] }));
    expect(model.features).toMatchObject({
      map: { status: "available" }, timeline: { status: "not_supported" }, territorySeries: { status: "not_supported" },
      comparison: { status: "not_supported" }, ranking: { status: "not_supported" }, percentile: { status: "not_supported" },
    });
  });

  it("uses only published TCD periods and keeps Forest comparison fail-closed without methodology evidence", () => {
    const maps = ["2018-2018", "2021-2021", "2023-2023"].map((period) => map("tree_cover_mean", period, "region"));
    const model = resolveExplorerModel(input({ domain: "forests", maps, mapGeometry: Object.fromEntries(maps.map((option) => [option.logicalPath, "region.pmtiles"])) }));
    expect(model.availablePeriods).toEqual(["2018-2018", "2021-2021", "2023-2023"]);
    expect(model.features.timeline.status).toBe("available");
    expect(model.features.territorySeries.status).toBe("available");
    expect(model.features.comparison).toEqual({ status: "not_published", reason: "missing_comparison_evidence" });
  });

  it("does not turn one TCPC change period into a timeline", () => {
    const option = map("tree_cover_gain_ha", "2018-2021", "province");
    const model = resolveExplorerModel(input({ domain: "forests", maps: [option], mapGeometry: { [option.logicalPath]: "province-2021.pmtiles" } }));
    expect(model.features.timeline).toEqual({ status: "not_supported", reason: "single_change_period" });
    expect(model.features.territorySeries).toEqual({ status: "not_supported", reason: "single_change_period" });
  });

  it("does not fabricate Forest municipal or provincial levels for INFC", () => {
    const option = map("forest_biomass_infc", "2015-2015", "region");
    const model = resolveExplorerModel(input({ domain: "forests", maps: [option], mapGeometry: { [option.logicalPath]: "region-2015.pmtiles" }, requestedLevel: "municipality" }));
    expect(model.availableLevels).toEqual(["region"]);
    expect(model.level).toBe("region");
    expect(model.features.timeline.status).toBe("not_supported");
  });

  it("distinguishes an allowed but unpublished ranking from a forbidden ranking", () => {
    const forest = map("tree_cover_mean", "2023-2023", "region");
    const forestModel = resolveExplorerModel(input({ domain: "forests", maps: [forest], mapGeometry: { [forest.logicalPath]: "region.pmtiles" } }));
    expect(forestModel.features.ranking).toEqual({ status: "not_published", reason: "ranking_not_published" });

    const risk = map("hydrogeological_flood_high_hazard_area_km2", "2020-2020", "region");
    const riskModel = resolveExplorerModel(input({ domain: "risk", maps: [risk], rankings: { "delivery/dissesto/rankings/hydrogeological_flood_high_hazard_area_km2/2020-2020/region.json": "accidental.json" } }));
    expect(riskModel.features.ranking.status).toBe("not_supported");
  });

  it("falls back deterministically to the latest published period and a valid level", () => {
    const maps = [map("soil_net_consumption_hectares", "2022-2022", "province"), map("soil_net_consumption_hectares", "2024-2024", "province")];
    const model = resolveExplorerModel(input({ maps, requestedMetric: "unknown", requestedLevel: "municipality", requestedPeriod: "1900-1900", preferences: { defaultMetric: "soil_net_consumption_hectares", preferredLevel: "municipality" } }));
    expect(model).toMatchObject({ metricId: "soil_net_consumption_hectares", level: "province", periodKey: "2024-2024" });
  });

  it("requires a map-specific geometry whenever mapGeometry is declared", () => {
    const option = map("tree_cover_mean", "2023-2023", "region");
    const model = resolveExplorerModel(input({ domain: "forests", maps: [option], mapGeometry: {} }));
    expect(model.features.map).toEqual({ status: "not_published", reason: "missing_compatible_geometry" });
  });

  it("retains a selected territory only while the territory level is unchanged", () => {
    expect(retainTerritoryForLevel("province", "province", "it:province:057")).toBe("it:province:057");
    expect(retainTerritoryForLevel("municipality", "province", "it:municipality:057001")).toBeUndefined();
  });
});
