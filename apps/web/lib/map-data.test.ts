import { describe, expect, it } from "vitest";
import { resolveMapDataset, resolvePeriodOption, resolveTemporalScale, type MapDataset } from "./map-data";

const options = [
  { logicalPath: "maps/tcd/2018", url: "https://example.test/A", metricId: "tree_cover_mean", periodKey: "2018-2018", level: "region" as const },
  { logicalPath: "maps/tcd/2021", url: "https://example.test/B", metricId: "tree_cover_mean", periodKey: "2021-2021", level: "region" as const },
  { logicalPath: "maps/tcd/2023", url: "https://example.test/C", metricId: "tree_cover_mean", periodKey: "2023-2023", level: "region" as const },
];

describe("forest map data resolution", () => {
  it("resolves each requested period to its own map URL", () => {
    expect(resolvePeriodOption(options, "2018-2018")?.url).toBe("https://example.test/A");
    expect(resolvePeriodOption(options, "2021-2021")?.url).toBe("https://example.test/B");
    expect(resolvePeriodOption(options, "2023-2023")?.url).toBe("https://example.test/C");
  });

  it("resolves a snapshot URL fragment without changing its period", () => {
    const dataset = resolveMapDataset({
      values: [["it:region:01", 1]], unit: "%", periodStart: "2021-01-01", periodEnd: "2021-12-31",
      snapshots: [{ sourceDimensions: { snap_code: "forest" }, unit: "ha", values: [["it:region:01", 42]] }],
    }, "https://example.test/map#forest");
    expect(dataset).toMatchObject({ values: [["it:region:01", 42]], unit: "ha", periodEnd: "2021-12-31" });
  });

  it("uses exactly one shared scale domain for map fill and legend", () => {
    const datasets: MapDataset[] = [
      { values: [["a", 10], ["b", 20]], unit: "%", periodStart: "2018-01-01", periodEnd: "2018-12-31" },
      { values: [["a", 15], ["b", 30]], unit: "%", periodStart: "2021-01-01", periodEnd: "2021-12-31" },
      { values: [["a", 5], ["b", 40]], unit: "%", periodStart: "2023-01-01", periodEnd: "2023-12-31" },
    ];
    expect(resolveTemporalScale(datasets, true)).toEqual({ min: 5, mid: 22.5, max: 40 });
    expect(resolveTemporalScale([datasets[1]], false)).toEqual({ min: 15, mid: 22.5, max: 30 });
  });
});
