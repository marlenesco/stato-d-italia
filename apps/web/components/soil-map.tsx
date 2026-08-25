"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import type { MapOption } from "../lib/data";
import { domainColorRamps, type DomainColorName, type DomainColorRamp } from "../lib/domain-colors";
import { territoryLabel } from "../lib/territory-labels";

type MapDataset = { values: [string, number][]; unit: string; periodStart: string; periodEnd: string };
type RankingRow = { territoryId: string; name: string; istatCode: string; value: number; percentile: number | null; rank: number | null };
type Ranking = { rows: RankingRow[] };
type RankingState = "loading" | "available" | "not-applicable" | "unavailable";

let protocol: import("pmtiles").Protocol | undefined;

function fillColorExpression(min: number, max: number, ramp: DomainColorRamp): import("maplibre-gl").ExpressionSpecification {
  const midpoint = min + (max - min) / 2;
  return ["interpolate", ["linear"], ["coalesce", ["feature-state", "value"], min], min, ramp.low, midpoint, ramp.mid, max, ramp.high];
}

function formatNumber(value: number, unit?: string) {
  return `${value.toLocaleString("it-IT", { maximumFractionDigits: 1 })}${unit ? ` ${unit}` : ""}`;
}

function formatPeriod(periodStart: string, periodEnd: string) {
  const start = periodStart.slice(0, 4);
  const end = periodEnd.slice(0, 4);
  return start === end ? start : `${start}–${end}`;
}

function territoryHref(level: string, istatCode: string) {
  const route = level === "municipality" ? "comuni" : level === "province" ? "province" : "regioni";
  return `/territori/${route}/${istatCode}`;
}

