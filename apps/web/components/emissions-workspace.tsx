"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { EmissionsData, EmissionsNationalDataset, EmissionsNationalSeries, MapOption } from "../lib/data";
import { SoilMap } from "./soil-map";
import { TimelineControl } from "./timeline-control";

type ExplorerView = "national" | "provincial";
type NationalDatasetKind = "greenhouse" | "air";

function format(value: number, maximumFractionDigits = 1) {
  return value.toLocaleString("it-IT", { maximumFractionDigits });
}

function dimensionOptionLabel(series: Pick<EmissionsNationalSeries, "dimensionCode" | "dimensionLabel">) {
  const code = series.dimensionCode.trim();
  const label = series.dimensionLabel.trim();
  return label === code || label.startsWith(`${code} ·`) ? label : `${code} · ${label}`;
}

function SeriesChart({ series }: { series: EmissionsNationalSeries }) {
  const values = series.values.map(([, value]) => value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const points = series.values.map(([year, value], index) => `${12 + index / Math.max(1, series.values.length - 1) * 296},${88 - (value - min) / span * 68}`).join(" ");
  const first = series.values[0];
  const latest = series.values.at(-1);
  return <div className="emissions-series-result" aria-live="polite">
    <div className="emissions-series-value"><p className="eyebrow">Valore ufficiale più recente</p><strong>{format(latest?.[1] ?? 0)}</strong><span>{series.unit}</span><p>{series.dimensionLabel}</p></div>
    <figure className="emissions-trend"><figcaption><span>{first?.[0]}–{latest?.[0]} · {series.sourceUnit}</span><strong>{series.metricLabel}</strong></figcaption><svg viewBox="0 0 320 104" role="img" aria-label={`${series.metricLabel}, ${series.dimensionLabel}: ${format(first?.[1] ?? 0)} nel ${first?.[0]}, ${format(latest?.[1] ?? 0)} nel ${latest?.[0]} ${series.unit}`}><path d="M12 88H308" className="chart-axis" /><polyline points={points} className="emissions-chart-line" /><circle cx={points.split(" ").at(-1)?.split(",")[0]} cy={points.split(" ").at(-1)?.split(",")[1]} r="3.8" className="emissions-chart-dot" /></svg><div><span>{first?.[0]}</span><span>{latest?.[0]}</span></div></figure>
    <details><summary>Apri la tabella annuale ufficiale</summary><div className="table-scroll"><table><thead><tr><th>Anno</th><th>Valore</th></tr></thead><tbody>{series.values.map(([year, value]) => <tr key={year}><th scope="row">{year}</th><td>{format(value)} {series.unit}</td></tr>)}</tbody></table></div></details>
  </div>;
}

function NationalExplorer({ id, title, coverage, url, detail, defaultMetricId, defaultDimensionCode }: { id: string; title: string; coverage: string; url: string; detail: string; defaultMetricId: string; defaultDimensionCode: string }) {
  const [dataset, setDataset] = useState<EmissionsNationalDataset | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [metricId, setMetricId] = useState("");
  const [dimensionCode, setDimensionCode] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setDataset(null); setError(null); setMetricId(""); setDimensionCode("");
    fetch(url, { signal: controller.signal }).then((response) => response.ok ? response.json() as Promise<EmissionsNationalDataset> : Promise.reject(new Error(`Serie non disponibile (${response.status}).`))).then((next) => {
      if (controller.signal.aborted) return;
      const defaultSeries = next.series.find((item) => item.metricId === defaultMetricId && item.dimensionCode === defaultDimensionCode) ?? next.series[0];
      setDataset(next); setMetricId(defaultSeries?.metricId ?? ""); setDimensionCode(defaultSeries?.dimensionCode ?? "");
    }).catch((caught) => { if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : "Impossibile caricare le serie."); });
    return () => controller.abort();
  }, [defaultDimensionCode, defaultMetricId, url]);
  const metricOptions = useMemo(() => dataset ? [...new Map(dataset.series.map((item) => [item.metricId, item.metricLabel])).entries()].sort((left, right) => left[1].localeCompare(right[1], "it")) : [], [dataset]);
  const dimensions = useMemo(() => dataset?.series.filter((item) => item.metricId === metricId) ?? [], [dataset, metricId]);
  useEffect(() => { if (dimensions.length && !dimensions.some((item) => item.dimensionCode === dimensionCode)) setDimensionCode(dimensions[0].dimensionCode); }, [dimensionCode, dimensions]);
  const selected = dimensions.find((item) => item.dimensionCode === dimensionCode) ?? dimensions[0];
  const selectedDimensionLabel = selected ? dimensionOptionLabel(selected) : "";
  return <section id={id} className="emissions-explorer" aria-labelledby={`${id}-title`}>
    <header><div><p className="eyebrow">Dati ufficiali · Italia</p><h2 id={`${id}-title`}>{title}</h2></div><p><strong>{coverage}</strong>{detail}</p></header>
    {!dataset && !error && <p className="state-copy" role="status">Carico serie ufficiali…</p>}
    {error && <p className="state-copy" role="alert">Serie non disponibili. {error}</p>}
    {dataset && <div className="emissions-controls">
      <label>Inquinante o gas<select value={metricId} onChange={(event) => setMetricId(event.target.value)}>{metricOptions.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
      <label>Categoria o settore<select value={dimensionCode} onChange={(event) => setDimensionCode(event.target.value)} aria-describedby={`${id}-dimension-selection`} title={selectedDimensionLabel}>{dimensions.map((item) => <option value={item.dimensionCode} key={item.id}>{dimensionOptionLabel(item)}</option>)}</select><span id={`${id}-dimension-selection`} className="emissions-select-selection">Selezionata: {selectedDimensionLabel}</span></label>
    </div>}
    {selected && <SeriesChart series={selected} />}
  </section>;
}

