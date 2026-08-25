"use client";

import { useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { WaterData } from "../lib/data";
import { WaterMap } from "./water-map";

const labels: Record<string, string> = {
  water_total_precipitation_mm: "Precipitazione totale",
  water_actual_evapotranspiration_mm: "Evapotraspirazione effettiva",
  water_internal_flow_mm: "Risorsa idrica rinnovabile",
  water_aquifer_recharge_mm: "Ricarica acquiferi",
  water_surface_runoff_mm: "Ruscellamento superficiale",
};

export function WaterWorkspace({ data }: { data: WaterData }) {
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

  function update(nextMetric: string, nextPeriod: string) {
    const query = new URLSearchParams({ metric: nextMetric, period: nextPeriod });
    router.replace(`${pathname}?${query.toString()}`, { scroll: false });
  }

  return <section className="water-workspace" aria-label="Atlante idrico"><div className="water-workspace-head"><div><p className="eyebrow">Esplora dati</p><h2>Regioni, 1951–2025</h2></div><p>URL con metrica e anno. Serie annuale completa: slider rappresenta tempo reale, non periodi aggregati.</p></div><div className="water-controls"><label>Metrica<select value={metric} onChange={(event) => { const nextMetric = event.target.value; const latest = data.maps.filter((item) => item.metricId === nextMetric).map((item) => item.periodKey).sort().at(-1) ?? "2025"; update(nextMetric, latest); }}>{metrics.map((item) => <option key={item} value={item}>{labels[item] ?? item}</option>)}</select></label><output aria-live="polite"><span>Anno</span><strong>{selected?.periodKey ?? "—"}</strong></output></div>{selected ? <><fieldset className="water-timeline"><legend>Anno di riferimento</legend><input type="range" min="0" max={Math.max(0, years.length - 1)} value={yearIndex} onChange={(event) => update(metric, years[Number(event.target.value)])} aria-label="Cambia anno" /><div><span>{years[0]}</span><span>{years[Math.floor(years.length / 2)]}</span><span>{years.at(-1)}</span></div></fieldset><WaterMap option={selected} metricLabel={labels[metric] ?? metric} geometryUrl={data.geometry.region} /></> : <p role="alert">Metrica o anno non presenti nella release attiva.</p>}<section className="water-limit"><p className="eyebrow">Come leggere</p><p>Valori BIGBANG 10.0: stime modellistiche annuali. Riguardano solo Regioni. Release corrente non pubblica ranking né confronto “migliore/peggiore”.</p></section><details className="provenance"><summary>Fonte e metodo · release {data.releaseId}</summary><pre>{JSON.stringify(data.provenance, null, 2)}</pre></details></section>;
}
