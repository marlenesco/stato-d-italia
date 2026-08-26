"use client";

import { useEffect, useMemo, useState } from "react";
import type { MapOption } from "../lib/data";
import { territoryLabel } from "../lib/territory-labels";

type MapDataset = { values: [string, number][]; unit: string; periodStart: string; periodEnd: string };
type Point = { period: string; periodStart: string; periodEnd: string; value: number; unit: string };
const TEMPORAL_COMPARISON_UI_VERSION = "temporal-comparison-ui-v1";

function format(value: number, unit: string) {
  return `${value.toLocaleString("it-IT", { maximumFractionDigits: 1 })} ${unit}`;
}

function polyline(points: Point[]) {
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  return points.map((point, index) => `${8 + index / Math.max(1, points.length - 1) * 224},${66 - (point.value - min) / span * 52}`).join(" ");
}

function periodDurationYears(point: Point) {
  return Number(point.periodEnd.slice(0, 4)) - Number(point.periodStart.slice(0, 4));
}

function comparison(previous: Point, current: Point) {
  if (previous.unit !== current.unit || periodDurationYears(previous) !== periodDurationYears(current) || previous.value === 0) return null;
  const change = current.value - previous.value;
  return { change, percent: change / Math.abs(previous.value) * 100 };
}

function EmptyComparisonGauge({ reason }: { reason: string }) {
  return <figure className="comparison-gauge comparison-gauge--empty">
    <figcaption><span>Variazione rispetto al periodo precedente</span><strong>Non disponibile</strong></figcaption>
    <svg viewBox="0 0 200 112" role="img" aria-label="Variazione rispetto al periodo precedente non disponibile"><path className="comparison-gauge-track" d="M20 100A80 80 0 0 1 180 100" /><path className="comparison-gauge-center" d="M100 20V32" /><circle className="comparison-gauge-empty-dot" cx="100" cy="100" r="4" /></svg>
    <p><strong>—</strong><span>{reason}</span></p>
  </figure>;
}

function ComparisonGauge({ previous, current }: { previous: Point; current: Point }) {
  const result = comparison(previous, current);
  if (!result) return <EmptyComparisonGauge reason="Periodi non comparabili" />;
  const clamped = Math.max(-100, Math.min(100, result.percent));
  const radians = (-90 + clamped * .8) * Math.PI / 180;
  const pointerX = 100 + 58 * Math.cos(radians);
  const pointerY = 100 + 58 * Math.sin(radians);
  const direction = result.change > 0 ? "Aumento" : result.change < 0 ? "Diminuzione" : "Invariato";
  const sign = result.percent > 0 ? "+" : "";
  return <figure className={`comparison-gauge comparison-gauge--${result.change > 0 ? "up" : result.change < 0 ? "down" : "flat"}`}>
    <figcaption><span>Rispetto al periodo precedente</span><strong>{direction}</strong></figcaption>
    <svg viewBox="0 0 200 112" role="img" aria-label={`${direction} di ${Math.abs(result.percent).toLocaleString("it-IT", { maximumFractionDigits: 1 })}% rispetto al periodo precedente`}>
      <path className="comparison-gauge-track" d="M20 100A80 80 0 0 1 180 100" />
      <path className="comparison-gauge-center" d="M100 20V32" />
      <line className="comparison-gauge-needle" x1="100" y1="100" x2={pointerX} y2={pointerY} />
      <circle className="comparison-gauge-dot" cx="100" cy="100" r="4" />
    </svg>
    <p><strong>{sign}{result.percent.toLocaleString("it-IT", { maximumFractionDigits: 1 })}%</strong><span>{result.change > 0 ? "+" : ""}{format(result.change, current.unit)}</span></p>
    <small>{TEMPORAL_COMPARISON_UI_VERSION}: valore {current.period} − valore {previous.period}.</small>
  </figure>;
}

export function TerritoryMapSeries({ options, territoryId, territoryName, selectedPeriod }: { options: MapOption[]; territoryId?: string; territoryName?: string; selectedPeriod?: string }) {
  const [points, setPoints] = useState<Point[] | null>(null);
  const requestKey = useMemo(() => options.map((option) => `${option.periodKey}:${option.url}`).join("|"), [options]);

  useEffect(() => {
    if (!territoryId || !options.length) {
      setPoints(null);
      return;
    }
    const controller = new AbortController();
    setPoints(null);
    async function load() {
      const next = await Promise.all(options.map(async (option) => {
        const response = await fetch(option.url, { signal: controller.signal });
        if (!response.ok) throw new Error(`Serie non disponibile (${response.status}).`);
        const dataset = await response.json() as MapDataset;
        const value = dataset.values.find(([id]) => id === territoryId)?.[1];
        return typeof value === "number" ? { period: option.periodKey, periodStart: dataset.periodStart, periodEnd: dataset.periodEnd, value, unit: dataset.unit } : null;
      }));
      if (!controller.signal.aborted) setPoints(next.filter((point): point is Point => point !== null));
    }
    void load().catch(() => { if (!controller.signal.aborted) setPoints([]); });
    return () => controller.abort();
  }, [options, requestKey, territoryId]);

  const selectedIndex = points && selectedPeriod ? points.findIndex((point) => point.period === selectedPeriod) : (points?.length ?? 0) - 1;
  const visiblePoints = points && selectedIndex >= 0 ? points.slice(0, selectedIndex + 1) : points;
  const current = visiblePoints?.at(-1);
  const previous = visiblePoints?.at(-2);
  const missingComparisonReason = points?.length === 1
    ? "La metrica pubblica un solo periodo"
    : "Manca periodo precedente";

  return <section className="sidebar-section territory-series" aria-live="polite">
    <h3>Serie del territorio</h3>
    {!territoryId ? <><p className="sidebar-context">Seleziona un territorio nella mappa: qui compariranno solo i valori ufficiali della zona scelta.</p><EmptyComparisonGauge reason="Seleziona un territorio" /></> : points === null ? <p className="sidebar-context">Carico serie di {territoryLabel(territoryId, territoryName)}…</p> : !current || !previous ? <><p className="sidebar-context"><strong>{territoryLabel(territoryId, territoryName)}</strong>{points.length === 1 ? " La metrica corrente pubblica un solo periodo." : " Il periodo selezionato non ha un predecessore comparabile pubblicato."}</p><EmptyComparisonGauge reason={missingComparisonReason} /></> : <><p className="sidebar-context"><strong>{territoryLabel(territoryId, territoryName)}</strong>Valori ufficiali; nessuna interpolazione.</p><figure className="sidebar-series-chart"><svg viewBox="0 0 240 74" role="img" aria-label={`Serie ufficiale di ${territoryLabel(territoryId, territoryName)}`}><path d="M8 66H232" className="chart-axis" /><polyline points={polyline(visiblePoints!)} className="chart-line" /></svg><figcaption><span>{visiblePoints![0].period}</span><span>{current.period}</span></figcaption></figure><ComparisonGauge previous={previous} current={current} /><p className="sidebar-context"><strong>Precedente:</strong> {format(previous.value, previous.unit)} · {previous.period}<br /><strong>Selezionato:</strong> {format(current.value, current.unit)} · {current.period}</p></>}
  </section>;
}
