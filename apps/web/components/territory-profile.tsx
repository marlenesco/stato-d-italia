import Link from "next/link";
import type { Observation, TerritoryDomainInsight, TerritoryProfileData } from "../lib/data";
import { PageSidebar } from "./page-sidebar";

const labels: Record<string, string> = {
  soil_net_consumption_hectares: "Incremento netto di suolo consumato",
  soil_gross_consumption_hectares: "Incremento lordo di suolo consumato",
  soil_restoration_hectares: "Ripristino di suolo",
  soil_consumed_hectares: "Suolo consumato",
  soil_consumed_share: "Suolo consumato",
};

const levelLabels: Record<string, string> = { municipality: "Comune", province: "Provincia", region: "Regione", country: "Italia" };
type Analytics = { changes?: Record<string, { value?: number | null; status?: string | null; reason?: string | null }>; trend?: { status?: string | null; direction?: string | null; slope_per_year?: number | null; reason?: string | null }; benchmarks?: Record<string, { percentile?: number | null; percentileStatus?: string | null; rank?: number | null; rankStatus?: string | null }> };

function period(start: string, end: string) {
  const from = start.slice(0, 4);
  const to = end.slice(0, 4);
  return from === to ? from : `${from}–${to}`;
}

function value(observation: Observation) {
  return `${observation.value.toLocaleString("it-IT", { maximumFractionDigits: 1 })} ${observation.unit}`;
}

function availability(change?: { value?: number | null; status?: string | null; reason?: string | null }) {
  if (change?.status === "available" && change.value !== undefined && change.value !== null) return `${change.value > 0 ? "+" : ""}${change.value.toLocaleString("it-IT", { maximumFractionDigits: 1 })} ha`;
  if (change?.reason === "missing_required_period") return "Non disponibile: manca il periodo necessario per il confronto";
  return "Non disponibile";
}

function trendLabel(direction?: string | null) {
  if (direction === "increasing") return "in aumento";
  if (direction === "decreasing") return "in diminuzione";
  if (direction === "flat") return "stabile";
  return "non stimabile";
}

function isAvailable(domain: TerritoryDomainInsight): domain is Extract<TerritoryDomainInsight, { availability: "available" }> {
  return domain.availability === "available";
}

function insightPeriod(start: string, end: string) {
  return start.slice(0, 4) === end.slice(0, 4) ? start.slice(0, 4) : `${start.slice(0, 4)}–${end.slice(0, 4)}`;
}

function insightStatus(domain: TerritoryDomainInsight) {
  if (!isAvailable(domain) || domain.comparison.status !== "available") return "Trend non disponibile";
  if (domain.comparison.direction === "improving") return "Pressione in diminuzione";
  if (domain.comparison.direction === "worsening") return "Pressione in aumento";
  if (domain.comparison.direction === "changed") return "Variazione osservata";
  return "Stabile";
}

function InsightChart({ domain }: { domain: TerritoryDomainInsight }) {
  if (!isAvailable(domain) || domain.series.length < 2) return <p className="territory-domain-chart-empty">Snapshot: nessuna serie comparabile.</p>;
  const values = domain.series.map((point) => point.value);
  const minimum = Math.min(...values);
  const span = Math.max(...values) - minimum || 1;
  const points = domain.series.map((point, index) => `${8 + index / Math.max(1, domain.series.length - 1) * 152},${58 - (point.value - minimum) / span * 46}`).join(" ");
  return <figure className="territory-domain-chart"><svg viewBox="0 0 168 66" role="img" aria-label={`Andamento disponibile: ${domain.series.map((point) => `${insightPeriod(point.periodStart, point.periodEnd)} ${point.value.toLocaleString("it-IT", { maximumFractionDigits: 1 })} ${point.unit}`).join(", ")}`}><path d="M8 58H160" className="chart-axis" /><polyline points={points} /><circle cx={points.split(" ").at(-1)?.split(",")[0]} cy={points.split(" ").at(-1)?.split(",")[1]} r="3.5" /></svg><figcaption><span>{insightPeriod(domain.series[0].periodStart, domain.series[0].periodEnd)}</span><span>{insightPeriod(domain.latest.periodStart, domain.latest.periodEnd)}</span></figcaption></figure>;
}

