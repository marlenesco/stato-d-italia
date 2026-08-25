"use client";

import { useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { DissestoData, MapOption } from "../lib/data";
import { ExposedMenu, MapSidebar } from "./map-sidebar";
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

  function update(params: Record<string, string | undefined>) {
    const next = new URLSearchParams(searchParams.toString());
    Object.entries(params).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key));
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  }

  function changeMetric(nextMetric: string) {
    const nextLevels = Array.from(new Set(data.maps.filter((item) => item.metricId === nextMetric && item.level !== "country").map((item) => item.level))) as MappableLevel[];
    update({ metric: nextMetric, level: nextLevels.includes(level) ? level : (nextLevels.includes("municipality") ? "municipality" : nextLevels[0]), territory: undefined });
  }

  return <section className="domain-site-layout domain-dissesto" aria-label="Atlante dissesto">
    <MapSidebar title="Atlante dissesto">
      <a className="sidebar-link sidebar-atlas-link" href="#mappa">Vai alla mappa ↓</a>
      <ExposedMenu label="Indicatore" value={metric} onChange={changeMetric} items={metrics.map((id) => ({ id, label: labels[id] ?? id, meta: units[id] ?? "" }))} />
      <section className="sidebar-section"><h3>Livello territoriale</h3><div className="level-menu" role="group" aria-label="Livello territoriale">{levels.map((item) => <button type="button" key={item} onClick={() => update({ level: item, territory: undefined })} aria-pressed={item === level}>{levelLabel(item)}</button>)}</div></section>
      <section className="sidebar-section"><h3>Riferimento</h3><p className="sidebar-context"><strong>{metric?.includes("flood") ? "Alluvioni · 2020" : "Frane · 2024"}</strong>Snapshot ufficiale ISPRA IdroGEO, non serie storica.</p></section>
      <section className="sidebar-section"><p className="sidebar-context">Valore `-1` fonte = non disponibile. Non diventa zero né entra nella scala.</p></section>
    </MapSidebar>
    <div className="domain-site-content">
      <section className="domain-hero"><div className="domain-hero-title"><p className="eyebrow">ISPRA · piattaforma nazionale IdroGEO</p><h1>Dissesto</h1></div><div className="domain-hero-copy"><p>Pericolosità da frana e alluvione letta alla scala dichiarata dalla fonte, con persone e superfici separate.</p><a className="primary-link" href="#mappa">Apri mappa <span aria-hidden="true">→</span></a></div><section className="domain-hero-context"><div><p className="eyebrow">Copertura</p><strong>Comuni · Province · Regioni</strong></div><p>Frane 2024. Alluvioni 2020. Nessun ranking derivato.</p></section></section>
      <section id="mappa" className="domain-workspace" tabIndex={-1} aria-label="Mappa del dissesto">
        {selected ? <SoilMap option={selected} metricLabel={labels[selected.metricId] ?? selected.metricId} geometryUrl={data.geometry[level]} selectedTerritoryId={searchParams.get("territory") ?? undefined} colorRamp="dissesto" /> : <p role="alert">Combinazione metrica/livello non disponibile nella release attiva.</p>}
        <details className="provenance"><summary>Fonte, metodo, limiti</summary><p>Valori ufficiali ISPRA IdroGEO. La scala colori mostra il valore, non un giudizio sul territorio.</p><pre>{JSON.stringify(data.provenance, null, 2)}</pre></details>
      </section>
    </div>
  </section>;
}
