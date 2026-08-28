"use client";

import { useEffect, useRef, useState } from "react";
import type { MapOption } from "../lib/data";
import { configureItalyMapControls, italyMapCamera } from "../lib/italy-map-bounds";
import { territoryIstatCode, territoryLabel } from "../lib/territory-labels";
import { TerritoryMapSeries } from "./territory-map-series";

type MapDataset = { values: [string, number][]; unit: string; periodStart: string; periodEnd: string };
type MapCamera = { center: [number, number]; zoom: number; bearing: number; pitch: number };

const WATER_CAMERA_STORAGE_KEY = "stato-italia:map-camera:water:region";
let protocol: import("pmtiles").Protocol | undefined;

function savedWaterCamera(): MapCamera | undefined {
  try {
    const saved = JSON.parse(window.sessionStorage.getItem(WATER_CAMERA_STORAGE_KEY) ?? "null") as Partial<MapCamera> | null;
    const [longitude, latitude] = saved?.center ?? [];
    const { zoom, bearing, pitch } = saved ?? {};
    if (typeof longitude !== "number" || typeof latitude !== "number" || typeof zoom !== "number" || typeof bearing !== "number" || typeof pitch !== "number" || !Number.isFinite(longitude) || !Number.isFinite(latitude) || !Number.isFinite(zoom) || !Number.isFinite(bearing) || !Number.isFinite(pitch)) return undefined;
    return { center: [longitude, latitude], zoom, bearing, pitch };
  } catch {
    return undefined;
  }
}

function saveWaterCamera(map: import("maplibre-gl").Map) {
  const center = map.getCenter();
  window.sessionStorage.setItem(WATER_CAMERA_STORAGE_KEY, JSON.stringify({ center: [center.lng, center.lat], zoom: map.getZoom(), bearing: map.getBearing(), pitch: map.getPitch() } satisfies MapCamera));
}

function colorExpression(min: number, max: number): import("maplibre-gl").ExpressionSpecification {
  const middle = min + (max - min) / 2;
  return ["case", ["==", ["typeof", ["feature-state", "value"]], "number"], ["interpolate", ["linear"], ["feature-state", "value"], min, "#e9f0e7", middle, "#78b5b4", max, "#075c70"], "#ffffff"];
}

function display(value: number, unit: string) {
  return `${value.toLocaleString("it-IT", { maximumFractionDigits: 1 })} ${unit}`;
}