export function SoilMap({ option, metricLabel, geometryUrl, rankingUrl, selectedTerritoryId, colorRamp = "soil" }: { option: MapOption; metricLabel: string; geometryUrl?: string; rankingUrl?: string; selectedTerritoryId?: string; colorRamp?: DomainColorName }) {
  const ramp = domainColorRamps[colorRamp];
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<import("maplibre-gl").Map | null>(null);
  const featureIds = useRef<string[]>([]);
  const currentDataset = useRef<MapDataset | null>(null);
  const selectedFeatureId = useRef<string | null>(null);
  const [ranking, setRanking] = useState<Ranking | null>(null);
  const [rankingState, setRankingState] = useState<RankingState>(rankingUrl ? "loading" : "not-applicable");
  const [rankingError, setRankingError] = useState<string | null>(null);
  const [mapError, setMapError] = useState<string | null>(null);
  const [valuesLoading, setValuesLoading] = useState(true);
  const [dataset, setDataset] = useState<MapDataset | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(selectedTerritoryId ?? null);

  useEffect(() => {
    setMapReady(false);
    setMapError(null);
    setDataset(null);
    setValuesLoading(true);
    const mapContainer = container.current;
    if (!geometryUrl || !mapContainer) {
      setMapError("La geometria per questo livello territoriale non è disponibile.");
      setValuesLoading(false);
      return;
    }
    const target: HTMLDivElement = mapContainer;
    const pmtilesUrl = geometryUrl;
    let map: import("maplibre-gl").Map | undefined;
    let resizeObserver: ResizeObserver | undefined;
    let disposed = false;
    async function createMap() {
      try {
        const [maplibregl, { PMTiles, Protocol }] = await Promise.all([import("maplibre-gl"), import("pmtiles")]);
        if (disposed) return;
        if (!protocol) {
          protocol = new Protocol();
          maplibregl.addProtocol("pmtiles", protocol.tile);
        }
        protocol.add(new PMTiles(pmtilesUrl));
        map = new maplibregl.Map({
          container: target,
          style: {
            version: 8,
            sources: { territories: { type: "vector", url: `pmtiles://${pmtilesUrl}`, promoteId: "territory_id" } },
            layers: [
              { id: "background", type: "background", paint: { "background-color": ramp.surface } },
              { id: "soil-fill", type: "fill", source: "territories", "source-layer": "territories", paint: { "fill-color": fillColorExpression(0, 1, ramp), "fill-opacity": 0.82 } },
              { id: "soil-line", type: "line", source: "territories", "source-layer": "territories", paint: { "line-color": ramp.outline, "line-width": 0.4 } },
              { id: "soil-selected", type: "line", source: "territories", "source-layer": "territories", paint: { "line-color": "#182120", "line-width": ["case", ["boolean", ["feature-state", "selected"], false], 2.2, 0] } },
            ],
          },
          center: [12.5, 42.8],
          zoom: 5,
        });
        const activeMap = map;
        activeMap.on("error", (event) => setMapError(event.error.message));
        activeMap.once("load", () => {
          if (disposed) return;
          mapRef.current = activeMap;
          resizeObserver = new ResizeObserver(() => activeMap.resize());
          resizeObserver.observe(target);
          requestAnimationFrame(() => activeMap.resize());
          setMapReady(true);
          activeMap.on("click", "soil-fill", (event) => { const feature = event.features?.[0]; if (feature?.id !== undefined) setSelectedId(String(feature.id)); });
          const hoverPopup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 12 });
          activeMap.on("mousemove", "soil-fill", (event) => {
            const feature = event.features?.[0];
            if (feature?.id === undefined) return;
            const id = String(feature.id);
            const value = activeMap.getFeatureState({ source: "territories", sourceLayer: "territories", id }).value;
            const label = territoryLabel(id, typeof feature.properties?.name === "string" ? feature.properties.name : undefined);
            hoverPopup.setLngLat(event.lngLat).setText(`${label} · ${typeof value === "number" ? formatNumber(value, currentDataset.current?.unit) : "valore non disponibile"}`).addTo(activeMap);
          });
          activeMap.on("mouseenter", "soil-fill", () => { activeMap.getCanvas().style.cursor = "pointer"; });
          activeMap.on("mouseleave", "soil-fill", () => { activeMap.getCanvas().style.cursor = ""; hoverPopup.remove(); });
        });
      } catch (caught) {
        setMapError(caught instanceof Error ? caught.message : "Impossibile caricare la mappa.");
        setValuesLoading(false);
      }
    }
    void createMap();
    return () => { disposed = true; resizeObserver?.disconnect(); mapRef.current = null; featureIds.current = []; currentDataset.current = null; selectedFeatureId.current = null; map?.remove(); };
  }, [geometryUrl, ramp]);

  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    const controller = new AbortController();
    setValuesLoading(true);
    setMapError(null);
    setDataset(null);
    async function updateValues() {
      try {
        const response = await fetch(option.url, { signal: controller.signal });
        if (!response.ok) throw new Error(`Valori della mappa non disponibili (${response.status}).`);
        const nextDataset = await response.json() as MapDataset;
        const values = nextDataset.values.map((item) => item[1]).filter(Number.isFinite);
        if (!values.length) throw new Error("La mappa non contiene valori numerici pubblicati.");
        const activeMap = mapRef.current;
        if (controller.signal.aborted || !activeMap) return;
        featureIds.current.forEach((territoryId) => activeMap.removeFeatureState({ source: "territories", sourceLayer: "territories", id: territoryId }));
        nextDataset.values.forEach(([territoryId, value]) => activeMap.setFeatureState({ source: "territories", sourceLayer: "territories", id: territoryId }, { value }));
        featureIds.current = nextDataset.values.map(([territoryId]) => territoryId);
        activeMap.setPaintProperty("soil-fill", "fill-color", fillColorExpression(Math.min(...values), Math.max(...values), ramp));
        currentDataset.current = nextDataset;
        setDataset(nextDataset);
      } catch (caught) {
        if (!controller.signal.aborted) setMapError(caught instanceof Error ? caught.message : "Impossibile caricare i valori della mappa.");
      } finally {
        if (!controller.signal.aborted) setValuesLoading(false);
      }
    }
    void updateValues();
    return () => controller.abort();
  }, [mapReady, option.url, ramp]);

  useEffect(() => { setSelectedId(selectedTerritoryId ?? null); }, [selectedTerritoryId]);

  useEffect(() => {
    const map = mapRef.current;
    if (!mapReady || !map) return;
    if (selectedFeatureId.current) map.setFeatureState({ source: "territories", sourceLayer: "territories", id: selectedFeatureId.current }, { selected: false });
    if (selectedId) map.setFeatureState({ source: "territories", sourceLayer: "territories", id: selectedId }, { selected: true });
    selectedFeatureId.current = selectedId;
  }, [mapReady, selectedId]);

  useEffect(() => {
    const controller = new AbortController();
    setRanking(null);
    setRankingError(null);
    if (!rankingUrl) {
      setRankingState("not-applicable");
      return () => controller.abort();
    }
    setRankingState("loading");
    fetch(rankingUrl, { signal: controller.signal })
      .then((response) => response.ok ? response.json() as Promise<Ranking> : Promise.reject(new Error(`Confronto non disponibile (${response.status}).`)))
      .then((nextRanking) => { if (!controller.signal.aborted) { setRanking(nextRanking); setRankingState("available"); } })
      .catch((caught) => { if (!controller.signal.aborted) { setRankingState("unavailable"); setRankingError(caught instanceof Error ? caught.message : "Impossibile caricare il confronto."); } });
    return () => controller.abort();
  }, [rankingUrl]);

  const selectedRow = ranking?.rows.find((row) => row.territoryId === selectedId);
  const selectedValue = dataset?.values.find(([territoryId]) => territoryId === selectedId)?.[1];
  const mapValues = dataset?.values.map(([, value]) => value).filter(Number.isFinite) ?? [];
  const min = mapValues.length ? Math.min(...mapValues) : null;
  const max = mapValues.length ? Math.max(...mapValues) : null;
  const middle = min !== null && max !== null ? min + (max - min) / 2 : null;

  return <>
    <section className={`map-stage map-stage--${colorRamp}`} style={{ "--map-ramp-low": ramp.low, "--map-ramp-mid": ramp.mid, "--map-ramp-high": ramp.high, "--map-ramp-outline": ramp.outline } as CSSProperties} aria-labelledby="map-title">
      <header className="map-heading"><div><p className="eyebrow">Mappa tematica</p><h2 id="map-title">{metricLabel}</h2><p>{dataset ? `${formatPeriod(dataset.periodStart, dataset.periodEnd)} · ${dataset.unit}` : option.periodKey}</p></div><p className="map-status" aria-live="polite">{valuesLoading ? "Carico valori…" : mapError ? "Valori non disponibili" : "Seleziona un territorio"}</p></header>
      <div className="map-wrap"><div ref={container} className="map" role="img" aria-label="Mappa tematica interattiva. La tabella di confronto è disponibile sotto." />
        {min !== null && middle !== null && max !== null && <aside className="map-legend" aria-label={`Legenda ${metricLabel}`}><strong>Valore pubblicato</strong><div className="legend-scale" aria-hidden="true" /><div className="legend-values"><span>{formatNumber(min, dataset?.unit)}</span><span>{formatNumber(middle, dataset?.unit)}</span><span>{formatNumber(max, dataset?.unit)}</span></div><p>Il colore mostra l’intensità del valore, non un giudizio sul territorio.</p></aside>}
      </div>
      {mapError && <p className="map-message" role="alert">{mapError}</p>}
      {selectedId && <aside className="territory-inspector" aria-live="polite"><p className="eyebrow">Territorio selezionato</p>{selectedRow ? <><h3>{territoryLabel(selectedRow.territoryId, selectedRow.name)}</h3><p><strong>{formatNumber(selectedRow.value, dataset?.unit)}</strong>{selectedRow.rank !== null && <> · posizione {selectedRow.rank}</>}</p><Link href={territoryHref(option.level, selectedRow.istatCode)}>Apri profilo territoriale</Link></> : <><h3>{territoryLabel(selectedId)}</h3><p>{selectedValue === undefined ? "Nessun valore associato nel dataset visualizzato." : formatNumber(selectedValue, dataset?.unit)}</p></>}</aside>}
    </section>
    <section className="ranking" aria-labelledby="ranking-title"><div className="section-heading"><div><p className="eyebrow">Confronto</p><h2 id="ranking-title">Territori nello stesso periodo</h2></div><p>Alternativa testuale alla mappa</p></div>
      {rankingState === "available" && ranking ? <div className="table-scroll"><table><thead><tr><th>Territorio</th><th>Valore</th><th>Posizione</th><th>Percentile</th></tr></thead><tbody>{ranking.rows.slice(0, 25).map((row) => <tr key={row.territoryId} className={row.territoryId === selectedId ? "is-selected" : undefined}><th scope="row"><button type="button" onClick={() => setSelectedId(row.territoryId)}>{row.name}</button></th><td>{formatNumber(row.value, dataset?.unit)}</td><td>{row.rank ?? "—"}</td><td>{row.percentile === null ? "—" : row.percentile.toLocaleString("it-IT", { maximumFractionDigits: 1 })}</td></tr>)}</tbody></table></div> : rankingState === "loading" ? <p className="state-copy" role="status">Carico il confronto territoriale pubblicato…</p> : rankingState === "not-applicable" ? <p className="state-copy">Per questa combinazione di metrica, livello e periodo non è pubblicato un confronto territoriale.</p> : <p className="state-copy" role="alert">Il confronto non è momentaneamente disponibile. {rankingError}</p>}
    </section>
  </>;
}
