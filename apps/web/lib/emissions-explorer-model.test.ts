import { describe, expect, it } from "vitest";
import type { EmissionsProvincialCombination } from "./data";
import { currentProfileHref } from "./current-profile";
import { resolveEmissionsProvincialModel } from "./emissions-explorer-model";
import { retainTerritoryForLevel } from "./explorer-model";
import { shouldRenderComparison, shouldRenderProfileLink, shouldRenderRanking, shouldRenderTerritorySeries } from "./explorer-rendering";

function combination(id: string, snapCode: string, periods: string[], metricId = "emissions_air_nox"): EmissionsProvincialCombination {
  return {
    id,
    metricId,
    pollutantCode: metricId === "emissions_air_nox" ? "NOX" : "PM10",
    pollutantLabel: metricId === "emissions_air_nox" ? "Ossidi di azoto" : "PM10",
    snapCode,
    snapLabel: `Attività ${snapCode}`,
    unit: "Mg",
    mapAssets: Object.fromEntries(periods.map((period) => {
      const logicalPath = `delivery/emissions/maps/${metricId}/${period}/province.json`;
      return [period, { logicalPath, url: `https://example.test/objects/${metricId}-${period}.json` }];
    })),
  };
}

function resolve(combinations: EmissionsProvincialCombination[], overrides: Partial<Parameters<typeof resolveEmissionsProvincialModel>[0]> = {}) {
  return resolveEmissionsProvincialModel({
    combinations,
    geometryByPeriod: { "2019": "province-2019.pmtiles", "2023": "province-2023.pmtiles" },
    ...overrides,
  });
}

describe("Emissions provincial explorer adapter", () => {
  it("enables map, timeline, and series for 2019 + 2023 while forbidding comparison and rankings", () => {
    const model = resolve([combination("nox-a", "A", ["2019", "2023"])], { currentTerritoryIds: { province: ["it:province:057"] } });
    expect(model).toMatchObject({ metricId: "emissions_air_nox", snapCode: "A", periodKey: "2023", geometryUrl: "province-2023.pmtiles" });
    expect(model.availablePeriods).toEqual(["2019", "2023"]);
    expect(model.features).toMatchObject({
      map: { status: "available" },
      timeline: { status: "available" },
      territorySeries: { status: "available" },
      comparison: { status: "not_supported", reason: "comparison_not_supported" },
      ranking: { status: "not_supported" },
      percentile: { status: "not_supported" },
      profile: { status: "available" },
    });
    expect(shouldRenderTerritorySeries(model.features.territorySeries)).toBe(true);
    expect(shouldRenderComparison(model.features.comparison.status)).toBe(false);
    expect(shouldRenderRanking(model.features.ranking)).toBe(false);

    const historical = resolve([combination("nox-a", "A", ["2019", "2023"])], { requestedPeriod: "2019" });
    expect(historical).toMatchObject({ periodKey: "2019", geometryUrl: "province-2019.pmtiles" });
  });

  it("keeps one sparse period supported but not published as timeline or series", () => {
    const model = resolve([combination("nox-a", "A", ["2023"])]);
    expect(model.features.timeline).toEqual({ status: "not_published", reason: "insufficient_published_periods" });
    expect(model.features.territorySeries).toEqual({ status: "not_published", reason: "insufficient_published_periods" });
    expect(model.features.comparison).toEqual({ status: "not_supported", reason: "comparison_not_supported" });
  });

  it("fails closed when the map has no exact geometry for its period", () => {
    const model = resolve([combination("nox-a", "A", ["2019"])], { geometryByPeriod: { "2023": "province-2023.pmtiles" } });
    expect(model.features.map).toEqual({ status: "not_published", reason: "missing_compatible_geometry" });
    expect(model.geometryUrl).toBeUndefined();
    expect(model.availableCombinations).toEqual([]);
  });

  it("isolates periods and map fragments between SNAP combinations sharing a metric", () => {
    const a = combination("nox-a", "A", ["2019"]);
    const b = combination("nox-b", "B", ["2023"]);
    const model = resolve([b, a], { requestedCombinationId: "nox-a" });
    expect(model.combination?.id).toBe("nox-a");
    expect(model.availablePeriods).toEqual(["2019"]);
    expect(model.seriesOptions).toHaveLength(1);
    expect(model.seriesOptions[0].url).toBe("https://example.test/objects/emissions_air_nox-2019.json#A");
    expect(model.seriesOptions.every((option) => !option.url.endsWith("#B"))).toBe(true);
  });

  it("uses the editorial published combination, then deterministic order, for invalid requests", () => {
    const first = combination("nox-a", "A", ["2019"]);
    const editorial = combination("pm10-c", "C", ["2023"], "emissions_air_pm10");
    expect(resolve([first, editorial], { requestedCombinationId: "missing", defaultMetricId: editorial.metricId, defaultSnapCode: editorial.snapCode }).combination?.id).toBe("pm10-c");
    expect(resolve([editorial, first], { requestedCombinationId: "missing" }).combination?.id).toBe("nox-a");
  });

  it("falls an invalid period back to the latest published period", () => {
    expect(resolve([combination("nox-a", "A", ["2019", "2023"])], { requestedPeriod: "1900" }).periodKey).toBe("2023");
  });

  it("preserves a period across SNAP changes only when the target combination publishes it", () => {
    const a = combination("nox-a", "A", ["2019", "2023"]);
    const b = combination("nox-b", "B", ["2019"]);
    expect(resolve([a, b], { requestedCombinationId: "nox-a", requestedPeriod: "2019" }).periodKey).toBe("2019");
    expect(resolve([a, b], { requestedCombinationId: "nox-b", requestedPeriod: "2023" }).periodKey).toBe("2019");
  });

  it("keeps the selected Province across pollutant, SNAP, and period changes", () => {
    expect(retainTerritoryForLevel("province", "province", "it:province:057")).toBe("it:province:057");
  });

  it("requires a non-empty current Province population and an exact current identity for profile links", () => {
    const item = combination("nox-a", "A", ["2023"]);
    expect(resolve([item]).features.profile.status).toBe("not_published");
    expect(resolve([item], { currentTerritoryIds: { province: [] } }).features.profile.status).toBe("not_published");

    const model = resolve([item], { currentTerritoryIds: { province: ["it:province:057"] } });
    expect(model.features.profile.status).toBe("available");
    const current = currentProfileHref("province", "it:province:057", "057", ["it:province:057"]);
    const historical = currentProfileHref("province", "it:province:215", "215", ["it:province:057"]);
    expect(shouldRenderProfileLink(model.features, current)).toBe("/territori/province/057");
    expect(shouldRenderProfileLink(model.features, historical)).toBeUndefined();
  });
});
