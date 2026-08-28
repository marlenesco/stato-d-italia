import Link from "next/link";
import type { HomeDomainSignal, HomeOverview } from "../lib/data";

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
  const coordinates = points.map(([, , , value], index) => `${10 + index / Math.max(1, points.length - 1) * 280},${82 - (value - min) / span * 64}`).join(" ");
  return <figure className="home-trend"><figcaption><span>Incremento netto annuo</span><strong>{points[0]?.[2].slice(0, 4)}–{points.at(-1)?.[2].slice(0, 4)}</strong></figcaption><svg viewBox="0 0 300 96" role="img" aria-label={`Incremento netto nazionale annuo: da ${number(values[0])} a ${number(values.at(-1) ?? 0)} ettari`}><path d="M10 82H290" className="chart-axis" /><polyline points={coordinates} className="chart-line" /></svg></figure>;
}

function DomainSignal({ signal }: { signal: HomeDomainSignal }) {
  const kind = signal.kind === "official" ? "Dato ufficiale" : signal.kind === "modelled" ? "Stima ufficiale" : "Elaborazione dichiarata";
  return <article className={`home-domain-row home-domain-${signal.id}`}>
    <div className="home-domain-name"><p>{kind}</p><h3>{signal.title}</h3></div>
    <div className="home-domain-value"><span>{signal.label}</span><strong>{signal.displayValue} <small>{signal.unit}</small></strong><p>{signal.period}</p></div>
    <p className="home-domain-note">{signal.note}</p>
    <Link href={signal.href}>Apri {signal.title.toLowerCase()} <span aria-hidden="true">→</span></Link>
  </article>;
}

export function HomeOverview({ overview, signals }: { overview: HomeOverview; signals: HomeDomainSignal[] }) {
  const previous = overview.previousChange?.status === "available" && overview.previousChange.value !== undefined && overview.previousChange.value !== null
    ? `${overview.previousChange.value > 0 ? "+" : ""}${number(overview.previousChange.value, 1)} ${overview.previousChange.unit}`
    : "Non disponibile";
  return <div className="home-dashboard">
    <header className="home-intro"><div><p className="eyebrow">Osservatorio territoriale · fonti verificabili</p><h1>Dati per leggere l&apos;Italia.</h1></div><p>Ambiente e territorio, senza punteggi opachi. Ogni dato mantiene periodo, scala geografica e provenienza.</p><small>Release {overview.releaseId}</small></header>

    <section className="home-current" aria-labelledby="home-current-title"><div><p className="eyebrow">Italia · {overview.periodKey}</p><h2 id="home-current-title">Suolo consumato: ultimo incremento netto</h2><p>Osservazione ufficiale ISPRA/SNPA. Rispetto al periodo precedente: <strong>{previous}</strong>.</p><Link href={`/suolo?metric=soil_net_consumption_hectares&level=region&period=${overview.periodKey.replace("–", "-")}#mappa`}>Vedi territori e mappa →</Link></div><div className="home-current-value"><strong>{number(overview.latestNet.value, 0)}</strong><span>{overview.latestNet.unit}</span><TrendLine series={overview.netSeries} /></div></section>

    <section className="home-domains" aria-labelledby="home-domains-title"><header><p className="eyebrow">Domini disponibili</p><h2 id="home-domains-title">Un ingresso chiaro per ogni tema</h2><p>Valori nazionali quando pubblicati; copertura della release quando un totale nazionale non sarebbe corretto.</p></header>{signals.map((signal) => <DomainSignal key={signal.id} signal={signal} />)}</section>

    <section className="home-regions" aria-labelledby="home-regions-title"><header><p className="eyebrow">Confronto regionale · {overview.periodKey}</p><h2 id="home-regions-title">Incrementi netti più alti</h2><p>Ordine del valore osservato, non giudizio su qualità o responsabilità.</p></header><ol>{overview.watchRegions.map((region) => <li key={region.territoryId}><span>{region.name}</span><strong>{number(region.value, 1)} ha</strong></li>)}</ol><Link href="/suolo?metric=soil_net_consumption_hectares&level=region#mappa">Apri confronto completo →</Link></section>

    <footer className="home-method"><p><strong>Come leggere.</strong> Valori ufficiali, stime modellistiche ed elaborazioni del progetto restano distinti. Nessuna granularità o periodo viene inventato.</p><span>Ranking {overview.algorithmVersion}</span></footer>
  </div>;
}