export function TerritoryProfile({ profile, insights }: { profile: TerritoryProfileData; insights: TerritoryDomainInsight[] }) {
  const net = profile.latestObservations.find((item) => item.metricId === "soil_net_consumption_hectares");
  const netSeries = profile.historicalSeries.find((item) => item.metricId === "soil_net_consumption_hectares");
  const analytics = profile.derivedMetrics.find((item) => item.metricId === "soil_net_consumption_hectares") as Analytics | undefined;
  const parents = profile.territory.parents.map((parent) => parent.name).join(" · ");
  const national = analytics?.benchmarks?.national;

  return <section className="territory-site-layout">
    <PageSidebar eyebrow={levelLabels[profile.territory.level] ?? profile.territory.level} title={profile.territory.name}>
      <nav className="page-sidebar-nav" aria-label="Sezioni profilo"><a href="#domini">Domini</a><a href="#indicatore">Approfondimento Suolo</a><a href="#storico">Storico Suolo</a><a href="#osservazioni">Osservazioni Suolo</a><Link href="/suolo#mappa">Torna alla mappa →</Link></nav>
      {parents && <section className="sidebar-section"><h3>Contesto</h3><p className="sidebar-context"><strong>{parents}</strong>Confini: {profile.territory.referenceDate}.</p></section>}
    </PageSidebar>
    <div className="territory-site-content">
    <section className="profile-head">
      <p className="eyebrow">{levelLabels[profile.territory.level] ?? profile.territory.level} · ISTAT {profile.territory.istatCode}</p>
      <h1>{profile.territory.name}</h1>
      {parents && <p className="profile-parent">{parents}</p>}
      <p className="muted">Confini di riferimento: {profile.territory.referenceDate}</p>
    </section>

    <section id="domini" className="territory-domain-summary" tabIndex={-1} aria-labelledby="territory-domains-title">
      <header><div><p className="eyebrow">Quadro del territorio</p><h2 id="territory-domains-title">Dati disponibili per questa zona</h2></div><p>Stessa entità territoriale. Nessuna somma, conversione di scala o dato assente trasformato in zero.</p></header>
      <div className="territory-domain-list">{insights.map((domain) => isAvailable(domain) ? <Link key={domain.id} href={domain.href} className={`territory-domain-signal territory-domain-signal--${domain.id}`}><header><span>{domain.title}</span><b>{insightStatus(domain)}</b></header><strong>{domain.latest.value.toLocaleString("it-IT", { maximumFractionDigits: 1 })} <small>{domain.latest.unit}</small></strong><p>{domain.label}</p><InsightChart domain={domain} /><small>{insightPeriod(domain.latest.periodStart, domain.latest.periodEnd)} · {domain.source}</small><em>{domain.comparison.status === "available" && domain.comparison.delta !== undefined ? `${domain.comparison.delta > 0 ? "+" : ""}${domain.comparison.delta.toLocaleString("it-IT", { maximumFractionDigits: 1 })} ${domain.latest.unit}${domain.comparison.percent !== undefined ? ` (${domain.comparison.percent > 0 ? "+" : ""}${domain.comparison.percent.toLocaleString("it-IT", { maximumFractionDigits: 1 })}%)` : ""} rispetto al rilievo precedente` : "Nessun confronto automatico"}</em><b className="territory-domain-open">Apri dominio <span aria-hidden="true">→</span></b></Link> : <article key={domain.id} className={`territory-domain-signal territory-domain-signal--${domain.id} is-unavailable`}><header><span>{domain.title}</span></header><h3>Dato non pubblicato</h3><p>{domain.reason === "source_not_published_at_this_level" ? "La fonte non pubblica questo dominio a questa scala." : "Nessun dato per questa zona nella copertura pubblicata."}</p></article>)}</div>
    </section>

    {net ? <section id="indicatore" className="profile-lead" aria-label="Approfondimento Suolo" tabIndex={-1}><div><p className="eyebrow">Approfondimento Suolo · dato ufficiale ISPRA / SNPA</p><h2>Ultimo incremento netto disponibile</h2><strong>{value(net)}</strong><span>{period(net.periodStart, net.periodEnd)}</span></div><p>È un valore osservato. Cause, responsabilità e valutazioni richiedono contesto ulteriore.</p></section> : <section id="indicatore" className="profile-lead" tabIndex={-1}><p className="eyebrow">Approfondimento Suolo · dato ufficiale</p><h2>Incremento netto non pubblicato per questo territorio</h2></section>}

    <section className="profile-grid">
      <div className="profile-card"><p className="eyebrow">Lettura della serie</p><h2>Variazioni e trend</h2>{analytics ? <dl>
        <dt>Rispetto al periodo precedente</dt><dd>{availability(analytics.changes?.previous)}</dd>
        <dt>Rispetto a 5 anni</dt><dd>{availability(analytics.changes?.fiveYears)}</dd>
        <dt>Rispetto a 10 anni</dt><dd>{availability(analytics.changes?.tenYears)}</dd>
        <dt>Trend stimato</dt><dd>{trendLabel(analytics.trend?.direction)}{analytics.trend?.status === "available" && analytics.trend.slope_per_year !== undefined && analytics.trend.slope_per_year !== null ? ` · ${analytics.trend.slope_per_year.toLocaleString("it-IT", { maximumFractionDigits: 1 })} ha/anno` : ""}</dd>
      </dl> : <p className="state-copy">Elaborazioni non pubblicate per questo profilo.</p>}</div>
      <div className="profile-card"><p className="eyebrow">Confronto nazionale</p><h2>Posizione nel periodo</h2>{national?.rankStatus === "available" || national?.percentileStatus === "available" ? <dl>
        <dt>Posizione</dt><dd>{national.rankStatus === "available" ? national.rank ?? "—" : "Non disponibile"}</dd>
        <dt>Percentile</dt><dd>{national.percentileStatus === "available" && national.percentile !== undefined && national.percentile !== null ? national.percentile.toLocaleString("it-IT", { maximumFractionDigits: 1 }) : "Non disponibile"}</dd>
      </dl> : <p className="state-copy">Confronto non pubblicato per questo territorio o livello.</p>}<p className="card-note">Posizione e percentile confrontano solo territori nello stesso livello e periodo.</p></div>
    </section>

    <section id="storico" className="history" tabIndex={-1}><div className="section-heading"><div><p className="eyebrow">Serie ufficiale</p><h2>Storico dell’incremento netto</h2></div><p>Ogni riga è un periodo pubblicato; non vengono stimati anni mancanti.</p></div>{netSeries ? <div className="table-scroll"><table><thead><tr><th>Periodo</th><th>Valore</th><th>Unità</th></tr></thead><tbody>{netSeries.values.map(([id, start, end, amount, unit]) => <tr key={id}><th scope="row">{period(start, end)}</th><td>{amount.toLocaleString("it-IT", { maximumFractionDigits: 1 })}</td><td>{unit}</td></tr>)}</tbody></table></div> : <p className="state-copy">Nessuna serie ufficiale pubblicata.</p>}</section>

    <section id="osservazioni" className="history" tabIndex={-1}><div className="section-heading"><div><p className="eyebrow">Ultime osservazioni</p><h2>Altri indicatori ufficiali</h2></div></div><div className="table-scroll"><table><thead><tr><th>Indicatore</th><th>Periodo</th><th>Valore</th></tr></thead><tbody>{profile.latestObservations.map((item) => <tr key={item.metricId}><th scope="row">{labels[item.metricId] ?? item.metricId}</th><td>{period(item.periodStart, item.periodEnd)}</td><td>{value(item)}</td></tr>)}</tbody></table></div></section>
    </div>
  </section>;
}
