import Link from "next/link";
import type { WaterOverview } from "../lib/data";

const labels: Record<string, string> = {
  water_total_precipitation_mm: "Precipitazione totale",
  water_actual_evapotranspiration_mm: "Evapotraspirazione effettiva",
  water_internal_flow_mm: "Risorsa idrica rinnovabile",
  water_aquifer_recharge_mm: "Ricarica acquiferi",
  water_surface_runoff_mm: "Ruscellamento superficiale",
};

function format(value: number, unit: string) {
  return `${value.toLocaleString("it-IT", { maximumFractionDigits: 1 })} ${unit}`;
}

function CountryTrend({ series }: { series: Array<[number, number]> }) {
  const values = series.map(([, value]) => value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const points = series.map(([year, value], index) => `${10 + index / Math.max(1, series.length - 1) * 280},${82 - (value - min) / span * 64}`).join(" ");
  return <figure className="water-trend"><figcaption><span>Italia · serie ufficiale modellistica</span><strong>{series[0]?.[0]}–{series.at(-1)?.[0]}</strong></figcaption><svg viewBox="0 0 300 96" role="img" aria-label={`Precipitazione totale Italia, da ${format(values[0] ?? 0, "mm")} a ${format(values.at(-1) ?? 0, "mm")}`}><path d="M10 82H290" className="chart-axis" /><polyline points={points} className="water-chart-line" /><circle cx={points.split(" ").at(-1)?.split(",")[0]} cy={points.split(" ").at(-1)?.split(",")[1]} r="3.8" className="water-chart-dot" /></svg><div><span>{series[0]?.[0]}</span><span>{series.at(-1)?.[0]}</span></div></figure>;
}

export function WaterOverview({ overview }: { overview: WaterOverview }) {
  const precipitation = overview.countryProfile.historicalSeries.find((item) => item.metricId === "water_total_precipitation_mm")?.values ?? [];
  return <>
    <section className="water-hero"><div><p className="eyebrow">BIGBANG 10.0 · serie 1951–2025</p><h1>Acqua, anno per anno.</h1><p>Stime ufficiali modellistiche per Italia e Regioni. Una mappa per ogni anno; nessuna interpolazione.</p><Link className="water-primary-link" href="/acqua?metric=water_total_precipitation_mm&period=2025">Apri atlante 2025 <span aria-hidden="true">→</span></Link></div>{precipitation.length > 1 && <CountryTrend series={precipitation} />}</section>
    <section className="water-reading" aria-labelledby="water-reading-title"><div><p className="eyebrow">Italia · 2025</p><h2 id="water-reading-title">Cinque componenti, stessa scala</h2></div><p>Millimetri annui stimati. Le grandezze descrivono aspetti diversi del ciclo idrologico: non sono un punteggio né un ranking.</p></section>
    <section className="water-metric-grid" aria-label="Ultime osservazioni nazionali">{overview.countryProfile.latestObservations.map((observation) => <Link key={observation.metricId} href={`/acqua?metric=${observation.metricId}&period=${observation.periodEnd.slice(0, 4)}`}><span>{labels[observation.metricId] ?? observation.metricId}</span><strong>{format(observation.value, observation.unit)}</strong><small>{observation.periodEnd.slice(0, 4)} · Italia</small></Link>)}</section>
  </>;
}
