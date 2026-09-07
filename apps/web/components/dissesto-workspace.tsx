"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { DissestoData } from "../lib/data";
import { ExplorerToolbar } from "./explorer-toolbar";
import { SoilMap } from "./soil-map";
import { resolveExplorerModel, retainTerritoryForLevel, type MappableLevel } from "../lib/explorer-model";
import { shouldRenderMap } from "../lib/explorer-rendering";

const labels: Record<string, string> = {
  hydrogeological_flood_high_hazard_area_km2: "Superficie a pericolosità idraulica elevata",
  hydrogeological_flood_high_hazard_population: "Popolazione in area a pericolosità idraulica elevata",
  hydrogeological_landslide_very_high_hazard_area_km2: "Superficie a pericolosità da frana molto elevata",
  hydrogeological_landslide_very_high_hazard_population: "Popolazione in area a pericolosità da frana molto elevata",
};

const units: Record<string, string> = {
  hydrogeological_flood_high_hazard_area_km2: "km²",
  hydrogeological_flood_high_hazard_population: "persone",
  hydrogeological_landslide_very_high_hazard_area_km2: "km²",
  hydrogeological_landslide_very_high_hazard_population: "persone",
};

function levelLabel(level: MappableLevel) {
  return level === "municipality" ? "Comuni" : level === "province" ? "Province" : "Regioni";
}

export function DissestoWorkspace({ data }: { data: DissestoData }) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedMetric = searchParams.get("metric");
  const requestedLevel = searchParams.get("level");
  const requestedPeriod = searchParams.get("period");
  const modelFor = (requested: { metric?: string | null; level?: string | null; period?: string | null } = {}) => resolveExplorerModel({
    domain: "risk", maps: data.maps, geometry: data.geometry, mapGeometry: data.mapGeometry, rankings: data.rankings,
    requestedMetric: requested.metric ?? requestedMetric, requestedLevel: requested.level ?? requestedLevel, requestedPeriod: requested.period ?? requestedPeriod,
    preferences: { preferredLevel: "municipality" },
  });
  const model = modelFor();
  const metric = model.metricId;
  const level = model.level;
  const selected = model.selectedOption;
  const metrics = model.availableMetrics;
  const levels = model.availableLevels;
  const requestedTerritory = searchParams.get("territory") ?? undefined;
  const [territory, setTerritory] = useState<{ id: string; name?: string } | undefined>(() => requestedTerritory ? { id: requestedTerritory } : undefined);

  useEffect(() => {
    setTerritory((current) => requestedTerritory ? current?.id === requestedTerritory ? current : { id: requestedTerritory } : undefined);
  }, [requestedTerritory]);

  function update(params: Record<string, string | undefined>) {
    const next = new URLSearchParams(searchParams.toString());
    Object.entries(params).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key));
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  }

  const selectTerritory = useCallback((id: string, name?: string) => {
    setTerritory({ id, name });
    update({ territory: id });
  }, [pathname, router, searchParams]);

  function changeMetric(nextMetric: string) {
    const next = modelFor({ metric: nextMetric, level, period: null });
    const retainedTerritory = retainTerritoryForLevel(level, next.level, territory?.id ?? requestedTerritory);
    if (!retainedTerritory) setTerritory(undefined);
    update({ metric: next.metricId, level: next.level, period: next.periodKey, territory: retainedTerritory });
  }

  return <section className="domain-site-layout explorer-layout domain-dissesto" aria-label="Atlante dissesto">
    <div className="domain-site-content">
      <header className="workspace-header"><div><p className="eyebrow">ISPRA · piattaforma nazionale IdroGEO</p><h1>Dissesto</h1></div><p>Pericolosità da frana e alluvione alla scala dichiarata dalla fonte. Persone e superfici restano indicatori separati.</p><dl><div><dt>Copertura</dt><dd>Comuni · Province · Regioni</dd></div><div><dt>Snapshot</dt><dd>2020 · 2024</dd></div><div><dt>Ranking</dt><dd>Non applicato</dd></div></dl></header>
      <ExplorerToolbar label="Indicatore" value={metric ?? ""} onChange={changeMetric} items={metrics.map((id) => ({ id, label: labels[id] ?? id, meta: units[id] ?? "" }))} levels={levels.map((item) => ({ id: item, label: levelLabel(item) }))} level={level ?? ""} onLevelChange={(id) => { const next = modelFor({ level: id, period: null }); setTerritory(undefined); update({ level: next.level, period: next.periodKey, territory: undefined }); }} context={`${metric?.includes("flood") ? "Alluvioni · 2020" : "Frane · 2024"} · snapshot ufficiale`} />
      <section id="mappa" className="domain-workspace map-workspace-v2" tabIndex={-1} aria-label="Mappa del dissesto">
        {selected && shouldRenderMap(model.features.map) ? <SoilMap option={selected} metricLabel={labels[selected.metricId] ?? selected.metricId} geometryUrl={model.geometryUrl} features={model.features} selectedTerritoryId={territory?.id} currentTerritoryIds={data.currentTerritoryIds?.[selected.level]} colorRamp="dissesto" onTerritorySelect={selectTerritory} /> : <p role={model.features.map.status === "not_supported" ? "status" : "alert"}>{model.features.map.status === "not_supported" ? "Mappa non supportata per questo dominio." : "Mappa non disponibile nella release attiva."}</p>}
        <div className="map-reading-panel"><p>Il valore `-1` della fonte significa non disponibile: non diventa zero e non entra nella scala.</p></div>
        <details className="provenance"><summary>Fonte, metodo, limiti</summary><p>Valori ufficiali ISPRA IdroGEO. La scala colori mostra il valore, non un giudizio sul territorio.</p><pre>{JSON.stringify(data.provenance, null, 2)}</pre></details>
      </section>
    </div>
  </section>;
}
