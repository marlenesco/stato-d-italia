"use client";

import { useCallback, useMemo, useState } from "react";
import type { EmissionsData, EmissionsOverview } from "../lib/data";
import { MapSidebar } from "./map-sidebar";
import { SoilMap } from "./soil-map";
import { TimelineControl } from "./timeline-control";
import { TerritoryMapSeries } from "./territory-map-series";

function format(value: number) {
  return value.toLocaleString("it-IT", { maximumFractionDigits: 0 });
}

function GreenhouseTrend({ overview }: { overview: EmissionsOverview["greenhouseGases"] }) {
  const values = overview.series.map(([, value]) => value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const points = overview.series.map(([year, value], index) => `${12 + index / Math.max(1, overview.series.length - 1) * 296},${88 - (value - min) / span * 68}`).join(" ");
  const first = overview.series[0];
  const latest = overview.series.at(-1);
  return <figure className="emissions-trend"><figcaption><span>{overview.seriesLabel}</span><strong>{first?.[0]}–{latest?.[0]}</strong></figcaption><svg viewBox="0 0 320 104" role="img" aria-label={`Totale emissioni nette di gas serra in Italia: ${format(first?.[1] ?? 0)} nel ${first?.[0]}, ${format(latest?.[1] ?? 0)} nel ${latest?.[0]} ${overview.unit}`}><path d="M12 88H308" className="chart-axis" /><polyline points={points} className="emissions-chart-line" /><circle cx={points.split(" ").at(-1)?.split(",")[0]} cy={points.split(" ").at(-1)?.split(",")[1]} r="3.8" className="emissions-chart-dot" /></svg><div><span>{first?.[0]}</span><span>{latest?.[0]}</span></div></figure>;
}

function DataRow({ id, label, coverage, detail, note }: { id: string; label: string; coverage: string; detail: string; note: string }) {
  return <section id={id} className="emissions-data-row"><div><p className="eyebrow">Dataset ufficiale</p><h2>{label}</h2></div><div><strong>{coverage}</strong><p>{detail}</p></div><p className="emissions-data-note">{note}</p></section>;
}

export function EmissionsWorkspace({ data }: { data: EmissionsData }) {
  const { overview } = data;
  const latest = overview.greenhouseGases.series.at(-1);
  const maps = useMemo(() => [...data.maps].sort((left, right) => Number(left.periodKey) - Number(right.periodKey)), [data.maps]);
  const [period, setPeriod] = useState(maps.at(-1)?.periodKey);
  const map = maps.find((item) => item.periodKey === period) ?? maps.at(-1);
  const [territory, setTerritory] = useState<{ id: string; name?: string } | undefined>();
  const selectTerritory = useCallback((id: string, name?: string) => setTerritory({ id, name }), []);
  return <section className="domain-site-layout domain-emissions" aria-label="Atlante emissioni">
    <MapSidebar title="Atlante emissioni">
      <a className="sidebar-link sidebar-atlas-link" href="#mappa">Vai alla mappa ↓</a>
      <section className="sidebar-section"><h3>Serie disponibili</h3><ul className="domain-metric-list"><li>Gas serra · Italia</li><li>Inquinanti NFR · Italia</li><li>SNAP provinciale</li></ul></section>
      <TerritoryMapSeries options={maps} territoryId={territory?.id} territoryName={territory?.name} selectedPeriod={map?.periodKey} />
      <section className="sidebar-section"><h3>Copertura</h3><p className="sidebar-context"><strong>1990–2024 nazionale</strong>Provincia: solo 2019 e 2023.</p></section>
      <section className="sidebar-section"><h3>Come leggere</h3><p className="sidebar-context">Non sono concentrazioni misurate né attribuzioni comunali ricavate dividendo la provincia. Emissioni territoriali e dichiarazioni industriali restano dataset diversi.</p></section>
      <a className="sidebar-link" href="#metodo">Fonte e limiti →</a>
    </MapSidebar>
    <div className="domain-site-content">
      <section className="emissions-hero"><div className="emissions-hero-title"><p className="eyebrow">ISPRA · inventari ufficiali</p><h1>Emissioni</h1></div><div className="emissions-hero-copy"><p>Leggi serie nazionali e stime provinciali senza farle diventare la stessa cosa.</p><a className="primary-link" href="#mappa">Apri mappa <span aria-hidden="true">→</span></a></div><div className="emissions-latest"><p className="eyebrow">Italia · {latest?.[0]}</p><strong>{format(latest?.[1] ?? 0)}</strong><span>{overview.greenhouseGases.unit}</span><small>Totale emissioni nette ufficiale.</small></div><GreenhouseTrend overview={overview.greenhouseGases} /></section>
      <section id="mappa" className="domain-workspace emissions-map-workspace" tabIndex={-1} aria-label="Mappa provinciale delle emissioni">
        {map && <TimelineControl periods={maps.map((item) => item.periodKey)} value={map.periodKey} onChange={setPeriod} />}
        {map && overview.map ? <><SoilMap option={map} metricLabel={overview.map.label} geometryUrl={data.geometryByPeriod[map.periodKey]} colorRamp="emissions" selectedTerritoryId={territory?.id} onTerritorySelect={selectTerritory} /><p className="emissions-map-note">{overview.map.detail} {overview.map.coverage}.</p></> : <p role="status">Mappa provinciale in preparazione nella release attiva.</p>}
      </section>
      <div className="emissions-data-list">
        <DataRow id="serra" label={overview.greenhouseGases.label} coverage={overview.greenhouseGases.coverage} detail={overview.greenhouseGases.metrics.join(" · ")} note="Inventario territoriale nazionale. Serie storica ufficiale; le categorie sorgente restano separate." />
        <DataRow id="inquinanti" label={overview.airPollutantsNfr.label} coverage={overview.airPollutantsNfr.coverage} detail={`${overview.airPollutantsNfr.metrics} inquinanti · ${overview.airPollutantsNfr.sourceDimensions.join(" · ")}`} note="Inventario territoriale nazionale per settore NFR. Nessun totale derivato dalla UI." />
        <DataRow id="province" label={overview.provincialDisaggregation.label} coverage={overview.provincialDisaggregation.coverage} detail={`${overview.provincialDisaggregation.metrics} inquinanti · ${overview.provincialDisaggregation.sourceDimensions.join(" · ")}`} note="Disaggregazione top-down ISPRA. Non è dato comunale, non è dichiarazione di stabilimento." />
      </div>
      <section id="metodo" className="emissions-method"><p className="eyebrow">Fuori da questa release</p><p>EEA Industrial Emissions aggiungerà stabilimenti geolocalizzati come emissioni industriali dichiarate. Sarà una vista distinta; eventuale Comune deriva solo da spatial join con confini ISTAT.</p></section>
    </div>
  </section>;
}
