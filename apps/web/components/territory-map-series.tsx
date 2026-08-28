"use client";

import { useEffect, useMemo, useState } from "react";
import type { MapOption } from "../lib/data";
import { territoryLabel } from "../lib/territory-labels";

type MapDataset = { values: [string, number][]; unit: string; periodStart: string; periodEnd: string };
type Point = { period: string; periodStart: string; periodEnd: string; value: number; unit: string };
type TrendGeometry = { paths: string[]; points: Array<{ x: number; y: number } | null> };
type Comparison = { change: number; percent: number };
const TEMPORAL_COMPARISON_UI_VERSION = "temporal-comparison-ui-v1";

function format(value: number, unit: string) {
  return `${value.toLocaleString("it-IT", { maximumFractionDigits: 1 })} ${unit}`;
}

function periodDurationYears(point: Point) {
  return Number(point.periodEnd.slice(0, 4)) - Number(point.periodStart.slice(0, 4));
}

function comparison(previous: Point, current: Point): Comparison | null {
  if (previous.unit !== current.unit || periodDurationYears(previous) !== periodDurationYears(current) || previous.value === 0) return null;
  const change = current.value - previous.value;
  return { change, percent: change / Math.abs(previous.value) * 100 };
}

function DeltaGauge({ result }: { result: Comparison | null }) {
  const direction = result ? result.change > 0 ? "up" : result.change < 0 ? "down" : "flat" : "empty";
  const progress = result ? Math.max(2, Math.min(Math.abs(result.percent), 100)) : 0;
  const value = result ? `${result.percent > 0 ? "+" : ""}${result.percent.toLocaleString("it-IT", { maximumFractionDigits: 1 })}%` : "—";
  const label = result ? `${value} rispetto al periodo precedente` : "Confronto con periodo precedente non disponibile";
  return <div className={`territory-delta-gauge territory-delta-gauge--${direction}`} aria-label={label}><svg viewBox="0 0 112 74" role="img" aria-label={label}><path className="territory-delta-gauge-track" d="M16 58A40 40 0 0 1 96 58" pathLength="100" /><path className="territory-delta-gauge-progress" d="M16 58A40 40 0 0 1 96 58" pathLength="100" style={{ strokeDasharray: `${progress} 100` }} /><text x="56" y="54" textAnchor="middle">{value}</text></svg></div>;
}

function trendGeometry(samples: Array<Point | null>): TrendGeometry {
  const values = samples.flatMap((sample) => sample ? [sample.value] : []);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pointAt = (sample: Point | null, index: number) => sample ? { x: 12 + index / Math.max(1, samples.length - 1) * 256, y: 72 - (sample.value - min) / span * 56 } : null;
  const points = samples.map(pointAt);
  const paths: string[] = [];
  let segment: string[] = [];
  points.forEach((point) => {
    if (point) segment.push(`${point.x},${point.y}`);
    else if (segment.length) { paths.push(segment.join(" ")); segment = []; }
  });
  if (segment.length) paths.push(segment.join(" "));
  return { paths, points };
}

export function TerritoryMapSeries({ options, territoryId, territoryName, selectedPeriod, statusNote = "Valori ufficiali; nessuna interpolazione." }: { options: MapOption[]; territoryId?: string; territoryName?: string; selectedPeriod?: string; statusNote?: string }) {
  const [samples, setSamples] = useState<Array<Point | null> | null>(null);
  const requestKey = useMemo(() => options.map((option) => `${option.periodKey}:${option.url}`).join("|"), [options]);

  useEffect(() => {
    if (!territoryId || !options.length) {
      setSamples(null);
      return;
    }
    const controller = new AbortController();
    setSamples(null);
    async function load() {
      const next = await Promise.all(options.map(async (option) => {
        const [url, snapshotCode] = option.url.split("#", 2);
        const response = await fetch(url, { signal: controller.signal });
        if (!response.ok) throw new Error(`Serie non disponibile (${response.status}).`);
        const raw = await response.json() as MapDataset & { snapshots?: Array<{ sourceDimensions: { snap_code: string }; unit: string; values: [string, number][] }> };
        const snapshot = raw.snapshots?.find((item) => item.sourceDimensions.snap_code === snapshotCode);
        const dataset = snapshot ? { ...raw, unit: snapshot.unit, values: snapshot.values } : raw;
        const value = dataset.values.find(([id]) => id === territoryId)?.[1];
        return typeof value === "number" ? { period: option.periodKey, periodStart: dataset.periodStart, periodEnd: dataset.periodEnd, value, unit: dataset.unit } : null;
      }));
      if (!controller.signal.aborted) setSamples(next);
    }
    void load().catch(() => { if (!controller.signal.aborted) setSamples([]); });
    return () => controller.abort();
  }, [options, requestKey, territoryId]);

  if (!territoryId) return null;
  const label = territoryLabel(territoryId, territoryName);
  if (samples === null) return <section className="territory-series territory-series--drawer" aria-live="polite"><h3>Andamento</h3><p className="sidebar-context">Carico serie di {label}…</p></section>;

  const selectedIndex = selectedPeriod ? options.findIndex((option) => option.periodKey === selectedPeriod) : samples.length - 1;
  const current = selectedIndex >= 0 ? samples[selectedIndex] : null;
  const previous = selectedIndex >= 0 ? samples.slice(0, selectedIndex).filter((sample): sample is Point => sample !== null).at(-1) : undefined;
  const geometry = samples.some(Boolean) ? trendGeometry(samples) : null;
  const result = current && previous ? comparison(previous, current) : null;
  const direction = result ? result.change > 0 ? "Aumento" : result.change < 0 ? "Diminuzione" : "Invariato" : "Non comparabile";

  return <section className="territory-series territory-series--drawer" aria-live="polite">
    <h3>Andamento nel periodo disponibile</h3>
    {geometry && <figure className="territory-trend"><svg viewBox="0 0 280 88" role="img" aria-label={`Trend pubblicato di ${label}`}><path d="M12 72H268" className="chart-axis" />{geometry.paths.map((path, index) => <polyline key={index} points={path} className="territory-trend-line" />)}{geometry.points.map((point, index) => point && <circle key={index} cx={point.x} cy={point.y} r={index === selectedIndex ? 4.6 : 2.2} className={index === selectedIndex ? "territory-trend-point territory-trend-point--selected" : "territory-trend-point"} />)}</svg><figcaption><span>{options[0]?.periodKey}</span><span>{selectedPeriod ?? options.at(-1)?.periodKey}</span></figcaption></figure>}
    {!current ? <p className="sidebar-context"><strong>{label}</strong> Dato non pubblicato per periodo selezionato. Territorio resta selezionato.</p> : <><dl className="territory-summary"><div><dt>Selezionato</dt><dd>{format(current.value, current.unit)}</dd></div><div><dt>Confronto precedente</dt><dd><DeltaGauge result={result} /></dd></div></dl><p className="sidebar-context"><strong>{direction}.</strong> {result ? `${result.change > 0 ? "+" : ""}${format(result.change, current.unit)} rispetto a ${previous?.period}.` : previous ? "Periodi non comparabili." : "Manca periodo precedente pubblicato."}</p><small className="territory-series-note">{statusNote} {result && `${TEMPORAL_COMPARISON_UI_VERSION}: valore ${current.period} − valore ${previous?.period}.`}</small></>}
  </section>;
}
