"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { WaterData, WaterOverview as WaterOverviewData } from "../lib/data";
import { ExplorerToolbar } from "./explorer-toolbar";
import { WaterMap } from "./water-map";
import { WaterOverview } from "./water-overview";
import { TimelineControl } from "./timeline-control";

type WaterLevel = "region" | "province";

const metrics = [
  { official: "water_total_precipitation_mm", derived: "water_total_precipitation_mm_zonal_mean", label: "Precipitazione totale" },
  { official: "water_actual_evapotranspiration_mm", derived: "water_actual_evapotranspiration_mm_zonal_mean", label: "Evapotraspirazione effettiva" },
  { official: "water_internal_flow_mm", derived: "water_internal_flow_mm_zonal_mean", label: "Risorsa idrica rinnovabile" },
  { official: "water_aquifer_recharge_mm", derived: "water_aquifer_recharge_mm_zonal_mean", label: "Ricarica acquiferi" },
  { official: "water_surface_runoff_mm", derived: "water_surface_runoff_mm_zonal_mean", label: "Ruscellamento superficiale" },
] as const;

function metricForLevel(candidate: string | null, level: WaterLevel) {
  const definition = metrics.find((item) => item.official === candidate || item.derived === candidate) ?? metrics[0];
  return level === "region" ? definition.official : definition.derived;
}

function labelForMetric(metric: string) {
  return metrics.find((item) => item.official === metric || item.derived === metric)?.label ?? metric;
}

export function WaterWorkspace({ data, overview }: { data: WaterData; overview: WaterOverviewData }) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const level: WaterLevel = searchParams.get("level") === "province" ? "province" : "region";
  const metric = metricForLevel(searchParams.get("metric"), level);
  const available = useMemo(
    () => data.maps.filter((item) => item.metricId === metric && item.level === level).sort((left, right) => Number(left.periodKey) - Number(right.periodKey)),
    [data.maps, level, metric],
  );
  const years = available.map((item) => item.periodKey);
  const requestedYear = searchParams.get("period");
  const selected = available.find((item) => item.periodKey === requestedYear) ?? available.at(-1);
  const requestedTerritory = searchParams.get("territory") ?? undefined;
  const [territory, setTerritory] = useState<{ id: string; name?: string } | undefined>(() => requestedTerritory ? { id: requestedTerritory } : undefined);

  useEffect(() => {
    setTerritory((current) => requestedTerritory ? current?.id === requestedTerritory ? current : { id: requestedTerritory } : undefined);
  }, [requestedTerritory]);

  function update(nextLevel: WaterLevel, nextMetric: string, nextPeriod: string, nextTerritory?: string) {
    const query = new URLSearchParams({ level: nextLevel, metric: nextMetric, period: nextPeriod });
    if (nextTerritory) query.set("territory", nextTerritory);
    router.replace(`${pathname}?${query.toString()}`, { scroll: false });
  }

  const selectTerritory = useCallback((id: string, name?: string) => {
    setTerritory({ id, name });
    update(level, metric, selected?.periodKey ?? years.at(-1) ?? "", id);
  }, [level, metric, pathname, router, selected?.periodKey, years]);

  function changeMetric(nextMetric: string) {
    const nextAvailable = data.maps.filter((item) => item.metricId === nextMetric && item.level === level).sort((left, right) => Number(left.periodKey) - Number(right.periodKey));
    update(level, nextMetric, nextAvailable.find((item) => item.periodKey === selected?.periodKey)?.periodKey ?? nextAvailable.at(-1)?.periodKey ?? "", territory?.id);
  }

  function changeLevel(nextLevel: string) {
    const targetLevel = nextLevel === "province" ? "province" : "region";
    const nextMetric = metricForLevel(metric, targetLevel);
    const nextAvailable = data.maps.filter((item) => item.metricId === nextMetric && item.level === targetLevel).sort((left, right) => Number(left.periodKey) - Number(right.periodKey));
    setTerritory(undefined);
    update(targetLevel, nextMetric, nextAvailable.find((item) => item.periodKey === selected?.periodKey)?.periodKey ?? nextAvailable.at(-1)?.periodKey ?? "");
  }

  const levelLabel = level === "province" ? "Province" : "Regioni";
  const derived = level === "province";
  return <section className="water-site-layout explorer-layout" aria-label="Atlante idrico">
    <div className="water-site-content">
      <WaterOverview overview={overview} />
      <ExplorerToolbar label="Misura" value={metric} onChange={changeMetric} items={metrics.map((item) => ({ id: level === "region" ? item.official : item.derived, label: item.label, meta: "mm" }))} levels={[{ id: "region", label: "Regioni" }, { id: "province", label: "Province" }]} level={level} onLevelChange={changeLevel} context={`${selected?.periodKey ?? "—"} · ${levelLabel} italiane`} />
      <section id="atlante" className="water-workspace map-workspace-v2" tabIndex={-1} aria-label={`Mappa ${level === "province" ? "provinciale" : "regionale"}`}>
        {selected && <TimelineControl periods={years} value={selected.periodKey} onChange={(period) => update(level, metric, period, territory?.id)} />}
        {selected ? <WaterMap option={selected} metricLabel={labelForMetric(metric)} geometryUrl={data.mapGeometry?.[selected.logicalPath]} territoryLevel={level} derived={derived} selectedTerritoryId={territory?.id} seriesOptions={available} onTerritorySelect={selectTerritory} /> : <p role="alert">Metrica o anno non presenti nella release attiva.</p>}
        <div className="map-reading-panel"><p>{derived ? "Elaborazione Stato d’Italia su raster ISPRA BIGBANG 10.0 · media zonale pesata per area. Non è dato ufficiale ISPRA." : "Stime ufficiali modellistiche BIGBANG 10.0. Nessun ranking “migliore/peggiore”."}</p></div>
        <section className="water-limit"><p className="eyebrow">Come leggere</p><p>{derived ? "Valori provinciali derivati da Stato d’Italia. Timeline con sole annualità e geometrie territoriali effettivamente disponibili." : "Valori BIGBANG 10.0: stime modellistiche annuali ufficiali. Scala colori relativa a metrica e anno selezionati."}</p></section>
        <details className="provenance"><summary>Fonte e metodo · release {data.releaseId}</summary><pre>{JSON.stringify(data.provenance, null, 2)}</pre></details>
      </section>
    </div>
  </section>;
}
