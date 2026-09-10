import { describe, expect, it } from "vitest";
import { formatPeriodLabel } from "./period-label";

describe("formatPeriodLabel", () => {
  it.each([
    ["2018-2018", "2018"],
    ["2018–2018", "2018"],
    ["2018-2021", "2018-2021"],
    [undefined, "—"],
  ])("formats %s for display as %s", (period, expected) => {
    expect(formatPeriodLabel(period)).toBe(expected);
  });
});
