type Observation = { metricId: string; periodStart: string; periodEnd: string; value: number; unit: string };
type Profile = {
  territory: { name: string; level: string; istatCode: string; referenceDate: string; parents: Array<{ name: string; level: string }> };
  latestObservations: Observation[];
  historicalSeries: Array<{ metricId: string; columns: string[]; values: Array<[string, string, string, number, string]> }>;
  derivedMetrics: Array<Record<string, unknown>>;
  comparisons: Record<string, Array<{ scope: string; status: string; territoryId?: string; observation?: Observation }>>;
};

const labels: Record<string, string> = {
  soil_net_consumption_hectares: "Incremento netto di suolo consumato",
  soil_gross_consumption_hectares: "Incremento lordo di suolo consumato",
  soil_restoration_hectares: "Ripristino di suolo",
  soil_consumed_hectares: "Suolo consumato",
  soil_consumed_share: "Suolo consumato",
};

export function TerritoryProfile({ profile }: { profile: Profile }) {
  const net = profile.latestObservations.find((item) => item.metricId === "soil_net_consumption_hectares");
  const netSeries = profile.historicalSeries.find((item) => item.metricId === "soil_net_consumption_hectares");
  const netAnalytics = profile.derivedMetrics.find((item) => item.metricId === "soil_net_consumption_hectares") as { changes?: Record<string, { value?: number; status?: string }>; trend?: Record<string, unknown>; benchmarks?: Record<string, Record<string, unknown>> } | undefined;
  return <>
    <section className="profile-head"><p className="eyebrow">{profile.territory.level} · ISTAT {profile.territory.istatCode}</p><h1>{profile.territory.name}</h1><p>{profile.territory.parents.map((parent) => `${parent.name} (${parent.level})`).join(" · ")}</p><p className="muted">Riferimento territoriale: {profile.territory.referenceDate}</p></section>
    {net && <section className="key-value"><p>Ultimo incremento netto disponibile</p><strong>{net.value.toLocaleString("it-IT")} {net.unit}</strong><span>{net.periodStart.slice(0, 4)}–{net.periodEnd.slice(0, 4)} · dato ufficiale ISPRA/SNPA</span></section>}
    <section className="profile-grid"><div><h2>Variazioni e trend</h2>{netAnalytics ? <dl>
      <dt>Vs periodo precedente</dt><dd>{netAnalytics.changes?.previous?.status === "available" ? `${netAnalytics.changes.previous.value?.toLocaleString("it-IT")} ha` : "Non disponibile"}</dd>
      <dt>Vs 5 anni</dt><dd>{netAnalytics.changes?.fiveYears?.status === "available" ? `${netAnalytics.changes.fiveYears.value?.toLocaleString("it-IT")} ha` : "Non disponibile"}</dd>
      <dt>Vs 10 anni</dt><dd>{netAnalytics.changes?.tenYears?.status === "available" ? `${netAnalytics.changes.tenYears.value?.toLocaleString("it-IT")} ha` : "Non disponibile: manca flusso annuale 2014"}</dd>
      <dt>Trend OLS</dt><dd>{String(netAnalytics.trend?.direction ?? "Non disponibile")} · slope {Number(netAnalytics.trend?.slope_per_year ?? 0).toLocaleString("it-IT")} ha/anno</dd>
      <dt>Percentile nazionale</dt><dd>{Number(netAnalytics.benchmarks?.national?.percentile ?? 0).toFixed(1)}</dd>
      <dt>Ranking nazionale</dt><dd>{String(netAnalytics.benchmarks?.national?.rank ?? "—")}</dd>
    </dl> : <p>Analytics non disponibile.</p>}</div><div><h2>Confronto stesso periodo</h2>{(profile.comparisons.soil_net_consumption_hectares ?? []).map((item) => <p key={item.scope}><strong>{item.scope}</strong>: {item.status === "available" ? `${item.observation?.value.toLocaleString("it-IT")} ${item.observation?.unit}` : "non disponibile"}</p>)}</div></section>
    <section className="history"><h2>Storico ufficiale</h2>{netSeries ? <table><thead><tr><th>Periodo</th><th>Valore</th><th>Unità</th></tr></thead><tbody>{netSeries.values.map(([id, start, end, value, unit]) => <tr key={id}><th scope="row">{start.slice(0, 4)}–{end.slice(0, 4)}</th><td>{value.toLocaleString("it-IT")}</td><td>{unit}</td></tr>)}</tbody></table> : <p>Nessun dato.</p>}</section>
    <section className="history"><h2>Altri indicatori ufficiali</h2><table><thead><tr><th>Indicatore</th><th>Periodo</th><th>Valore</th></tr></thead><tbody>{profile.latestObservations.map((item) => <tr key={item.metricId}><th scope="row">{labels[item.metricId] ?? item.metricId}</th><td>{item.periodStart.slice(0, 4)}–{item.periodEnd.slice(0, 4)}</td><td>{item.value.toLocaleString("it-IT")} {item.unit}</td></tr>)}</tbody></table></section>
  </>;
}