export function WaterMap({ option, metricLabel, geometryUrl, selectedTerritoryId, seriesOptions, onTerritorySelect }: { option: MapOption; metricLabel: string; geometryUrl?: string; selectedTerritoryId?: string; seriesOptions?: MapOption[]; onTerritorySelect?: (territoryId: string, name?: string) => void }) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<import("maplibre-gl").Map | null>(null);
  const featureIds = useRef<string[]>([]);
  const currentDataset = useRef<MapDataset | null>(null);
  const selectedFeatureId = useRef<string | null>(null);
  const onTerritorySelectRef = useRef(onTerritorySelect);
  const [dataset, setDataset] = useState<MapDataset | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<{ id: string; name?: string } | null>(selectedTerritoryId ? { id: selectedTerritoryId } : null);

  useEffect(() => { onTerritorySelectRef.current = onTerritorySelect; }, [onTerritorySelect]);

  useEffect(() => {
    setMapReady(false);
    setDataset(null);
    setLoading(true);
    setError(null);
    const target = container.current;
    if (!geometryUrl || !target) {
      setError("Geometria regionale non disponibile.");
      setLoading(false);
      return;
    }
    const pmtilesUrl = geometryUrl;
    const initialCamera = savedWaterCamera() ?? italyMapCamera;
    const mapTarget = target;
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
        map = new maplibregl.Map({ container: mapTarget, style: { version: 8, sources: { territories: { type: "vector", url: `pmtiles://${pmtilesUrl}`, promoteId: "territory_id" } }, layers: [{ id: "water-background", type: "background", paint: { "background-color": "#eef3ee" } }, { id: "water-fill", type: "fill", source: "territories", "source-layer": "territories", paint: { "fill-color": colorExpression(0, 1), "fill-outline-color": "#9ab6ae", "fill-opacity": 0.86 } }, { id: "water-selected", type: "fill", source: "territories", "source-layer": "territories", paint: { "fill-color": "#182120", "fill-opacity": ["case", ["boolean", ["feature-state", "selected"], false], 0.16, 0] } }] }, ...initialCamera });
        configureItalyMapControls(map, maplibregl);
        const activeMap = map;
        activeMap.on("error", (event) => setError(event.error.message));
        activeMap.once("load", () => {
          if (disposed) return;
          mapRef.current = activeMap;
          resizeObserver = new ResizeObserver(() => activeMap.resize());
          resizeObserver.observe(mapTarget);
          requestAnimationFrame(() => activeMap.resize());
          activeMap.on("moveend", () => saveWaterCamera(activeMap));
          setMapReady(true);
          activeMap.on("click", "water-fill", (event) => { const feature = event.features?.[0]; if (feature?.id !== undefined) { const id = String(feature.id); if (!Number.isFinite(activeMap.getFeatureState({ source: "territories", sourceLayer: "territories", id }).value)) return; const next = { id, name: typeof feature.properties?.name === "string" ? feature.properties.name : undefined }; setSelected(next); onTerritorySelectRef.current?.(next.id, next.name); } });
          const hoverPopup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 12 });
          activeMap.on("mousemove", "water-fill", (event) => {
            const feature = event.features?.[0];
            if (feature?.id === undefined) return;
            const id = String(feature.id);
            const value = activeMap.getFeatureState({ source: "territories", sourceLayer: "territories", id }).value;
            if (!Number.isFinite(value)) { activeMap.getCanvas().style.cursor = ""; hoverPopup.remove(); return; }
            const unit = currentDataset.current?.unit ?? "mm";
            const label = territoryLabel(id, typeof feature.properties?.name === "string" ? feature.properties.name : undefined);
            activeMap.getCanvas().style.cursor = "pointer";
            hoverPopup.setLngLat(event.lngLat).setText(`${label} · ${display(value, unit)}`).addTo(activeMap);
          });
          activeMap.on("mouseleave", "water-fill", () => { activeMap.getCanvas().style.cursor = ""; hoverPopup.remove(); });
        });
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Impossibile caricare la mappa.");
        setLoading(false);
      }
    }
    void createMap();
    return () => { disposed = true; resizeObserver?.disconnect(); mapRef.current = null; featureIds.current = []; currentDataset.current = null; selectedFeatureId.current = null; map?.remove(); };
  }, [geometryUrl]);

  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setDataset(null);
    fetch(option.url, { signal: controller.signal }).then((response) => response.ok ? response.json() as Promise<MapDataset> : Promise.reject(new Error(`Valori non disponibili (${response.status}).`))).then((nextDataset) => {
      const values = nextDataset.values.map(([, value]) => value).filter(Number.isFinite);
      if (!values.length) throw new Error("Mappa senza valori numerici pubblicati.");
      const map = mapRef.current;
      if (controller.signal.aborted || !map) return;
      featureIds.current.forEach((id) => map.removeFeatureState({ source: "territories", sourceLayer: "territories", id }));
      nextDataset.values.forEach(([id, value]) => map.setFeatureState({ source: "territories", sourceLayer: "territories", id }, { value }));
      featureIds.current = nextDataset.values.map(([id]) => id);
      map.setPaintProperty("water-fill", "fill-color", colorExpression(Math.min(...values), Math.max(...values)));
      currentDataset.current = nextDataset;
      setDataset(nextDataset);
    }).catch((caught) => { if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : "Impossibile caricare i valori."); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [mapReady, option.url]);

  useEffect(() => {
    setSelected((current) => selectedTerritoryId ? current?.id === selectedTerritoryId ? current : { id: selectedTerritoryId } : null);
  }, [selectedTerritoryId]);

  useEffect(() => {
    const map = mapRef.current;
    if (!mapReady || !map || !selected || selected.name) return;
    const resolveName = () => {
      const features = [
        ...map.queryRenderedFeatures(undefined, { layers: ["water-fill"] }),
        ...map.querySourceFeatures("territories", { sourceLayer: "territories" }),
      ];
      const feature = features.find((candidate) => String(candidate.id ?? candidate.properties?.territory_id) === selected.id);
      const name = typeof feature?.properties?.name === "string" ? feature.properties.name : undefined;
      if (name) setSelected((current) => current?.id === selected.id ? { ...current, name } : current);
    };
    resolveName();
    map.on("idle", resolveName);
    return () => { map.off("idle", resolveName); };
  }, [mapReady, selected]);

  useEffect(() => {
    const map = mapRef.current;
    if (!mapReady || !map || !dataset) return;
    if (selectedFeatureId.current) map.setFeatureState({ source: "territories", sourceLayer: "territories", id: selectedFeatureId.current }, { selected: false });
    if (selected?.id) map.setFeatureState({ source: "territories", sourceLayer: "territories", id: selected.id }, { selected: true });
    selectedFeatureId.current = selected?.id ?? null;
  }, [dataset, mapReady, selected]);

  const values = dataset?.values.map(([, value]) => value).filter(Number.isFinite) ?? [];
  const min = values.length ? Math.min(...values) : null;
  const max = values.length ? Math.max(...values) : null;
  const middle = min !== null && max !== null ? min + (max - min) / 2 : null;
  const selectedValue = selected && dataset?.values.find(([id]) => id === selected.id)?.[1];
  const selectedLabel = selected ? territoryLabel(selected.id, selected.name) : null;

  return <section className="water-map-stage" aria-labelledby="water-map-title"><header className="map-heading"><div><p className="eyebrow">Atlante regionale</p><h2 id="water-map-title">{metricLabel}</h2><p>{dataset ? dataset.periodEnd.slice(0, 4) : option.periodKey} · valori annui</p></div><p className="map-status" aria-live="polite">{loading ? "Carico valori…" : error ? "Valori non disponibili" : selectedLabel ? selectedValue == null ? `Regione selezionata: dato non pubblicato` : `Regione selezionata: ${selectedLabel}` : "Seleziona regione"}</p></header><div className="map-wrap"><div ref={container} className="map water-map" role="img" aria-label="Mappa regionale interattiva. I colori mostrano valori ufficiali modellistici." />{min !== null && middle !== null && max !== null && <aside className="water-legend" aria-label={`Legenda ${metricLabel}`}><strong>Valore annuale stimato</strong><div className="water-legend-scale" aria-hidden="true" /><div className="legend-values"><span>{display(min, dataset?.unit ?? "mm")}</span><span>{display(middle, dataset?.unit ?? "mm")}</span><span>{display(max, dataset?.unit ?? "mm")}</span></div><p>Scala relativa a metrica e anno selezionati.</p></aside>}{selected && <aside className="water-selection map-selection-drawer" aria-live="polite"><p className="eyebrow">Regione selezionata</p><h3>{selectedLabel}</h3><p className="territory-istat-code">Codice ISTAT · {territoryIstatCode(selected.id)}</p><strong>{selectedValue == null ? "Dato non pubblicato per anno e metrica selezionati" : display(selectedValue, dataset?.unit ?? "mm")}</strong><p>Anno {dataset?.periodEnd.slice(0, 4) ?? option.periodKey} · stima ufficiale modellistica</p><TerritoryMapSeries options={seriesOptions ?? [option]} territoryId={selected.id} territoryName={selected.name} selectedPeriod={option.periodKey} statusNote="Stima ufficiale modellistica; nessuna interpolazione." /></aside>}</div>{error && <p className="map-message" role="alert">{error}</p>}</section>;
}
