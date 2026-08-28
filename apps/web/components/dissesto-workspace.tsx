"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { DissestoData, MapOption } from "../lib/data";
import { ExplorerToolbar } from "./explorer-toolbar";
import { SoilMap } from "./soil-map";

type MappableLevel = Exclude<MapOption["level"], "country">;

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
  const metrics = useMemo(() => [...new Set(data.maps.map((item) => item.metricId))], [data.maps]);
  const requestedMetric = searchParams.get("metric");
  const metric = requestedMetric && metrics.includes(requestedMetric) ? requestedMetric : metrics[0];
  const levels = useMemo(() => Array.from(new Set(data.maps.filter((item) => item.metricId === metric).map((item) => item.level))).filter((item): item is MappableLevel => item !== "country"), [data.maps, metric]);
  const requestedLevel = searchParams.get("level") as MappableLevel | null;
  const level = requestedLevel && levels.includes(requestedLevel) ? requestedLevel : (levels.includes("municipality") ? "municipality" : levels[0]);
  const selected = data.maps.find((item) => item.metricId === metric && item.level === level);
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
    const nextLevels = Array.from(new Set(data.maps.filter((item) => item.metricId === nextMetric && item.level !== "country").map((item) => item.level))) as MappableLevel[];
    const nextLevel = nextLevels.includes(level) ? level : (nextLevels.includes("municipality") ? "municipality" : nextLevels[0]);
    const retainedTerritory = nextLevel === level ? territory?.id ?? requestedTerritory : undefined;
    if (!retainedTerritory) setTerritory(undefined);
    update({ metric: nextMetric, level: nextLevel, territory: retainedTerritory });
  }

  return <section className="domain-site-layout explorer-layout domain-dissesto" aria-label="Atlante dissesto">
    <div className="domain-site-content">
      <header className="workspace-header"><div><p className="eyebrow">ISPRA · piattaforma nazionale IdroGEO</p><h1>Dissesto</h1></div><p>Pericolosità da frana e alluvione alla scala dichiarata dalla fonte. Persone e superfici restano indicatori separati.</p><dl><div><dt>Copertura</dt><dd>Comuni · Province · Regioni</dd></div><div><dt>Snapshot</dt><dd>2020 · 2024</dd></div><div><dt>Ranking</dt><dd>Non applicato</dd></div></dl></header>
      <ExplorerToolbar label="Indicatore" value={metric} onChange={changeMetric} items={metrics.map((id) => ({ id, label: labels[id] ?? id, meta: units[id] ?? "" }))} levels={levels.map((item) => ({ id: item, label: levelLabel(item) }))} level={level} onLevelChange={(id) => { setTerritory(undefined); update({ level: id, territory: undefined }); }} context={`${metric?.includes("flood") ? "Alluvioni · 2020" : "Frane · 2024"} · snapshot ufficiale`} />
      <section id="mappa" className="domain-workspace map-workspace-v2" tabIndex={-1} aria-label="Mappa del dissesto">
        {selected ? <SoilMap option={selected} metricLabel={labels[selected.metricId] ?? selected.metricId} geometryUrl={data.geometry[level]} selectedTerritoryId={territory?.id} seriesOptions={[selected]} colorRamp="dissesto" onTerritorySelect={selectTerritory} /> : <p role="alert">Combinazione metrica/livello non disponibile nella release attiva.</p>}
        <div className="map-reading-panel"><p>Il valore `-1` della fonte significa non disponibile: non diventa zero e non entra nella scala.</p></div>
        <details className="provenance"><summary>Fonte, metodo, limiti</summary><p>Valori ufficiali ISPRA IdroGEO. La scala colori mostra il valore, non un giudizio sul territorio.</p><pre>{JSON.stringify(data.provenance, null, 2)}</pre></details>
      </section>
    </div>
  </section>;
}