export function EmissionsWorkspace({ data }: { data: EmissionsData }) {
  const { overview } = data;
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedTerritory = searchParams.get("territory") ?? undefined;
  const requestedPeriod = searchParams.get("period") ?? undefined;
  const latest = overview.greenhouseGases.series.at(-1);
  const [view, setView] = useState<ExplorerView>(() => searchParams.get("view") === "provincial" ? "provincial" : "national");
  const [nationalDataset, setNationalDataset] = useState<NationalDatasetKind>("greenhouse");
  const defaultCombination = data.provincial.find((item) => item.metricId === overview.map?.metricId && item.snapCode === overview.map?.snapCode) ?? data.provincial[0];
  const [combinationId, setCombinationId] = useState(defaultCombination?.id ?? "");
  const combination = data.provincial.find((item) => item.id === combinationId) ?? defaultCombination;
  const metricOptions = useMemo(() => [...new Map(data.provincial.map((item) => [item.metricId, item.pollutantLabel])).entries()].sort((left, right) => left[1].localeCompare(right[1], "it")), [data.provincial]);
  const [metricId, setMetricId] = useState(combination?.metricId ?? "");
  const [activityQuery, setActivityQuery] = useState("");
  const snapOptions = useMemo(() => data.provincial.filter((item) => item.metricId === metricId), [data.provincial, metricId]);
  const filteredSnapOptions = useMemo(() => {
    const query = activityQuery.trim().toLocaleLowerCase("it");
    return query ? snapOptions.filter((item) => `${item.snapCode} ${item.snapLabel}`.toLocaleLowerCase("it").includes(query)) : snapOptions;
  }, [activityQuery, snapOptions]);
  useEffect(() => { if (combination && combination.metricId !== metricId) setMetricId(combination.metricId); }, [combination, metricId]);
  useEffect(() => { if (snapOptions.length && !snapOptions.some((item) => item.id === combinationId)) setCombinationId(snapOptions[0].id); }, [combinationId, snapOptions]);
  const periods = Object.keys(combination?.mapPaths ?? {}).sort();
  const [period, setPeriod] = useState(() => requestedPeriod && periods.includes(requestedPeriod) ? requestedPeriod : periods.at(-1) ?? "");
  useEffect(() => { if (periods.length && !periods.includes(period)) setPeriod(periods.at(-1) ?? ""); }, [period, periods]);
  useEffect(() => { if (requestedPeriod && periods.includes(requestedPeriod) && requestedPeriod !== period) setPeriod(requestedPeriod); }, [period, periods, requestedPeriod]);
  const maps: MapOption[] = periods.map((year) => ({ logicalPath: combination?.mapPaths[year] ?? "", url: `${combination?.mapPaths[year] ?? ""}#${combination?.snapCode ?? ""}`, metricId: combination?.metricId ?? "", periodKey: year, level: "province" }));
  const map = maps.find((item) => item.periodKey === period) ?? maps.at(-1);
  const [territory, setTerritory] = useState<{ id: string; name?: string } | undefined>(() => requestedTerritory ? { id: requestedTerritory } : undefined);

  useEffect(() => {
    setTerritory((current) => requestedTerritory ? current?.id === requestedTerritory ? current : { id: requestedTerritory } : undefined);
  }, [requestedTerritory]);

  const updateQuery = useCallback((params: Record<string, string | undefined>) => {
    const next = new URLSearchParams(searchParams.toString());
    Object.entries(params).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key));
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  }, [pathname, router, searchParams]);

  const selectTerritory = useCallback((id: string, name?: string) => {
    setTerritory({ id, name });
    updateQuery({ territory: id, view: "provincial" });
  }, [updateQuery]);
  const chooseMetric = (nextMetric: string) => { setMetricId(nextMetric); setCombinationId(data.provincial.find((item) => item.metricId === nextMetric)?.id ?? ""); setActivityQuery(""); };
  const selectView = (next: ExplorerView) => { setView(next); updateQuery({ view: next }); window.setTimeout(() => document.getElementById(next === "national" ? "nazionali" : "mappa")?.focus(), 0); };

  return <section className="domain-site-layout explorer-layout domain-emissions" aria-label="Atlante emissioni">
    <div className="domain-site-content">
      <header className="workspace-header emissions-workspace-header"><div><p className="eyebrow">ISPRA · inventari ufficiali</p><h1>Emissioni</h1></div><p>Serie nazionale e distribuzione provinciale descrivono scale diverse. Non vengono sommate né trasformate in qualità dell&apos;aria.</p><div className="emissions-latest"><p className="eyebrow">Italia · {latest?.[0]}</p><strong>{format(latest?.[1] ?? 0, 0)}</strong><span>{overview.greenhouseGases.unit}</span><small>Totale emissioni nette ufficiale.</small></div></header>
      <section className="emissions-choice" aria-labelledby="emissions-choice-title"><div><p className="eyebrow">Vista</p><h2 id="emissions-choice-title">Scegli scala di lettura</h2></div><div className="emissions-choice-actions"><button type="button" className={view === "national" ? "is-active" : undefined} onClick={() => selectView("national")}><strong>Italia nel tempo</strong><span>Gas serra e inquinanti NFR, 1990–2024.</span></button><button type="button" className={view === "provincial" ? "is-active" : undefined} onClick={() => selectView("provincial")}><strong>Province per attività</strong><span>Una combinazione inquinante + SNAP, 2019 o 2023.</span></button></div></section>
      {view === "national" ? <section id="nazionali" className="emissions-reading-surface" tabIndex={-1} aria-labelledby="national-title"><header><p className="eyebrow">Serie nazionali</p><h2 id="national-title">Italia nel tempo</h2><p>Seleziona inventario, gas o inquinante e categoria. Dati NFR non sommati dalla pagina.</p></header><div className="emissions-data-tabs" role="tablist" aria-label="Inventario nazionale"><button type="button" role="tab" aria-selected={nationalDataset === "greenhouse"} className={nationalDataset === "greenhouse" ? "is-active" : undefined} onClick={() => setNationalDataset("greenhouse")}>Gas serra<span>CO2 equivalente, CO2, CH4, N2O, F-gas</span></button><button type="button" role="tab" aria-selected={nationalDataset === "air"} className={nationalDataset === "air" ? "is-active" : undefined} onClick={() => setNationalDataset("air")}>Inquinanti NFR<span>26 inquinanti, per settore NFR</span></button></div>{nationalDataset === "greenhouse" ? <NationalExplorer key="greenhouse" id="serra" title={overview.greenhouseGases.label} coverage={overview.greenhouseGases.coverage} url={data.nationalUrls.greenhouseGases} detail="Il primo valore è il totale netto in CO2 equivalente, incluse le categorie LULUCF indicate dalla fonte." defaultMetricId="emissions_ghg_co2e" defaultDimensionCode="Total (net emissions) (4)" /> : <NationalExplorer key="air" id="inquinanti" title={overview.airPollutantsNfr.label} coverage={overview.airPollutantsNfr.coverage} url={data.nationalUrls.airPollutantsNfr} detail="Ogni serie rappresenta una sola combinazione inquinante + settore NFR; la UI non produce totali." defaultMetricId="emissions_air_nox_as_no2" defaultDimensionCode="1A3bi" />}</section> : <section id="mappa" className="emissions-map-surface map-workspace-v2" tabIndex={-1} aria-labelledby="map-explorer-title"><header><p className="eyebrow">Disaggregazione provinciale</p><h2 id="map-explorer-title">Province per attività SNAP</h2><p>Singolo inquinante e singola attività. Non è totale provinciale, dato comunale o qualità dell&apos;aria.</p></header><div className="emissions-map-controls"><label>1. Inquinante<select value={metricId} onChange={(event) => chooseMetric(event.target.value)}>{metricOptions.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label><label>2. Cerca attività SNAP<input type="search" value={activityQuery} onChange={(event) => setActivityQuery(event.target.value)} placeholder="es. automobili, caldaie, agricoltura" aria-describedby="snap-results" /></label><label>3. Attività<select value={combination?.id ?? ""} onChange={(event) => setCombinationId(event.target.value)} disabled={!filteredSnapOptions.length}>{filteredSnapOptions.map((item) => <option value={item.id} key={item.id}>{item.snapCode} · {item.snapLabel}</option>)}</select><span id="snap-results">{filteredSnapOptions.length} attività disponibili per {combination?.pollutantLabel ?? "questo inquinante"}.</span></label></div>{map && <TimelineControl periods={periods} value={map.periodKey} onChange={(nextPeriod) => { setPeriod(nextPeriod); updateQuery({ period: nextPeriod }); }} />}{map && combination ? <><SoilMap option={map} metricLabel={`${combination.pollutantLabel} · ${combination.snapLabel}`} geometryUrl={data.geometryByPeriod[map.periodKey]} colorRamp="emissions" selectedTerritoryId={territory?.id} seriesOptions={maps} onTerritorySelect={selectTerritory} /><div className="map-reading-panel"><p><strong>Stai leggendo:</strong> {combination.pollutantLabel} da {combination.snapLabel} · ISPRA · {combination.pollutantCode} · SNAP {combination.snapCode}.</p></div></> : <p role="status">Mappa provinciale in preparazione nella release attiva.</p>}</section>}
      <section id="metodo" className="emissions-method"><p className="eyebrow">Fonte e limiti</p><div><p>Inventari nazionali e disaggregazione provinciale sono dataset diversi. Le attività SNAP non vengono sommate. ISPRA pubblica snapshot provinciali anche precedenti, ma la mappa espone solo 2019 e 2023: sono gli anni con confini ISTAT storici equivalenti già archiviati.</p><p>Nessuna interpolazione, conversione comunale o interpretazione come qualità dell&apos;aria.</p></div></section>
    </div>
  </section>;
}
