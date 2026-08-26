"use client";

import { useEffect, useRef, useState } from "react";
import type { MapOption } from "../lib/data";
import { italyMapCamera } from "../lib/italy-map-bounds";
import { territoryLabel } from "../lib/territory-labels";

type MapDataset = { values: [string, number][]; unit: string; periodStart: string; periodEnd: string };
let protocol: import("pmtiles").Protocol | undefined;

function colorExpression(min: number, max: number): import("maplibre-gl").ExpressionSpecification {
  const middle = min + (max - min) / 2;
  return ["interpolate", ["linear"], ["coalesce", ["feature-state", "value"], min], min, "#e9f0e7", middle, "#78b5b4", max, "#075c70"];
}

function display(value: number, unit: string) {
  return `${value.toLocaleString("it-IT", { maximumFractionDigits: 1 })} ${unit}`;
}

export function WaterMap({ option, metricLabel, geometryUrl, onTerritorySelect }: { option: MapOption; metricLabel: string; geometryUrl?: string; onTerritorySelect?: (territoryId: string, name?: string) => void }) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<import("maplibre-gl").Map | null>(null);
  const featureIds = useRef<string[]>([]);
  const currentDataset = useRef<MapDataset | null>(null);
  const [dataset, setDataset] = useState<MapDataset | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<{ id: string; name?: string } | null>(null);

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
        map = new maplibregl.Map({ container: mapTarget, style: { version: 8, sources: { territories: { type: "vector", url: `pmtiles://${pmtilesUrl}`, promoteId: "territory_id" } }, layers: [{ id: "water-background", type: "background", paint: { "background-color": "#eef3ee" } }, { id: "water-fill", type: "fill", source: "territories", "source-layer": "territories", paint: { "fill-color": colorExpression(0, 1), "fill-outline-color": "#fffdf7", "fill-opacity": 0.86 } }] }, ...italyMapCamera });
        const activeMap = map;
        activeMap.on("error", (event) => setError(event.error.message));
        activeMap.once("load", () => {
          if (disposed) return;
          mapRef.current = activeMap;
          resizeObserver = new ResizeObserver(() => activeMap.resize());
          resizeObserver.observe(mapTarget);
          requestAnimationFrame(() => activeMap.resize());
          setMapReady(true);
          activeMap.on("click", "water-fill", (event) => { const feature = event.features?.[0]; if (feature?.id !== undefined) { const next = { id: String(feature.id), name: typeof feature.properties?.name === "string" ? feature.properties.name : undefined }; setSelected(next); onTerritorySelect?.(next.id, next.name); } });
          const hoverPopup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 12 });
          activeMap.on("mousemove", "water-fill", (event) => {
            const feature = event.features?.[0];
            if (feature?.id === undefined) return;
            const id = String(feature.id);
            const value = activeMap.getFeatureState({ source: "territories", sourceLayer: "territories", id }).value;
            const unit = currentDataset.current?.unit ?? "mm";
            const label = territoryLabel(id, typeof feature.properties?.name === "string" ? feature.properties.name : undefined);
            hoverPopup.setLngLat(event.lngLat).setText(`${label} · ${typeof value === "number" ? display(value, unit) : "valore non disponibile"}`).addTo(activeMap);
          });
          activeMap.on("mouseenter", "water-fill", () => { activeMap.getCanvas().style.cursor = "pointer"; });
          activeMap.on("mouseleave", "water-fill", () => { activeMap.getCanvas().style.cursor = ""; hoverPopup.remove(); });
        });
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Impossibile caricare la mappa.");
        setLoading(false);
      }
    }
    void createMap();
    return () => { disposed = true; resizeObserver?.disconnect(); mapRef.current = null; featureIds.current = []; currentDataset.current = null; map?.remove(); };
  }, [geometryUrl, onTerritorySelect]);

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

  const values = dataset?.values.map(([, value]) => value).filter(Number.isFinite) ?? [];
  const min = values.length ? Math.min(...values) : null;
  const max = values.length ? Math.max(...values) : null;
  const middle = min !== null && max !== null ? min + (max - min) / 2 : null;
  const selectedValue = selected && dataset?.values.find(([id]) => id === selected.id)?.[1];
  const selectedLabel = selected ? territoryLabel(selected.id, selected.name) : null;

  return <section className="water-map-stage" aria-labelledby="water-map-title"><header className="map-heading"><div><p className="eyebrow">Atlante regionale</p><h2 id="water-map-title">{metricLabel}</h2><p>{dataset ? dataset.periodEnd.slice(0, 4) : option.periodKey} · valori annui</p></div><p className="map-status" aria-live="polite">{loading ? "Carico valori…" : error ? "Valori non disponibili" : selectedLabel ? `Selezionata: ${selectedLabel}` : "Seleziona regione"}</p></header><div className="map-wrap"><div ref={container} className="map water-map" role="img" aria-label="Mappa regionale interattiva. I colori mostrano valori ufficiali modellistici." />{min !== null && middle !== null && max !== null && <aside className="water-legend" aria-label={`Legenda ${metricLabel}`}><strong>Valore annuale stimato</strong><div className="water-legend-scale" aria-hidden="true" /><div className="legend-values"><span>{display(min, dataset?.unit ?? "mm")}</span><span>{display(middle, dataset?.unit ?? "mm")}</span><span>{display(max, dataset?.unit ?? "mm")}</span></div><p>Scala relativa a metrica e anno selezionati.</p></aside>}</div>{error && <p className="map-message" role="alert">{error}</p>}{selected && <aside className="water-selection" aria-live="polite"><p className="eyebrow">Regione selezionata</p><h3>{selectedLabel}</h3><strong>{selectedValue == null ? "Valore non disponibile" : display(selectedValue, dataset?.unit ?? "mm")}</strong><p>Anno {dataset?.periodEnd.slice(0, 4) ?? option.periodKey} · stima ufficiale modellistica</p></aside>}</section>;
}
