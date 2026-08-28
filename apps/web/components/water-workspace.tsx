"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { WaterData, WaterOverview as WaterOverviewData } from "../lib/data";
import { ExplorerToolbar } from "./explorer-toolbar";
import { WaterMap } from "./water-map";
import { WaterOverview } from "./water-overview";
import { TimelineControl } from "./timeline-control";

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
  const requestedTerritory = searchParams.get("territory") ?? undefined;
  const [territory, setTerritory] = useState<{ id: string; name?: string } | undefined>(() => requestedTerritory ? { id: requestedTerritory } : undefined);

  useEffect(() => {
    setTerritory((current) => requestedTerritory ? current?.id === requestedTerritory ? current : { id: requestedTerritory } : undefined);
  }, [requestedTerritory]);

  function update(nextMetric: string, nextPeriod: string, nextTerritory = territory?.id ?? requestedTerritory) {
    const query = new URLSearchParams({ metric: nextMetric, period: nextPeriod });
    if (nextTerritory) query.set("territory", nextTerritory);
    router.replace(`${pathname}?${query.toString()}`, { scroll: false });
  }

  const selectTerritory = useCallback((id: string, name?: string) => {
    setTerritory({ id, name });
    update(metric, selected?.periodKey ?? years.at(-1) ?? "", id);
  }, [metric, pathname, router, searchParams, selected?.periodKey, years]);

  function changeMetric(nextMetric: string) {
    const latest = data.maps.filter((item) => item.metricId === nextMetric).map((item) => item.periodKey).sort().at(-1) ?? "2025";
    update(nextMetric, latest);
  }

  return <section className="water-site-layout explorer-layout" aria-label="Atlante idrico">
    <div className="water-site-content">
      <WaterOverview overview={overview} />
      <ExplorerToolbar label="Misura" value={metric} onChange={changeMetric} items={metrics.map((id) => ({ id, label: labels[id] ?? id, meta: "mm" }))} context={`${selected?.periodKey ?? "—"} · Regioni italiane`} />
      <section id="atlante" className="water-workspace map-workspace-v2" tabIndex={-1} aria-label="Mappa regionale">
        {selected && <TimelineControl periods={years} value={selected.periodKey} onChange={(period) => update(metric, period)} />}
        {selected ? <WaterMap option={selected} metricLabel={labels[metric] ?? metric} geometryUrl={data.geometry.region} selectedTerritoryId={territory?.id} seriesOptions={available} onTerritorySelect={selectTerritory} /> : <p role="alert">Metrica o anno non presenti nella release attiva.</p>}
        <div className="map-reading-panel"><p>Stime ufficiali modellistiche BIGBANG 10.0. Nessun ranking “migliore/peggiore”.</p></div>
        <section className="water-limit"><p className="eyebrow">Come leggere</p><p>Valori BIGBANG 10.0: stime modellistiche annuali. Scala colori relativa a metrica e anno selezionati.</p></section>
        <details className="provenance"><summary>Fonte e metodo · release {data.releaseId}</summary><pre>{JSON.stringify(data.provenance, null, 2)}</pre></details>
      </section>
    </div>
  </section>;
}
