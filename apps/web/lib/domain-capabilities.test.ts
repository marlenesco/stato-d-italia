import { describe, expect, it } from "vitest";
import { DOMAIN_CAPABILITIES } from "./domain-capabilities";

describe("cross-domain capability contract", () => {
  it("keeps D2 comparison and ranking policies stable across all five domains", () => {
    expect(Object.fromEntries(Object.entries(DOMAIN_CAPABILITIES).map(([id, capability]) => [id, {
      comparison: capability.comparison,
      ranking: capability.rankingPolicy,
    }]))).toEqual({
      soil: { comparison: "same_metric_unit", ranking: "allowed_when_published" },
      water: { comparison: "same_metric_unit_method_geometry", ranking: "not_allowed" },
      forests: { comparison: "same_metric_unit_method_geometry", ranking: "allowed_when_published" },
      emissions: { comparison: "not_supported", ranking: "not_allowed" },
      risk: { comparison: "not_supported", ranking: "not_allowed" },
    });
  });
});
