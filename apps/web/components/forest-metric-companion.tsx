"use client";

import { useEffect, useMemo, useState } from "react";
import type { MapOption } from "../lib/data";

export type ForestMetricCompanionConfig = {
  id: "composition" | "distribution" | "change";
  metricIds: string[];
  title: string;
  description: string;
};

type MapDataset = { values: [string, number][]; unit: string };
type LoadState = { status: "idle" | "loading" | "ready" | "error"; datasets: Record<string, MapDataset>; error?: string };

function formatNumber(value: number, unit: string) {
  return `${value.toLocaleString("it-IT", { maximumFractionDigits: 1 })} ${unit}`;
}

async function fetchDataset(option: MapOption, signal: AbortSignal): Promise<MapDataset> {
  const [mapUrl, snapshotCode] = option.url.split("#", 2);
  const response = await fetch(mapUrl, { signal });
  if (!response.ok) throw new Error(`Valori non disponibili (${response.status}).`);
  const raw = await response.json() as MapDataset & { snapshots?: Array<{ sourceDimensions: { snap_code: string }; unit: string; values: [string, number][] }> };
  const snapshot = raw.snapshots?.find((item) => item.sourceDimensions.snap_code === snapshotCode);
  return snapshot ? { unit: snapshot.unit, values: snapshot.values } : raw;
}

function MetricBars({ rows }: { rows: Array<{ label: string; value: number; unit: string }> }) {
  const maximum = Math.max(...rows.map((row) => row.value), 0);
  return <dl className="forest-comparison-bars">{rows.map((row) => <div key={row.label}><dt>{row.label}</dt><dd>{formatNumber(row.value, row.unit)}</dd><div className="forest-comparison-bar" aria-hidden="true"><span style={{ width: `${maximum ? (row.value / maximum) * 100 : 0}%` }} /></div></div>)}</dl>;
}

function Distribution({ datasets, territoryId }: { datasets: Record<string, MapDataset>; territoryId: string }) {
  const mean = datasets.tree_cover_mean;
  const p25 = datasets.tree_cover_p25;
  const p50 = datasets.tree_cover_p50;
  const p75 = datasets.tree_cover_p75;
  if (!mean || !p25 || !p50 || !p75) return null;
  const values = [mean, p25, p50, p75].map((dataset) => dataset.values.find(([candidate]) => candidate === territoryId)?.[1]);
  if (values.some((value) => !Number.isFinite(value))) return null;
  const [meanValue, p25Value, p50Value, p75Value] = values as number[];
  const unit = mean.unit;
  return <><div className="forest-distribution" aria-label={`Copertura tra ${formatNumber(p25Value, unit)} e ${formatNumber(p75Value, unit)}; mediana ${formatNumber(p50Value, unit)}`}><p><strong>Fascia centrale</strong><span>Metà dei pixel del territorio è compresa qui.</span></p><div className="forest-distribution-scale"><span>0%</span><div aria-hidden="true"><i style={{ left: `${p25Value}%`, width: `${Math.max(p75Value - p25Value, 0)}%` }} /><b style={{ left: `${p50Value}%` }} /></div><span>100%</span></div></div><dl className="forest-stat-list"><div><dt>Copertura media</dt><dd>{formatNumber(meanValue, unit)}</dd></div><div><dt>25° percentile</dt><dd>{formatNumber(p25Value, unit)}</dd></div><div><dt>Mediana</dt><dd>{formatNumber(p50Value, unit)}</dd></div><div><dt>75° percentile</dt><dd>{formatNumber(p75Value, unit)}</dd></div></dl></>;
}

export function ForestMetricCompanion({ activeMetricId, selectedOption, selectedTerritoryId, selectedTerritoryName, maps, metricLabels, companions }: { activeMetricId: string; selectedOption: MapOption; selectedTerritoryId?: string; selectedTerritoryName?: string; maps: MapOption[]; metricLabels: Record<string, string>; companions: ForestMetricCompanionConfig[] }) {
  const companion = companions.find((item) => item.metricIds.includes(activeMetricId));
  const options = useMemo(() => companion ? companion.metricIds.map((metricId) => maps.find((item) => item.metricId === metricId && item.level === selectedOption.level && item.periodKey === selectedOption.periodKey)).filter((item): item is MapOption => Boolean(item)) : [], [companion, maps, selectedOption.level, selectedOption.periodKey]);
  const [state, setState] = useState<LoadState>({ status: "idle", datasets: {} });

  useEffect(() => {
    const controller = new AbortController();
    if (!companion || !selectedTerritoryId || options.length !== companion.metricIds.length) {
      setState({ status: "idle", datasets: {} });
      return () => controller.abort();
    }
    setState({ status: "loading", datasets: {} });
    Promise.all(options.map(async (option) => [option.metricId, await fetchDataset(option, controller.signal)] as const))
      .then((items) => { if (!controller.signal.aborted) setState({ status: "ready", datasets: Object.fromEntries(items) }); })
      .catch((caught) => { if (!controller.signal.aborted) setState({ status: "error", datasets: {}, error: caught instanceof Error ? caught.message : "Impossibile caricare il confronto." }); });
    return () => controller.abort();
  }, [companion, options, selectedTerritoryId]);

  if (!companion) return null;
  const territoryName = selectedTerritoryName ?? "il territorio selezionato";
  const rows = companion.metricIds.flatMap((metricId) => {
    const dataset = state.datasets[metricId];
    const value = dataset?.values.find(([territoryId]) => territoryId === selectedTerritoryId)?.[1];
    return dataset && typeof value === "number" && Number.isFinite(value) ? [{ label: metricLabels[metricId] ?? metricId, value, unit: dataset.unit }] : [];
  });

  return <section className="forest-companion" aria-live="polite"><header><div><p className="eyebrow">Leggi insieme</p><h2>{companion.title}</h2></div><p>{companion.description}</p></header>{!selectedTerritoryId ? <p className="forest-companion-state">Seleziona un territorio nella mappa per confrontare queste misure.</p> : state.status === "loading" ? <p className="forest-companion-state" role="status">Carico il confronto per {territoryName}…</p> : state.status === "error" ? <p className="forest-companion-state" role="alert">Confronto non disponibile. {state.error}</p> : rows.length !== companion.metricIds.length ? <p className="forest-companion-state">Non tutte le misure sono disponibili per {territoryName} in questo periodo.</p> : companion.id === "distribution" ? <Distribution datasets={state.datasets} territoryId={selectedTerritoryId} /> : <MetricBars rows={rows} />}</section>;
}
