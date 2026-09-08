import { describe, expect, it } from "vitest";
import { DOMAIN_CAPABILITIES } from "./domain-capabilities";
import { resolveExplorerModel, type ExplorerModelInput } from "./explorer-model";
import { profileUnavailableCopy, shouldRenderComparison, shouldRenderMap, shouldRenderProfileLink, shouldRenderRanking, shouldRenderTerritorySeries, shouldRenderTimeline } from "./explorer-rendering";

function map(metricId: string, periodKey: string, level: "municipality" | "province" | "region") {
  const logicalPath = `delivery/maps/${metricId}/${periodKey}/${level}.json`;
  return { logicalPath, url: `https://example.test/${logicalPath}`, metricId, periodKey, level };
}

function model(input: Partial<ExplorerModelInput>) {
  return resolveExplorerModel({ domain: "soil", maps: [], geometry: { municipality: "municipal.pmtiles", province: "province.pmtiles", region: "region.pmtiles" }, rankings: {}, ...input });
}

describe("explorer rendering guards", () => {
  it("keeps every temporal, ranking, series, and comparison affordance out of a Risk snapshot", () => {
    const risk = model({
      domain: "risk",
      maps: [map("hydrogeological_flood_high_hazard_area_km2", "2020-2020", "municipality")],
      currentTerritoryIds: { municipality: ["it:municipality:058091"] },
    });
    expect(shouldRenderTimeline(risk.features.timeline)).toBe(false);
    expect(shouldRenderTerritorySeries(risk.features.territorySeries)).toBe(false);
    expect(shouldRenderRanking(risk.features.ranking)).toBe(false);
    expect(risk.features.comparison.status).toBe("not_supported");
    expect(risk.features.profile.status).toBe("available");
  });

  it("renders a Forest TCPC map but not a one-item timeline or territory series", () => {
    const option = map("tree_cover_gain_ha", "2018-2021", "province");
    const forest = model({ domain: "forests", maps: [option], mapGeometry: { [option.logicalPath]: "province-2021.pmtiles" } });
    expect(shouldRenderMap(forest.features.map)).toBe(true);
    expect(shouldRenderTimeline(forest.features.timeline)).toBe(false);
    expect(shouldRenderTerritorySeries(forest.features.territorySeries)).toBe(false);
    expect(shouldRenderRanking(forest.features.ranking)).toBe(true);
  });

  it("renders a Forest TCD timeline and series but no delta without comparison evidence", () => {
    const maps = ["2018-2018", "2021-2021", "2023-2023"].map((period) => map("tree_cover_mean", period, "region"));
    const forest = model({ domain: "forests", maps, mapGeometry: Object.fromEntries(maps.map((option) => [option.logicalPath, "region.pmtiles"])) });
    expect(shouldRenderTimeline(forest.features.timeline)).toBe(true);
    expect(shouldRenderTerritorySeries(forest.features.territorySeries)).toBe(true);
    expect(forest.features.comparison.status).toBe("not_published");
    expect(shouldRenderComparison(forest.features.comparison.status)).toBe(false);
  });

  it("enforces map and profile policy before a component can render an affordance", () => {
    const option = map("soil_net_consumption_hectares", "2024-2024", "province");
    const forbidden = model({ maps: [option], capability: { ...DOMAIN_CAPABILITIES.soil, mapPolicy: "not_allowed", profilePolicy: "not_allowed" }, currentTerritoryIds: { province: ["it:province:057"] } });
    expect(shouldRenderMap(forbidden.features.map)).toBe(false);
    expect(shouldRenderProfileLink(forbidden.features, "/territori/province/057")).toBeUndefined();

    const missing = model({ maps: [option] });
    expect(shouldRenderProfileLink(missing.features, "/territori/province/057")).toBeUndefined();
    expect(profileUnavailableCopy(missing.features.profile)).toContain("non disponibile");

    const exact = model({ maps: [option], currentTerritoryIds: { province: ["it:province:057"] } });
    expect(shouldRenderProfileLink(exact.features, "/territori/province/057")).toBe("/territori/province/057");
  });
});
