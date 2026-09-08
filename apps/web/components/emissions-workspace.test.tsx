import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { EmissionsNationalDataset, EmissionsNationalSeries } from "../lib/data";
import { dimensionOptionLabel, findNationalSeries, SeriesChart } from "./emissions-workspace";

const greenhouse: EmissionsNationalSeries = { id: "ghg-total", metricId: "emissions_ghg_co2e", metricLabel: "Gas serra", dimensionCode: "Total", dimensionLabel: "Totale netto", sourceUnit: "kt CO2 eq", unit: "kt CO2 eq", values: [[1990, 520], [2024, 385]] };
const nfr: EmissionsNationalSeries = { id: "nfr-road", metricId: "emissions_air_nox_as_no2", metricLabel: "NOx", dimensionCode: "1A3bi", dimensionLabel: "Automobili", sourceUnit: "Mg", unit: "Mg", values: [[1990, 100], [2024, 42]] };
const dataset: EmissionsNationalDataset = { kind: "official_national_series", series: [greenhouse, nfr] };

describe("specialized national Emissions explorer", () => {
  it("keeps greenhouse and NFR dimension selection separate", () => {
    expect(findNationalSeries(dataset, "emissions_ghg_co2e", "Total")).toBe(greenhouse);
    expect(findNationalSeries(dataset, "emissions_air_nox_as_no2", "1A3bi")).toBe(nfr);
    expect(dimensionOptionLabel(nfr)).toBe("1A3bi · Automobili");
  });

  it("renders the official annual values in the specialized SeriesChart table", () => {
    const html = renderToStaticMarkup(<SeriesChart series={nfr} />);
    expect(html).toContain("1990");
    expect(html).toContain("2024");
    expect(html).toContain("100 Mg");
    expect(html).toContain("42 Mg");
  });
});
