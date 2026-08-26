"use client";

import { useCallback, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { WaterData, WaterOverview as WaterOverviewData } from "../lib/data";
import { ExposedMenu, MapSidebar } from "./map-sidebar";
import { WaterMap } from "./water-map";
import { WaterOverview } from "./water-overview";
import { TimelineControl } from "./timeline-control";
import { TerritoryMapSeries } from "./territory-map-series";

const labels: Record<string, string> = {
  water_total_precipitation_mm: "Precipitazione totale",
  water_actual_evapotranspiration_mm: "Evapotraspirazione effettiva",
  water_internal_flow_mm: "Risorsa idrica rinnovabile",
  water_aquifer_recharge_mm: "Ricarica acquiferi",
  water_surface_runoff_mm: "Ruscellamento superficiale",
};

export function WaterWorkspace({ data, overview }: { data: WaterData; overview: WaterOverviewData }) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const metrics = useMemo(() => [...new Set(data.maps.map((item) => item.metricId))], [data.maps]);
  const requestedMetric = searchParams.get("metric");
  const metric = requestedMetric && metrics.includes(requestedMetric) ? requestedMetric : "water_total_precipitation_mm";
  const available = data.maps.filter((item) => item.metricId === metric && item.level === "region").sort((left, right) => Number(left.periodKey) - Number(right.periodKey));
  const years = available.map((item) => item.periodKey);
  const requestedYear = searchParams.get("period");
  const yearIndex = Math.max(0, years.indexOf(requestedYear ?? years.at(-1) ?? ""));
  const selected = available[yearIndex] ?? available.at(-1);
  const [territory, setTerritory] = useState<{ id: string; name?: string } | undefined>();
  const selectTerritory = useCallback((id: string, name?: string) => setTerritory({ id, name }), []);

  function update(nextMetric: string, nextPeriod: string) {
    const query = new URLSearchParams({ metric: nextMetric, period: nextPeriod });
    router.replace(`${pathname}?${query.toString()}`, { scroll: false });
  }

  function changeMetric(nextMetric: string) {
    const latest = data.maps.filter((item) => item.metricId === nextMetric).map((item) => item.periodKey).sort().at(-1) ?? "2025";
    update(nextMetric, latest);
  }

  return <section className="water-site-layout" aria-label="Atlante idrico">
    <MapSidebar title="Atlante acqua">
      <a className="sidebar-link sidebar-atlas-link" href="#atlante">Vai alla mappa ↓</a>
      <ExposedMenu label="Metrica" value={metric} onChange={changeMetric} items={metrics.map((id) => ({ id, label: labels[id] ?? id, meta: "mm" }))} />
      <TerritoryMapSeries options={available} territoryId={territory?.id} territoryName={territory?.name} selectedPeriod={selected?.periodKey} />
      <section className="sidebar-section"><h3>Copertura</h3><p className="sidebar-context"><strong>Regioni · 1951–2025</strong>Stime ufficiali modellistiche BIGBANG 10.0.</p></section>
      <section className="sidebar-section"><p className="sidebar-context">Release corrente non pubblica ranking o “migliore/peggiore”.</p></section>
    </MapSidebar>
    <div className="water-site-content">
      <WaterOverview overview={overview} />
      <section id="atlante" className="water-workspace" tabIndex={-1} aria-label="Mappa regionale">
        {selected && <TimelineControl periods={years} value={selected.periodKey} onChange={(period) => update(metric, period)} />}
        {selected ? <WaterMap option={selected} metricLabel={labels[metric] ?? metric} geometryUrl={data.geometry.region} onTerritorySelect={selectTerritory} /> : <p role="alert">Metrica o anno non presenti nella release attiva.</p>}
        <section className="water-limit"><p className="eyebrow">Come leggere</p><p>Valori BIGBANG 10.0: stime modellistiche annuali. Scala colori relativa a metrica e anno selezionati.</p></section>
        <details className="provenance"><summary>Fonte e metodo · release {data.releaseId}</summary><pre>{JSON.stringify(data.provenance, null, 2)}</pre></details>
      </section>
    </div>
  </section>;
}
