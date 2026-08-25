import Link from "next/link";
import type { HomeOverview } from "../lib/data";
import { PageSidebar } from "./page-sidebar";

function number(value: number, maximumFractionDigits = 0) {
  return new Intl.NumberFormat("it-IT", { maximumFractionDigits }).format(value);
}

function annualPoints(series: HomeOverview["netSeries"]) {
  return series.filter(([, start, end]) => Number(end.slice(0, 4)) - Number(start.slice(0, 4)) === 1);
}

function TrendLine({ series }: { series: HomeOverview["netSeries"] }) {
  const points = annualPoints(series);
  const values = points.map(([, , , value]) => value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const coordinates = points.map(([, , end, value], index) => {
    const x = 10 + (index / Math.max(1, points.length - 1)) * 280;
    const y = 82 - ((value - min) / span) * 64;
    return `${x},${y}`;
  }).join(" ");
  return <figure className="trend-figure">
    <figcaption><span>Serie annua comparabile</span><strong>2015–2024</strong></figcaption>
    <svg viewBox="0 0 300 96" role="img" aria-label={`Incremento netto nazionale annuo: da ${number(values[0])} a ${number(values.at(-1) ?? 0)} ettari`}>
      <path d="M10 82H290" className="chart-axis" />
      <polyline points={coordinates} className="chart-line" />
      {coordinates.split(" ").map((point, index) => <circle key={point} cx={point.split(",")[0]} cy={point.split(",")[1]} r={index === points.length - 1 ? 4 : 2.2} className="chart-dot" />)}
    </svg>
    <div className="trend-scale"><span>{points[0]?.[2].slice(0, 4)}</span><span>{points.at(-1)?.[2].slice(0, 4)}</span></div>
  </figure>;
}

function signalHref(period: string, territoryId?: string) {
  const params = new URLSearchParams({ metric: "soil_net_consumption_hectares", level: "region", period });
  if (territoryId) params.set("territory", territoryId);
  return `/suolo?${params.toString()}#mappa`;
}

export function HomeOverview({ overview }: { overview: HomeOverview }) {
  const previous = overview.previousChange?.status === "available" && overview.previousChange.value !== undefined && overview.previousChange.value !== null
    ? `${overview.previousChange.value > 0 ? "+" : ""}${number(overview.previousChange.value, 1)} ${overview.previousChange.unit}`
    : "Non disponibile";
  return <section className="home-site-layout">
    <PageSidebar eyebrow="Osservatorio" title="Italia">
      <nav className="page-sidebar-nav" aria-label="Sezioni panoramica"><a href="#lettura">Cosa emerge</a><a href="#segnali">Segnali regionali</a><Link href={signalHref(overview.periodKey.replace("–", "-"))}>Esplora mappa suolo →</Link></nav>
      <section className="sidebar-section"><h3>Periodo corrente</h3><p className="sidebar-context"><strong>{overview.periodKey}</strong>Incremento netto di suolo consumato.</p></section>
      <section className="sidebar-section"><p className="sidebar-context">Fonti, periodi e limiti restano visibili in ogni approfondimento.</p></section>
    </PageSidebar>
    <div className="home-site-content">
    <section className="home-hero">
      <p className="eyebrow">Osservatorio territoriale · dati ufficiali</p>
      <h1>Come cambia<br />l&apos;Italia.</h1>
      <p className="home-lede">Leggi cambiamenti ambientali e territoriali nel tempo. Fonti, periodi e limiti restano sempre visibili.</p>
      <Link className="primary-link" href={signalHref(overview.periodKey.replace("–", "-"))}>Esplora consumo di suolo <span aria-hidden="true">→</span></Link>
    </section>

    <section id="lettura" className="national-reading" aria-labelledby="national-reading-title" tabIndex={-1}>
      <div><p className="eyebrow">Italia · {overview.periodKey}</p><h2 id="national-reading-title">Cosa emerge</h2></div>
      <p className="reading-copy">Nel periodo più recente, incremento netto nazionale: <strong>{number(overview.latestNet.value, 0)} {overview.latestNet.unit}</strong>. Rispetto al periodo annuale precedente: <strong>{previous}</strong>. Il valore è osservazione ufficiale; ranking e segnali sono elaborazioni versionate.</p>
      <TrendLine series={overview.netSeries} />
    </section>

    <section id="segnali" className="signal-grid" aria-label="Segnali regionali" tabIndex={-1}>
      <article className="signal-panel signal-panel-alert">
        <p className="eyebrow">Da approfondire</p>
        <h2>Incrementi netti più alti</h2>
        <p>Regioni con maggior incremento netto registrato. Non è un giudizio di qualità o responsabilità.</p>
        <ol className="signal-list">{overview.watchRegions.map((region) => <li key={region.territoryId}><Link href={signalHref(overview.periodKey.replace("–", "-"), region.territoryId)}><span>{region.name}</span><strong>{number(region.value, 1)} ha</strong></Link></li>)}</ol>
      </article>
      <article className="signal-panel signal-panel-calm">
        <p className="eyebrow">Incremento più contenuto</p>
        <h2>Valori più bassi nel periodo</h2>
        <p>Confronto sul solo incremento netto osservato. Non equivale a “regione migliore”.</p>
        <ol className="signal-list">{overview.lowerChangeRegions.map((region) => <li key={region.territoryId}><Link href={signalHref(overview.periodKey.replace("–", "-"), region.territoryId)}><span>{region.name}</span><strong>{number(region.value, 1)} ha</strong></Link></li>)}</ol>
      </article>
    </section>

    <section className="method-note"><p><strong>Come leggere questa pagina.</strong> “Da approfondire” ordina valori ufficiali per incremento netto. Non assegna cause né giudizi. Algoritmo ranking: {overview.algorithmVersion}. <Link href="/suolo#mappa">Apri dati, mappa e metodo</Link>.</p><span>Release {overview.releaseId}</span></section>
    </div>
  </section>;
}
