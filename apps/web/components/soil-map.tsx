"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import type { MapOption } from "../lib/data";
import { domainColorRamps, type DomainColorName, type DomainColorRamp } from "../lib/domain-colors";
import { configureItalyMapControls, italyMapCamera } from "../lib/italy-map-bounds";
import { territoryIstatCode, territoryLabel } from "../lib/territory-labels";
import { TerritoryMapSeries } from "./territory-map-series";

type MapDataset = { values: [string, number][]; unit: string; periodStart: string; periodEnd: string };
type RankingRow = { territoryId: string; name: string; istatCode: string; value: number; percentile: number | null; rank: number | null };
type Ranking = { rows: RankingRow[]; scopeLabel?: string };
type RankingState = "loading" | "available" | "not-applicable" | "unavailable";

let protocol: import("pmtiles").Protocol | undefined;

function fillColorExpression(min: number, max: number, ramp: DomainColorRamp): import("maplibre-gl").ExpressionSpecification {
  const midpoint = min + (max - min) / 2;
  return ["case", ["==", ["typeof", ["feature-state", "value"]], "number"], ["interpolate", ["linear"], ["feature-state", "value"], min, ramp.low, midpoint, ramp.mid, max, ramp.high], "#ffffff"];
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

export function SoilMap({ option, metricLabel, geometryUrl, rankingUrl, selectedTerritoryId, seriesOptions, seriesStatusNote, colorRamp = "soil", comparisonNote, onTerritorySelect }: { option: MapOption; metricLabel: string; geometryUrl?: string; rankingUrl?: string; selectedTerritoryId?: string; seriesOptions?: MapOption[]; seriesStatusNote?: string; colorRamp?: DomainColorName; comparisonNote?: string; onTerritorySelect?: (territoryId: string, name?: string) => void }) {
  const ramp = domainColorRamps[colorRamp];
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<import("maplibre-gl").Map | null>(null);
  const featureIds = useRef<string[]>([]);
  const currentDataset = useRef<MapDataset | null>(null);
  const selectedFeatureId = useRef<string | null>(null);
  const onTerritorySelectRef = useRef(onTerritorySelect);
  const [ranking, setRanking] = useState<Ranking | null>(null);
  const [rankingState, setRankingState] = useState<RankingState>(rankingUrl ? "loading" : "not-applicable");
  const [rankingError, setRankingError] = useState<string | null>(null);
  const [mapError, setMapError] = useState<string | null>(null);
  const [valuesLoading, setValuesLoading] = useState(true);
  const [dataset, setDataset] = useState<MapDataset | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(selectedTerritoryId ?? null);
  const [selectedName, setSelectedName] = useState<string | undefined>();

  useEffect(() => { onTerritorySelectRef.current = onTerritorySelect; }, [onTerritorySelect]);

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
              { id: "soil-fill", type: "fill", source: "territories", "source-layer": "territories", paint: { "fill-color": fillColorExpression(0, 1, ramp), "fill-outline-color": ramp.outline, "fill-opacity": 0.82 } },
              { id: "soil-selected", type: "fill", source: "territories", "source-layer": "territories", paint: { "fill-color": "#182120", "fill-opacity": ["case", ["boolean", ["feature-state", "selected"], false], 0.16, 0] } },
            ],
          },
          ...italyMapCamera,
        });
        configureItalyMapControls(map, maplibregl);
        const activeMap = map;
        activeMap.on("error", (event) => setMapError(event.error.message));
        activeMap.once("load", () => {
          if (disposed) return;
          mapRef.current = activeMap;
          resizeObserver = new ResizeObserver(() => activeMap.resize());
          resizeObserver.observe(target);
          requestAnimationFrame(() => activeMap.resize());
          setMapReady(true);
          activeMap.on("click", "soil-fill", (event) => { const feature = event.features?.[0]; if (feature?.id !== undefined) { const id = String(feature.id); if (!Number.isFinite(activeMap.getFeatureState({ source: "territories", sourceLayer: "territories", id }).value)) return; const name = typeof feature.properties?.name === "string" ? feature.properties.name : undefined; setSelectedId(id); setSelectedName(name); onTerritorySelectRef.current?.(id, name); } });
          const hoverPopup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 12 });
          activeMap.on("mousemove", "soil-fill", (event) => {
            const feature = event.features?.[0];
            if (feature?.id === undefined) return;
            const id = String(feature.id);
            const value = activeMap.getFeatureState({ source: "territories", sourceLayer: "territories", id }).value;
            if (!Number.isFinite(value)) { activeMap.getCanvas().style.cursor = ""; hoverPopup.remove(); return; }
            const label = territoryLabel(id, typeof feature.properties?.name === "string" ? feature.properties.name : undefined);
            activeMap.getCanvas().style.cursor = "pointer";
            hoverPopup.setLngLat(event.lngLat).setText(`${label} · ${formatNumber(value, currentDataset.current?.unit)}`).addTo(activeMap);
          });
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
        const [mapUrl, snapCode] = option.url.split("#", 2);
        const response = await fetch(mapUrl, { signal: controller.signal });
        if (!response.ok) throw new Error(`Valori della mappa non disponibili (${response.status}).`);
        const raw = await response.json() as MapDataset & { snapshots?: Array<{ sourceDimensions: { snap_code: string }; unit: string; values: [string, number][] }> };
        const snapshot = raw.snapshots?.find((item) => item.sourceDimensions.snap_code === snapCode);
        const nextDataset = snapshot ? { values: snapshot.values, unit: snapshot.unit, periodStart: raw.periodStart, periodEnd: raw.periodEnd } : raw;
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

  useEffect(() => { setSelectedId(selectedTerritoryId ?? null); setSelectedName(undefined); }, [selectedTerritoryId]);

  useEffect(() => {
    const map = mapRef.current;
    if (!mapReady || !map || !selectedId || selectedName) return;
    const resolveName = () => {
      const features = [
        ...map.queryRenderedFeatures(undefined, { layers: ["soil-fill"] }),
        ...map.querySourceFeatures("territories", { sourceLayer: "territories" }),
      ];
      const feature = features.find((candidate) => String(candidate.id ?? candidate.properties?.territory_id) === selectedId);
      const name = typeof feature?.properties?.name === "string" ? feature.properties.name : undefined;
      if (name) setSelectedName(name);
    };
    resolveName();
    map.on("idle", resolveName);
    return () => { map.off("idle", resolveName); };
  }, [mapReady, selectedId, selectedName]);

  useEffect(() => {
    const map = mapRef.current;
    if (!mapReady || !map || !dataset) return;
    if (selectedFeatureId.current) map.setFeatureState({ source: "territories", sourceLayer: "territories", id: selectedFeatureId.current }, { selected: false });
    if (selectedId) map.setFeatureState({ source: "territories", sourceLayer: "territories", id: selectedId }, { selected: true });
    selectedFeatureId.current = selectedId;
  }, [dataset, mapReady, selectedId]);

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
  const selectedLabel = selectedRow ? territoryLabel(selectedRow.territoryId, selectedRow.name) : selectedId ? territoryLabel(selectedId, selectedName) : null;
  const levelLabel = option.level === "municipality" ? "Comune" : option.level === "province" ? "Provincia" : "Regione";
  const selectionLabel = option.level === "municipality" ? "Comune selezionato" : option.level === "province" ? "Provincia selezionata" : "Regione selezionata";

  return <>
    <section className={`map-stage map-stage--${colorRamp}`} style={{ "--map-ramp-low": ramp.low, "--map-ramp-mid": ramp.mid, "--map-ramp-high": ramp.high, "--map-ramp-outline": ramp.outline } as CSSProperties} aria-labelledby="map-title">
      <header className="map-heading"><div><p className="eyebrow">Mappa tematica</p><h2 id="map-title">{metricLabel}</h2><p>{dataset ? `${formatPeriod(dataset.periodStart, dataset.periodEnd)} · ${dataset.unit}` : option.periodKey}</p></div><p className="map-status" aria-live="polite">{valuesLoading ? "Carico valori…" : mapError ? "Valori non disponibili" : selectedLabel ? selectedValue === undefined ? `${selectionLabel}: dato non pubblicato` : `${selectionLabel}: ${selectedLabel}` : "Seleziona un territorio"}</p></header>
      <div className="map-wrap"><div ref={container} className="map" role="img" aria-label="Mappa tematica interattiva. La tabella di confronto è disponibile sotto." />
        {min !== null && middle !== null && max !== null && <aside className="map-legend" aria-label={`Legenda ${metricLabel}`}><strong>Valore pubblicato</strong><div className="legend-scale" aria-hidden="true" /><div className="legend-values"><span>{formatNumber(min, dataset?.unit)}</span><span>{formatNumber(middle, dataset?.unit)}</span><span>{formatNumber(max, dataset?.unit)}</span></div><p>{mapValues.length} territori con valore pubblicato. Il bianco indica un valore non disponibile; il colore non è un giudizio sul territorio.</p></aside>}
        {selectedId && <aside className="territory-inspector map-selection-drawer" aria-live="polite"><p className="eyebrow">{selectionLabel}</p>{selectedRow ? <><h3>{territoryLabel(selectedRow.territoryId, selectedRow.name)}</h3><p className="territory-istat-code">Codice ISTAT · {territoryIstatCode(selectedRow.territoryId, selectedRow.istatCode)}</p><p><strong>{formatNumber(selectedRow.value, dataset?.unit)}</strong>{selectedRow.rank !== null && <> · posizione {selectedRow.rank}</>}</p><Link href={territoryHref(option.level, selectedRow.istatCode)}>Apri profilo {levelLabel.toLocaleLowerCase("it")}</Link></> : <><h3>{territoryLabel(selectedId, selectedName)}</h3><p className="territory-istat-code">Codice ISTAT · {territoryIstatCode(selectedId)}</p><p>{selectedValue === undefined ? "Dato non pubblicato per periodo e metrica selezionati." : formatNumber(selectedValue, dataset?.unit)}</p></>}<TerritoryMapSeries options={seriesOptions ?? [option]} territoryId={selectedId} territoryName={selectedRow?.name ?? selectedName} selectedPeriod={option.periodKey} statusNote={seriesStatusNote} /></aside>}
      </div>
      {mapError && <p className="map-message" role="alert">{mapError}</p>}
    </section>
    <section className="ranking" aria-labelledby="ranking-title"><div className="section-heading"><div><p className="eyebrow">Confronto</p><h2 id="ranking-title">Territori nello stesso periodo</h2></div><p>{ranking?.scopeLabel ?? comparisonNote ?? "Alternativa testuale alla mappa"}</p></div>
      {rankingState === "available" && ranking ? <div className="table-scroll"><table><thead><tr><th>Territorio</th><th>Valore</th><th>Posizione</th><th>Percentile</th></tr></thead><tbody>{ranking.rows.slice(0, 25).map((row) => <tr key={row.territoryId} className={row.territoryId === selectedId ? "is-selected" : undefined}><th scope="row"><button type="button" onClick={() => { setSelectedId(row.territoryId); setSelectedName(row.name); onTerritorySelect?.(row.territoryId, row.name); }}>{row.name}</button></th><td>{formatNumber(row.value, dataset?.unit)}</td><td>{row.rank ?? "—"}</td><td>{row.percentile === null ? "—" : row.percentile.toLocaleString("it-IT", { maximumFractionDigits: 1 })}</td></tr>)}</tbody></table></div> : rankingState === "loading" ? <p className="state-copy" role="status">Carico il confronto territoriale pubblicato…</p> : rankingState === "not-applicable" ? <p className="state-copy">Per questa combinazione di metrica, livello e periodo non è pubblicato un confronto territoriale.</p> : <p className="state-copy" role="alert">Il confronto non è momentaneamente disponibile. {rankingError}</p>}
    </section>
  </>;
}
