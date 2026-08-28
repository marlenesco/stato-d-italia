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
  const atlasHref = (metricId: string, period: string) => `/acqua?metric=${metricId}&period=${period}#atlante`;
  return <>
    <header className="workspace-header water-workspace-header"><div><p className="eyebrow">BIGBANG 10.0 · serie ufficiale modellistica</p><h1>Acqua</h1></div><p>Bilancio idrologico annuale per Italia e Regioni. Solo anni pubblicati, nessuna interpolazione.</p>{precipitation.length > 1 && <CountryTrend series={precipitation} />}</header>
    <section className="domain-data-strip" aria-label="Ultime osservazioni nazionali">{overview.countryProfile.latestObservations.map((observation) => <Link key={observation.metricId} href={atlasHref(observation.metricId, observation.periodEnd.slice(0, 4))}><span>{labels[observation.metricId] ?? observation.metricId}</span><strong>{format(observation.value, observation.unit)}</strong><small>{observation.periodEnd.slice(0, 4)} · Italia</small></Link>)}</section>
  </>;
}
