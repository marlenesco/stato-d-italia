"use client";

import { useEffect, useRef, useState } from "react";
import type { MapOption } from "../lib/data";

type MapDataset = { values: [string, number][]; unit: string; periodStart: string; periodEnd: string };
type Ranking = { rows: Array<{ territoryId: string; name: string; istatCode: string; value: number; percentile: number | null; rank: number | null }> };
let protocol: import("pmtiles").Protocol | undefined;

function fillColorExpression(min: number, max: number): import("maplibre-gl").ExpressionSpecification {
  const midpoint = min + (max - min) / 2;
  return ["interpolate", ["linear"], ["coalesce", ["feature-state", "value"], min], min, "#f2e7be", midpoint, "#d98c4b", max, "#8e2f25"];
}

export function SoilMap({ option, geometryUrl, rankingUrl }: { option: MapOption; geometryUrl?: string; rankingUrl?: string }) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<import("maplibre-gl").Map | null>(null);
  const currentDataset = useRef<MapDataset | null>(null);
  const featureIds = useRef<string[]>([]);
  const [ranking, setRanking] = useState<Ranking | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mapReady, setMapReady] = useState(false);

  useEffect(() => {
    setMapReady(false);
    setError(null);
    const mapContainer = container.current;
    if (!geometryUrl || !mapContainer) { setError("PMTiles per livello non disponibile"); return; }
    const target: HTMLDivElement = mapContainer;
    const pmtilesUrl = geometryUrl;
    let map: import("maplibre-gl").Map | undefined;
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
        map = new maplibregl.Map({ container: target, style: {
          version: 8,
          sources: { territories: { type: "vector", url: `pmtiles://${pmtilesUrl}`, promoteId: "territory_id" } },
          layers: [
            { id: "background", type: "background", paint: { "background-color": "#f1f2ec" } },
            { id: "soil-fill", type: "fill", source: "territories", "source-layer": "territories", paint: { "fill-color": fillColorExpression(0, 1), "fill-opacity": 0.82 } },
            { id: "soil-line", type: "line", source: "territories", "source-layer": "territories", paint: { "line-color": "#fffdf7", "line-width": 0.4 } },
          ],
        }, center: [12.5, 42.8], zoom: 5 });
        const activeMap = map;
        activeMap.on("error", (event) => setError(event.error.message));
        activeMap.once("load", () => {
          if (disposed) return;
          mapRef.current = activeMap;
          setMapReady(true);
          activeMap.on("click", "soil-fill", (event) => {
            const feature = event.features?.[0];
            if (!feature) return;
            const value = activeMap.getFeatureState({ source: "territories", sourceLayer: "territories", id: feature.id }).value;
            new maplibregl.Popup().setLngLat(event.lngLat).setText(`${feature.properties?.territory_id}: ${Number(value).toLocaleString("it-IT")} ${currentDataset.current?.unit ?? ""}`).addTo(activeMap);
          });
        });
      } catch (caught) { setError(caught instanceof Error ? caught.message : "Errore mappa"); }
    }
    void createMap();
    return () => {
      disposed = true;
      mapRef.current = null;
      currentDataset.current = null;
      featureIds.current = [];
      map?.remove();
    };
  }, [geometryUrl]);

  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    const controller = new AbortController();
    async function updateValues() {
      try {
        const response = await fetch(option.url, { signal: controller.signal });
        if (!response.ok) throw new Error(`Map values ${response.status}`);
        const dataset = await response.json() as MapDataset;
        const values = dataset.values.map((item) => item[1]).filter(Number.isFinite);
        if (!values.length) throw new Error("Map values vuoti o non numerici");
        const activeMap = mapRef.current;
        if (controller.signal.aborted || !activeMap) return;
        featureIds.current.forEach((territoryId) => activeMap.removeFeatureState({ source: "territories", sourceLayer: "territories", id: territoryId }));
        dataset.values.forEach(([territoryId, value]) => activeMap.setFeatureState({ source: "territories", sourceLayer: "territories", id: territoryId }, { value }));
        featureIds.current = dataset.values.map(([territoryId]) => territoryId);
        currentDataset.current = dataset;
        activeMap.setPaintProperty("soil-fill", "fill-color", fillColorExpression(Math.min(...values), Math.max(...values)));
        setError(null);
      } catch (caught) {
        if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : "Errore valori mappa");
      }
    }
    void updateValues();
    return () => controller.abort();
  }, [mapReady, option.url]);

  useEffect(() => {
    setRanking(null);
    if (!rankingUrl) return;
    fetch(rankingUrl).then((response) => response.ok ? response.json() : Promise.reject(new Error(`Ranking ${response.status}`))).then(setRanking).catch(() => setRanking(null));
  }, [rankingUrl]);

  return <>
    <div className="map-meta"><strong>{option.metricId.replaceAll("_", " ")}</strong><span>{option.periodKey}</span></div>
    <div ref={container} className="map" aria-label="Mappa tematica. Dati completi nella tabella seguente." />
    {error && <p role="alert">{error}</p>}
    <section className="ranking" aria-labelledby="ranking-title"><h2 id="ranking-title">Ranking nazionale — alternativa alla mappa</h2>
      {ranking ? <table><thead><tr><th>Territorio</th><th>Valore</th><th>Rank</th><th>Percentile</th></tr></thead><tbody>{ranking.rows.slice(0, 25).map((row) => <tr key={row.territoryId}><th scope="row">{row.name} <small>{row.istatCode}</small></th><td>{row.value.toLocaleString("it-IT")}</td><td>{row.rank ?? "—"}</td><td>{row.percentile?.toFixed(1) ?? "—"}</td></tr>)}</tbody></table> : <p>Ranking non applicabile a questa metrica o gruppo.</p>}
    </section>
  </>;
}
