"use client";

import Link from "next/link";
import { useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { MapOption, SoilData } from "../lib/data";
import { SoilMap } from "./soil-map";
import { TimelineControl } from "./timeline-control";

type MappableLevel = Exclude<MapOption["level"], "country">;

const metricLabels: Record<string, string> = {
  soil_net_consumption_hectares: "Incremento netto di suolo consumato",
  soil_gross_consumption_hectares: "Incremento lordo di suolo consumato",
  soil_restoration_hectares: "Ripristino di suolo",
  soil_consumed_hectares: "Suolo consumato (ha)",
  soil_consumed_share: "Suolo consumato (%)",
  water_total_precipitation_mm: "Precipitazione totale",
  water_actual_evapotranspiration_mm: "Evapotraspirazione effettiva",
  water_internal_flow_mm: "Risorsa idrica rinnovabile",
  water_aquifer_recharge_mm: "Ricarica acquiferi",
  water_surface_runoff_mm: "Ruscellamento superficiale",
};

function rankingPath(option: MapOption) {
  return `delivery/soil/rankings/${option.metricId}/${option.periodKey}/${option.level}.json`;
}

function comparePeriods(left: string, right: string) {
  return Number(left.slice(0, 4)) - Number(right.slice(0, 4)) || left.localeCompare(right);
}

function levelLabel(level: MappableLevel) {
  return level === "municipality" ? "Comuni" : level === "province" ? "Province" : "Regioni";
}

export function ThemeWorkspace({ data, themeLabel }: { data: SoilData; themeLabel: string }) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const metrics = useMemo(() => [...new Set(data.maps.map((item) => item.metricId))], [data.maps]);
  const requestedMetric = searchParams.get("metric");
  const metric = requestedMetric && metrics.includes(requestedMetric) ? requestedMetric : metrics[0];
  const levels = useMemo(() => Array.from(new Set(data.maps.filter((item) => item.metricId === metric).map((item) => item.level))).filter((item): item is MappableLevel => item !== "country"), [data.maps, metric]);
  const requestedLevel = searchParams.get("level") as MappableLevel | null;
  const level = requestedLevel && levels.includes(requestedLevel) ? requestedLevel : (levels.includes("municipality") ? "municipality" : levels[0]);
  const available = data.maps.filter((item) => item.metricId === metric && item.level === level).sort((left, right) => comparePeriods(left.periodKey, right.periodKey));
  const requestedPeriod = searchParams.get("period");
  const selected = available.find((item) => item.periodKey === requestedPeriod) ?? available.at(-1);
  const periods = available.map((item) => item.periodKey);

  function update(params: Record<string, string | undefined>) {
    const next = new URLSearchParams(searchParams.toString());
    Object.entries(params).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key));
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  }

  function changeMetric(nextMetric: string) {
    const nextLevels = Array.from(new Set(data.maps.filter((item) => item.metricId === nextMetric && item.level !== "country").map((item) => item.level))) as MappableLevel[];
    const nextLevel = nextLevels.includes(level) ? level : (nextLevels.includes("municipality") ? "municipality" : nextLevels[0]);
    const nextPeriods = data.maps.filter((item) => item.metricId === nextMetric && item.level === nextLevel).sort((left, right) => comparePeriods(left.periodKey, right.periodKey));
    update({ metric: nextMetric, level: nextLevel, period: nextPeriods.at(-1)?.periodKey, territory: undefined });
  }

  return <section className="workspace" aria-label={`Esplorazione ${themeLabel}`}>
    <div className="workspace-kicker"><p className="eyebrow">Esplora dati</p><p>URL aggiornato con metrica, livello e periodo: vista condivisibile.</p></div>
    <div className="controls" aria-label="Filtri mappa">
      <label>Metrica<select value={metric} onChange={(event) => changeMetric(event.target.value)}>{metrics.map((item) => <option key={item} value={item}>{metricLabels[item] ?? item}</option>)}</select></label>
      <label>Livello<select value={level} onChange={(event) => {
        const nextLevel = event.target.value as MappableLevel;
        const nextPeriod = data.maps.filter((item) => item.metricId === metric && item.level === nextLevel).sort((left, right) => comparePeriods(left.periodKey, right.periodKey)).at(-1)?.periodKey;
        update({ level: nextLevel, period: nextPeriod, territory: undefined });
      }}>{levels.map((item) => <option key={item} value={item}>{levelLabel(item)}</option>)}</select></label>
      <Link className="control-link" href="/">Leggi panoramica nazionale</Link>
    </div>
    {selected && <TimelineControl periods={periods} value={selected.periodKey} onChange={(period) => update({ period, territory: undefined })} />}
    {selected ? <SoilMap option={selected} metricLabel={metricLabels[selected.metricId] ?? selected.metricId} geometryUrl={data.geometry[level]} rankingUrl={data.rankings[rankingPath(selected)]} selectedTerritoryId={searchParams.get("territory") ?? undefined} /> : <p role="alert">Combinazione non disponibile nella release attiva.</p>}
    <details className="provenance"><summary>Fonte, metodo, limiti</summary><p>Valori in mappa: osservazioni ufficiali. Ranking e percentili: elaborazioni riproducibili del progetto.</p><pre>{JSON.stringify(data.provenance, null, 2)}</pre></details>
  </section>;
}
