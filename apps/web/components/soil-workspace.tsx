"use client";

import Link from "next/link";
import { useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { MapOption, SoilData } from "../lib/data";
import { ExposedMenu, MapSidebar } from "./map-sidebar";
import { SoilMap } from "./soil-map";
import { TimelineControl } from "./timeline-control";

type MappableLevel = Exclude<MapOption["level"], "country">;

const metricLabels: Record<string, string> = {
  soil_net_consumption_hectares: "Incremento netto di suolo consumato",
  soil_gross_consumption_hectares: "Incremento lordo di suolo consumato",
  soil_restoration_hectares: "Ripristino di suolo",
  soil_consumed_hectares: "Suolo consumato (ha)",
  soil_consumed_share: "Suolo consumato (%)",
};

const metricUnits: Record<string, string> = { soil_net_consumption_hectares: "ha", soil_gross_consumption_hectares: "ha", soil_restoration_hectares: "ha", soil_consumed_hectares: "ha", soil_consumed_share: "%" };

function rankingPath(option: MapOption) {
  return `delivery/soil/rankings/${option.metricId}/${option.periodKey}/${option.level}.json`;
}

function comparePeriods(left: string, right: string) {
  return Number(left.slice(0, 4)) - Number(right.slice(0, 4)) || left.localeCompare(right);
}

function levelLabel(level: MappableLevel) {
  return level === "municipality" ? "Comuni" : level === "province" ? "Province" : "Regioni";
}

export function ThemeWorkspace({ data, themeLabel }: { data: SoilData; themeLabel: string }) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const metrics = useMemo(() => [...new Set(data.maps.map((item) => item.metricId))], [data.maps]);
  const requestedMetric = searchParams.get("metric");
  const metric = requestedMetric && metrics.includes(requestedMetric) ? requestedMetric : metrics[0];
  const levels = useMemo(() => Array.from(new Set(data.maps.filter((item) => item.metricId === metric).map((item) => item.level))).filter((item): item is MappableLevel => item !== "country"), [data.maps, metric]);
  const requestedLevel = searchParams.get("level") as MappableLevel | null;
  const level = requestedLevel && levels.includes(requestedLevel) ? requestedLevel : (levels.includes("municipality") ? "municipality" : levels[0]);
  const available = data.maps.filter((item) => item.metricId === metric && item.level === level).sort((left, right) => comparePeriods(left.periodKey, right.periodKey));
  const requestedPeriod = searchParams.get("period");
  const selected = available.find((item) => item.periodKey === requestedPeriod) ?? available.at(-1);
  const periods = available.map((item) => item.periodKey);

  function update(params: Record<string, string | undefined>) {
    const next = new URLSearchParams(searchParams.toString());
    Object.entries(params).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key));
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  }

  function changeMetric(nextMetric: string) {
    const nextLevels = Array.from(new Set(data.maps.filter((item) => item.metricId === nextMetric && item.level !== "country").map((item) => item.level))) as MappableLevel[];
    const nextLevel = nextLevels.includes(level) ? level : (nextLevels.includes("municipality") ? "municipality" : nextLevels[0]);
    const nextPeriods = data.maps.filter((item) => item.metricId === nextMetric && item.level === nextLevel).sort((left, right) => comparePeriods(left.periodKey, right.periodKey));
    update({ metric: nextMetric, level: nextLevel, period: nextPeriods.at(-1)?.periodKey, territory: undefined });
  }

  function changeLevel(nextLevel: MappableLevel) {
    const nextPeriod = data.maps.filter((item) => item.metricId === metric && item.level === nextLevel).sort((left, right) => comparePeriods(left.periodKey, right.periodKey)).at(-1)?.periodKey;
    update({ level: nextLevel, period: nextPeriod, territory: undefined });
  }

  return <section className="soil-site-layout" aria-label={`Esplorazione ${themeLabel}`}>
    <MapSidebar title="Consumo di suolo">
      <a className="sidebar-link sidebar-atlas-link" href="#mappa">Vai alla mappa ↓</a>
      <ExposedMenu label="Metrica" value={metric} onChange={changeMetric} items={metrics.map((id) => ({ id, label: metricLabels[id] ?? id, meta: metricUnits[id] }))} />
      <section className="sidebar-section"><h3>Livello territoriale</h3><div className="level-menu" role="group" aria-label="Livello territoriale">{levels.map((item) => <button type="button" key={item} onClick={() => changeLevel(item)} aria-pressed={item === level}>{levelLabel(item)}</button>)}</div></section>
      {selected && <section className="sidebar-section"><TimelineControl periods={periods} value={selected.periodKey} onChange={(period) => update({ period, territory: undefined })} /></section>}
      <section className="sidebar-section"><h3>Vista corrente</h3><p className="sidebar-context"><strong>{selected?.periodKey ?? "—"}</strong>{levelLabel(level)} · valori ufficiali ISPRA/SNPA.</p></section>
      <section className="sidebar-section"><p className="sidebar-context">Mappa: osservazioni ufficiali. Confronto e percentile solo quando pubblicati.</p></section>
      <Link className="sidebar-link" href="/">Panoramica nazionale →</Link>
    </MapSidebar>
    <div className="soil-site-content">
      <section className="soil-hero"><p className="eyebrow">ISPRA / SNPA · release {data.releaseId}</p><h1>Consumo di suolo</h1><p>Valori ufficiali per periodo. Analisi, ranking e percentili sono elaborazioni riproducibili del progetto.</p></section>
      <section id="mappa" className="soil-workspace" tabIndex={-1} aria-label="Mappa consumo di suolo">
        {selected ? <SoilMap option={selected} metricLabel={metricLabels[selected.metricId] ?? selected.metricId} geometryUrl={data.geometry[level]} rankingUrl={data.rankings[rankingPath(selected)]} selectedTerritoryId={searchParams.get("territory") ?? undefined} /> : <p role="alert">Combinazione non disponibile nella release attiva.</p>}
        <details className="provenance"><summary>Fonte, metodo, limiti</summary><p>Valori in mappa: osservazioni ufficiali. Ranking e percentili: elaborazioni riproducibili del progetto.</p><pre>{JSON.stringify(data.provenance, null, 2)}</pre></details>
      </section>
    </div>
  </section>;
}
